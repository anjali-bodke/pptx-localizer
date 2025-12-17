# src/core/translation/translator_interface.py
"""
Translation interfaces for slide text (line-aligned) and transcripts (full text).
Backed by NLLB-200 via src.core.translation.nllb_model.NLLBTranslator.

- Consistent, no-raise logging via safe_log
- Deterministic ordering of files
- Slide text preserves 1:1 line alignment for reintegration
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from pptx_linguistic_tool.utils.logging_utils import safe_log
from pptx_linguistic_tool.utils.preprocessing import segment_sentences
from pptx_linguistic_tool.core.translation.nllb_model import NLLBTranslator  # type: ignore

# ---- Optional glossary cleanup (can be disabled) ----
GLOSSARY_ON = True  # set to False to disable glossary-based cleanup

try:
    from pptx_linguistic_tool.utils.cleanup import (
        apply_glossary_cleanup_to_lines,
        apply_glossary_cleanup_with_source,
    )
    _HAS_CLEANUP = True
except Exception:
    _HAS_CLEANUP = False
    GLOSSARY_ON = False


LANG_MAP = {
    "de": "deu_Latn",
    "en": "eng_Latn",
    # extend as needed
}


def _norm_lang(code: str) -> str:
    return LANG_MAP.get(code, code)


def translate_text_files(
    input_dir: Path,
    output_dir: Path,
    source_lang: str,
    target_lang: str,
    log: Callable[[str], None] | None = print,
    output: Callable[[str], None] | None = None,
) -> List[Path]:
    """
    Translates slide text files **line-by-line** to preserve alignment.

    Returns:
        List of output .txt paths.
    """
    log = log or (lambda *_: None)
    output = output or (lambda *_: None)

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    src = _norm_lang(source_lang)
    tgt = _norm_lang(target_lang)

    try:
        translator = NLLBTranslator(src, tgt)
        safe_log(log, f"[INFO] NLLB translator initialized: {src} -> {tgt}")
    except Exception as e:
        safe_log(log, f"[ERROR] Failed to initialize NLLB translator {src}->{tgt}: {e}")
        return []

    translated_files: List[Path] = []
    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        safe_log(log, f"[INFO] No .txt files found in: {input_dir}")
        return translated_files

    for txt_file in txt_files:
        try:
            src_lines = txt_file.read_text(encoding="utf-8").splitlines()
            out_lines: List[str] = []
            total = len(src_lines)

            for i, line in enumerate(src_lines, start=1):
                clean = (line or "").strip()

                # Preserve alignment for blank/non-alpha/very-long lines
                if (
                    not clean
                    or not any(c.isalpha() for c in clean)
                    or len(clean) > 300
                    or (clean.count("/") >= 3 and not clean.endswith(".com"))
                ):
                    out_lines.append("")  # keep 1:1 line mapping
                    continue

                safe_log(log, f"[INFO] Translating {txt_file.name} line {i}/{total}")

                try:
                    sentences = segment_sentences(clean) or [clean]
                    translated_chunks: List[str] = []
                    for sent in sentences:
                        s = sent.strip()
                        if not s:
                            continue
                        chunk = translator.translate(s, log=None) or ""
                        translated_chunks.append(chunk.strip())

                    translated_line = " ".join(ch for ch in translated_chunks if ch)
                    out_lines.append(translated_line.strip())
                except Exception as e:
                    safe_log(log, f"[WARN] Translation failed for {txt_file.name} line {i}: {e}")
                    out_lines.append("")  # preserve alignment on failure

            # ---- Optional glossary + light cleanup ----
            if GLOSSARY_ON and _HAS_CLEANUP:
                try:
                    # Prefer the source-aware variant to correct mistranslated abbreviations
                    out_lines = apply_glossary_cleanup_with_source(
                        src_lines,
                        out_lines,
                        term_map_path=Path("src/utils/term_map.json"),
                        expand_exact_matches=True,
                    )
                except Exception:
                    # Fallback: attempt line-only cleanup
                    try:
                        out_lines = apply_glossary_cleanup_to_lines(
                            out_lines,
                            term_map_path=Path("src/utils/term_map.json"),
                            expand_exact_matches=True,
                        )
                    except Exception as e2:
                        safe_log(log, f"[WARN] Glossary cleanup skipped for {txt_file.name}: {e2}")

            out_path = output_dir / txt_file.name
            out_path.write_text("\n".join(out_lines), encoding="utf-8")
            translated_files.append(out_path)
            safe_log(log, f"[INFO] Saved: {out_path.name}")
        except Exception as e:
            safe_log(log, f"[ERROR] Failed to translate {txt_file.name}: {e}")

    safe_log(output, f"Translated {len(translated_files)} slide .txt files → {output_dir}")
    return translated_files


def translate_transcript_files(
    input_dir: Path,
    output_dir: Path,
    source_lang: str,
    target_lang: str,
    log: Callable[[str], None] | None = print,
    output: Callable[[str], None] | None = None,
) -> List[Path]:
    """
    Translates full transcript files (one block of text per file).
    (No glossary cleanup here to avoid altering free-form text; keep behavior unchanged.)
    """
    log = log or (lambda *_: None)
    output = output or (lambda *_: None)

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    src = _norm_lang(source_lang)
    tgt = _norm_lang(target_lang)

    try:
        translator = NLLBTranslator(src, tgt)
        safe_log(log, f"[INFO] NLLB translator initialized: {src} -> {tgt}")
    except Exception as e:
        safe_log(log, f"[ERROR] Failed to initialize NLLB translator {src}->{tgt}: {e}")
        return []

    translated_files: List[Path] = []
    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        safe_log(log, f"[INFO] No .txt files found in: {input_dir}")
        return translated_files

    for txt_file in txt_files:
        try:
            text = txt_file.read_text(encoding="utf-8").strip()
            if not text or not any(c.isalpha() for c in text):
                out_path = output_dir / txt_file.name
                out_path.write_text("", encoding="utf-8")
                translated_files.append(out_path)
                safe_log(log, f"[INFO] Skipped empty/non-alpha: {txt_file.name}")
                continue

            safe_log(log, f"[INFO] Translating {txt_file.name} (full file)")
            translated = (translator.translate(text) or "").strip()
            out_path = output_dir / txt_file.name
            out_path.write_text(translated, encoding="utf-8")
            translated_files.append(out_path)
            safe_log(log, f"[INFO] Saved: {out_path.name}")
        except Exception as e:
            safe_log(log, f"[ERROR] Failed to translate {txt_file.name}: {e}")

    safe_log(output, f"Translated {len(translated_files)} transcript files → {output_dir}")
    return translated_files
