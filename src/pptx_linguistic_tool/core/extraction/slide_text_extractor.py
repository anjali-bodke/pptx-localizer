"""
slide_text_extractor.py — RAW XML extractor (stable 1:1 lines) + audio

Why this version:
- Some slides (like your slide 2) store text in shapes python-pptx doesn't expose as TextFrames
  (e.g., SmartArt/graphicFrame or nested containers). We read slide XML directly.
Stable contract preserved:
- One TXT line = one PPT paragraph.
- Internal <a:br/> become the literal '\\n' in the TXT (so reintegration stays 1:1).
- Tabs <a:tab/> -> '\t'.
- Skips placeholders of type date/slide-number/header/footer.

Also includes the same audio extractor.
"""

from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

# Namespaces
NS = {
    "p":  "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a":  "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r":  "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m":  "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

# Placeholder types to skip (date/slide-number/footer/header)
_SKIP_PH_TYPES = {"dt", "sldNum", "ftr", "hdr"}


def _text_from_run(a_r: ET.Element) -> str:
    """
    Collect visible text in a run:
      - <a:t>
      - any OfficeMath <m:t> nested under the run
      - <a:tab/> -> '\t'
      - <a:br/>  -> '\n'
    """
    out: list[str] = []

    # Tabs / breaks that are direct children of <a:r>
    for child in a_r:
        tag = child.tag
        if tag == f"{{{NS['a']}}}t":
            out.append(child.text or "")
        elif tag == f"{{{NS['a']}}}tab":
            out.append("\t")
        elif tag == f"{{{NS['a']}}}br":
            out.append("\n")

    # Any OfficeMath text inside the run
    for mt in a_r.findall(".//m:t", NS):
        if mt.text:
            out.append(mt.text)

    return "".join(out)

def _extract_paragraph_text(p_elem: ET.Element, lstStyle: ET.Element | None) -> str:
    """
    Convert <a:p> into text:
      - prepend bullet char if defined either on pPr or inherited from lstStyle (lvl*)
      - concatenate text from runs and their math
      - convert <a:br/> to '\n' and <a:tab/> to '\t'
    """
    # Paragraph-level bullet
    bullet = ""
    pPr = p_elem.find("a:pPr", NS)
    if pPr is not None:
        buChar = pPr.find("a:buChar", NS)
        if buChar is not None:
            ch = buChar.get("char")
            if ch:
                bullet = ch

    # If no explicit bullet, try inheritance via lstStyle and paragraph level
    if not bullet and lstStyle is not None:
        lvl = 0
        if pPr is not None and pPr.get("lvl") is not None:
            try:
                lvl = int(pPr.get("lvl") or "0")
            except Exception:
                lvl = 0
        lvl_name = f"a:lvl{max(1, min(9, lvl + 1))}pPr"
        lvl_pPr = lstStyle.find(lvl_name, NS)
        if lvl_pPr is not None:
            buChar2 = lvl_pPr.find("a:buChar", NS)
            if buChar2 is not None:
                ch2 = buChar2.get("char")
                if ch2:
                    bullet = ch2

    # Body text from runs and math
    out: list[str] = []
    for child in p_elem:
        tag = child.tag
        if tag == f"{{{NS['a']}}}r" or tag == f"{{{NS['a']}}}fld":
            out.append(_text_from_run(child))
        elif tag == f"{{{NS['a']}}}br":
            out.append("\n")
        elif tag == f"{{{NS['a']}}}tab":
            out.append("\t")
        # stray math <m:t> directly under <a:p>
        elif tag == f"{{{NS['m']}}}t":
            if child.text:
                out.append(child.text)

    body = "".join(out)

    if bullet:
        # Do not insert a space if body starts with punctuation like ':'
        return bullet + ("" if body[:1] in (":", ";", ".", ",", ")", "-", "—", "·", " ") else " ") + body
    return body


def _iter_all_paragraphs_from_slide_xml(slide_xml: bytes):
    """
    Yield text for every <a:p> under any text body on the slide.
    Supports both a:txBody and p:txBody, and handles inherited bullets.
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(slide_xml)

    # Collect ALL text bodies (some decks use a:txBody, others p:txBody)
    tx_bodies = []
    tx_bodies += root.findall(".//a:txBody", NS)
    tx_bodies += root.findall(".//p:txBody", NS)

    for txBody in tx_bodies:
        # ---- SAFER PLACEHOLDER CHECK (don’t over-skip) ----
        # Try to locate the owning <p:sp> that literally contains this txBody
        skip_this = False
        for sp in root.findall(".//p:sp", NS):
            # Does this <p:sp> subtree contain THIS txBody element?
            contains = False
            for node in sp.iter():
                if node is txBody:
                    contains = True
                    break
            if contains:
                ph = sp.find(".//p:ph", NS)
                # Only skip known trivial placeholders
                if ph is not None and (ph.get("type") in _SKIP_PH_TYPES):
                    skip_this = True
                break
        if skip_this:
            continue

        # Paragraph list style (for inherited bullets)
        # (a:lstStyle is always DrawingML 'a' ns even when the body is p:txBody)
        lstStyle = txBody.find("a:lstStyle", NS)

        # Emit every paragraph in this text body
        for p_elem in txBody.findall("./a:p", NS):
            yield _extract_paragraph_text(p_elem, lstStyle)


# ---------------------------
# Slide text extraction API
# ---------------------------

def extract_slide_text(pptx_path: Path, output_dir: Path, log_fn=print) -> list[Path]:
    """
    Extract text for each slide by reading ppt/slides/slideN.xml directly.

    Writes one .txt per slide; each TEXT FILE LINE == one PPT paragraph.
    Any <a:br/> inside a paragraph is serialized as the literal '\\n'.
    """
    if not pptx_path.exists() or pptx_path.suffix.lower() != ".pptx":
        raise ValueError("Invalid PowerPoint file path.")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []

    # Open the PPTX as a zip once
    with zipfile.ZipFile(pptx_path, "r") as zf:
        # Count slides by probing ppt/slides/slide{i}.xml
        slide_idx = 1
        while True:
            name = f"ppt/slides/slide{slide_idx}.xml"
            if name not in zf.namelist():
                break
            xml_bytes = zf.read(name)
            lines = list(_iter_all_paragraphs_from_slide_xml(xml_bytes))

            out_file = output_dir / f"slide{slide_idx}.txt"
            # Escape internal newlines so we keep 1 line per paragraph
            out_file.write_text("\n".join(s.replace("\n", "\\n") for s in lines), encoding="utf-8")
            log_fn(f"[INFO] slide{slide_idx}.txt: {len(lines)} paragraphs")
            saved_files.append(out_file)

            slide_idx += 1

    return saved_files


# ---------------------------
# Audio extraction
# ---------------------------

def extract_audio_from_pptx(pptx_path: Path, output_dir: Path, log_fn=print) -> list[Path]:
    """
    Extracts embedded audio files from a PowerPoint (.pptx) file into
    <output_dir>/media using the original PPTX basenames (e.g., media42.m4a).
    """
    if not pptx_path.exists() or pptx_path.suffix.lower() != ".pptx":
        raise ValueError("Invalid PowerPoint file path.")

    audio_extensions = {".m4a", ".mp3", ".aac", ".wav", ".wma"}
    media_dir = output_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Optional safety: remove old audio so leftovers don't confuse tests
    for p in media_dir.glob("*"):
        if p.suffix.lower() in audio_extensions:
            try:
                p.unlink()
            except Exception:
                pass

    extracted_files: list[Path] = []

    import zipfile
    with zipfile.ZipFile(pptx_path, "r") as archive:
        # Do NOT sort and do NOT renumber; keep original PPTX basenames.
        for file in archive.namelist():
            if file.startswith("ppt/media/") and not file.endswith("/"):
                ext = Path(file).suffix.lower()
                if ext in audio_extensions:
                    orig_name = Path(file).name  # <- keep original name, e.g. "media42.m4a"
                    out_path = media_dir / orig_name
                    with open(out_path, "wb") as f:
                        f.write(archive.read(file))
                    extracted_files.append(out_path)

    log_fn(f"[INFO][NEW] extracted {len(extracted_files)} audio file(s) to {media_dir}")
    return extracted_files