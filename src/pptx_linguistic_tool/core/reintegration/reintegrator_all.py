# reintegration_all.py — Hybrid reintegrator (paragraph-first, math-safe)

from __future__ import annotations
from pathlib import Path
import shutil, zipfile, tempfile
import lxml.etree as ET

# Namespaces
NS_A  = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P  = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_M  = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS    = {"a": NS_A, "p": NS_P, "ct": NS_CT, "m": NS_M}

ET.register_namespace("a", NS_A)
ET.register_namespace("p", NS_P)

# ----------------- logging -----------------
def _log(msg, log_fn=print):
    if log_fn:
        try:
            log_fn(msg)
        except Exception:
            pass

# ----------------- tiny helpers -----------------
def _read_lines(txt: Path) -> list[str]:
    if not txt.exists():
        return []
    return txt.read_text(encoding="utf-8").splitlines()

def _split_keep_seps(s: str) -> list[tuple[str, str]]:
    """Return list of (segment, sep) where sep in {'', '\\n', '\\t'}.
    Handles both real '\n'/'\t' and literal '\\n'/'\\t' sequences from TXT."""
    out, buf, i = [], [], 0
    while i < len(s):
        ch = s[i]
        # literal sequences: \n or \t
        if ch == "\\" and i + 1 < len(s) and s[i+1] in ("n", "t"):
            out.append(("".join(buf), "\\n" if s[i+1] == "n" else "\\t"))
            buf = []
            i += 2
            continue
        # real embedded newline/tab (just in case)
        if ch == "\n" or ch == "\t":
            out.append(("".join(buf), "\\n" if ch == "\n" else "\\t"))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append(("".join(buf), ""))
    return out

# ----------------- XML collectors -----------------
def _find_runs(root: ET.Element) -> list[ET.Element]:
    """All <a:t> in slide (for quick run-level counts)."""
    return root.findall(".//a:t", namespaces=NS)

def _shape_is_skipped_placeholder(sp_el: ET.Element) -> bool:
    """Skip date/footer/header/slide-number placeholders on a <p:sp>."""
    ph = sp_el.find(".//p:nvSpPr/p:nvPr/p:ph", namespaces=NS)
    if ph is None:
        return False
    ph_type = ph.get("type")
    return ph_type in {"sldNum", "dt", "ftr", "hdr"}

def _collect_paragraphs_from_node(node: ET.Element, acc: list[ET.Element]):
    """
    Recursively collect <a:p> paragraphs:
      - From shapes <p:sp> (unless skipped placeholder)
      - From group shapes <p:grpSp>
      - From graphic frames (tables, smartart) by scanning for any descendant <a:p>
    """
    tag = node.tag

    # Shape with text body
    if tag == f"{{{NS_P}}}sp":
        if _shape_is_skipped_placeholder(node):
            return
        tx = node.find("./p:txBody", namespaces=NS)
        if tx is not None:
            acc.extend(tx.findall(".//a:p", namespaces=NS))
        return

    # Group shape: recurse into children
    if tag == f"{{{NS_P}}}grpSp":
        for child in node:
            _collect_paragraphs_from_node(child, acc)
        return

    # Graphic frame (charts, tables, smartart); scan any descendant <a:p>
    if tag == f"{{{NS_P}}}graphicFrame":
        acc.extend(node.findall(".//a:p", namespaces=NS))
        return

    # Generic recursion
    for child in node:
        _collect_paragraphs_from_node(child, acc)

def _collect_paragraphs(root: ET.Element) -> list[ET.Element]:
    """
    Collect <a:p> paragraphs in reading order across the slide tree,
    including groups and graphic frames. Skips only dt/ftr/hdr/sldNum placeholders.
    """
    paras: list[ET.Element] = []
    sp_tree = root.find(".//p:cSld/p:spTree", namespaces=NS)
    if sp_tree is None:
        paras.extend(root.findall(".//a:p", namespaces=NS))
        return paras
    for child in sp_tree:
        _collect_paragraphs_from_node(child, paras)
    return paras


def _visible_plaintext_outside_math(p_el: ET.Element) -> str:
    """
    Concatenate text from <a:t> nodes that are NOT inside math.
    """
    t_nodes = p_el.xpath(".//a:r[not(ancestor::m:oMath or ancestor::m:oMathPara)]/a:t", namespaces=NS)
    return "".join((t.text or "") for t in t_nodes)

def _set_xml_space_preserve(t_el: ET.Element):
    # ensure spaces/tabs aren’t collapsed
    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

def _replace_plaintext_preserving_math(p_el: ET.Element, new_text: str):
    """
    Replace only the 'plain text' part of a paragraph.
    Keep <a:br/>, <a:tab/>, any <m:oMath*> exactly as they are.
    Strategy: put full new_text into the first eligible <a:t>, blank the rest.
    """
    t_nodes = p_el.xpath(".//a:r[not(ancestor::m:oMath or ancestor::m:oMathPara)]/a:t", namespaces=NS)
    if not t_nodes:
        return  # nothing to replace (formula-only paragraph etc.)
    first = True
    for t in t_nodes:
        if first:
            t.text = new_text
            _set_xml_space_preserve(t)
            first = False
        else:
            t.text = ""

# ----------------- writers -----------------
def _replace_single_t_with_segments(t_el: ET.Element, text: str):
    """Replace one <a:t> with a sequence of <a:t> and <a:br>/<a:tab> in its parent."""
    parent = t_el.getparent()
    parent.remove(t_el)
    for seg, sep in _split_keep_seps(text or ""):
        t = ET.Element(f"{{{NS_A}}}t")
        t.text = seg
        _set_xml_space_preserve(t)
        parent.append(t)
        if sep == "\\n":
            parent.append(ET.Element(f"{{{NS_A}}}br"))
        elif sep == "\\t":
            parent.append(ET.Element(f"{{{NS_A}}}tab"))

# ----------------- slide-level methods -----------------
def _patch_slide_runs(xml_path: Path, lines: list[str], log_fn=print) -> int:
    """Run-level overwrite (legacy-compatible)."""
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(str(xml_path), parser)
    root = tree.getroot()

    t_nodes = _find_runs(root)
    n_xml, n_txt = len(t_nodes), len(lines)

    if n_txt < n_xml:
        lines = lines + [""] * (n_xml - n_txt)
    elif n_txt > n_xml:
        _log(f"[WARN] {xml_path.name}: truncating {n_txt-n_xml} extra TXT lines for run-level patch", log_fn)
        lines = lines[:n_xml]

    for t_el, text in zip(t_nodes, lines):
        _replace_single_t_with_segments(t_el, text)

    tree.write(str(xml_path), encoding="utf-8", xml_declaration=True, pretty_print=True)
    return n_xml

def _patch_slide_paragraphs(xml_path: Path, lines: list[str], log_fn=print) -> int:
    """
    Paragraph-level overwrite, but **math-safe**:
    - Only replace plain text (<a:t> outside math) in each paragraph.
    - Leave math (<m:oMath*>) and existing <a:br/>/<a:tab/> structure intact.
    - One TXT line is applied to one paragraph that actually has visible plain text.
    """
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(str(xml_path), parser)
    root = tree.getroot()

    p_nodes = _collect_paragraphs(root)
    n_xml, n_txt = len(p_nodes), len(lines)

    if n_xml == 0:
        _log(f"[INFO] {xml_path.name}: no paragraphs found", log_fn)
        return 0

    if n_txt < n_xml:
        lines = lines + [""] * (n_xml - n_txt)
    elif n_txt > n_xml:
        _log(f"[WARN] {xml_path.name}: truncating {n_txt-n_xml} extra TXT lines for paragraph-level patch", log_fn)
        lines = lines[:n_xml]

    for p_el, text in zip(p_nodes, lines):
        visible = _visible_plaintext_outside_math(p_el).strip()
        if visible:
            _replace_plaintext_preserving_math(p_el, text)
        else:
            # Paragraph without non-math text: keep as-is to preserve formulas/structure.
            pass

    tree.write(str(xml_path), encoding="utf-8", xml_declaration=True, pretty_print=True)
    return n_xml

# ----------------- hybrid chooser -----------------
def _choose_method(n_runs: int, n_lines: int) -> str:
    """
    Prefer PARAGRAPHS to avoid merged titles. Use RUNS only for near-exact matches.
    """
    if n_lines == 0:
        return "paragraphs"
    ratio = n_runs / float(n_lines)
    diff = abs(n_runs - n_lines)
    if 0.90 <= ratio <= 1.15 and diff <= 2:
        return "runs"
    return "paragraphs"

def _patch_slide_hybrid(xml_path: Path, txt_lines: list[str], log_fn=print) -> tuple[str, int, int]:
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(str(xml_path), parser)
    root = tree.getroot()

    n_runs = len(_find_runs(root))
    method = _choose_method(n_runs, len(txt_lines))

    if method == "runs":
        count = _patch_slide_runs(xml_path, txt_lines, log_fn)
    else:
        count = _patch_slide_paragraphs(xml_path, txt_lines, log_fn)
    return method, n_runs, count

# ----------------- public API: TEXT -----------------
def reintegrate_translated_slide_text(pptx_in: Path, txt_dir: Path, pptx_out: Path, log_fn=print) -> int:
    modified = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        with zipfile.ZipFile(pptx_in, "r") as zin:
            zin.extractall(tmpdir_path)

        slides_dir = tmpdir_path / "ppt" / "slides"
        for slide_xml in sorted(slides_dir.glob("slide*.xml")):
            slide_num = int(slide_xml.stem.replace("slide", ""))
            txt = txt_dir / f"slide{slide_num}.txt"
            lines = _read_lines(txt)
            if not lines:
                _log(f"[SKIP] slide{slide_num}.txt not found or empty.", log_fn)
                continue

            method, n_runs, wrote = _patch_slide_hybrid(slide_xml, lines, log_fn)
            _log(f"[INFO] Slide {slide_num}: method={method}, runs={n_runs}, wrote={wrote}", log_fn)
            if wrote > 0:
                modified += 1

        with zipfile.ZipFile(pptx_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for f in tmpdir_path.rglob("*"):
                if f.is_file():
                    zout.write(f, f.relative_to(tmpdir_path))

    _log(f"[DONE] Saved text-reintegrated PPTX -> {pptx_out}", log_fn)
    return modified

# ----------------- public API: AUDIO (unchanged) -----------------
def reintegrate_audio_to_pptx(pptx_path: Path, tts_dir: Path, log_fn=print, output_fn=print) -> int:
    replaced = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        with zipfile.ZipFile(pptx_path, "r") as zin:
            zin.extractall(tmpdir_path)

        ppt_media_dir = tmpdir_path / "ppt" / "media"
        content_types  = tmpdir_path / "[Content_Types].xml"

        # ensure m4a is declared
        try:
            tree = ET.parse(str(content_types))
            root = tree.getroot()
            if not any(e.attrib.get("Extension") == "m4a"
                       for e in root.findall(".//ct:Default", namespaces=NS)):
                entry = ET.Element(f"{{{NS_CT}}}Default", Extension="m4a", ContentType="audio/mp4")
                root.append(entry)
                tree.write(str(content_types), xml_declaration=True, encoding="utf-8", pretty_print=True)
        except Exception as e:
            _log(f"[ERROR] Failed to patch content types: {e}", log_fn)

        for audio in tts_dir.glob("*.m4a"):
            target = ppt_media_dir / audio.name
            if target.exists():
                shutil.copy2(audio, target)
                replaced += 1
                _log(f"[INFO] Replaced {target.name}", log_fn)

        new_pptx = pptx_path.with_suffix(".tmp.pptx")
        with zipfile.ZipFile(new_pptx, "w", zipfile.ZIP_DEFLATED) as zout:
            for f in tmpdir_path.rglob("*"):
                if f.is_file():
                    zout.write(f, f.relative_to(tmpdir_path))
        shutil.move(new_pptx, pptx_path)

    _log(f"[DONE] Audio reintegration: {replaced} file(s)", log_fn)
    return replaced

# ----------------- combined -----------------
def reintegrate_text_and_audio(pptx_in: Path, txt_dir: Path, tts_dir: Path, pptx_out: Path, log_fn=print, output_fn=print):
    shutil.copy2(pptx_in, pptx_out)
    reintegrate_translated_slide_text(pptx_out, txt_dir, pptx_out, log_fn)
    reintegrate_audio_to_pptx(pptx_out, tts_dir, log_fn, output_fn)
