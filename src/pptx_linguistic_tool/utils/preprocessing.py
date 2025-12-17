"""
preprocessing.py

Text normalization, cleanup, and sentence segmentation utilities used before translation and TTS.
- Unicode normalization (NFKC)
- Whitespace cleanup
- Punctuation-based chunking (optional helper)
- TTS sanitization
- Deterministic, dependency-free sentence segmentation that avoids variable-width lookbehinds
"""

from __future__ import annotations

import re
import unicodedata
from typing import List


# ---------------------------
# Basic normalization helpers
# ---------------------------

def normalize_text(text: str) -> str:
    """
    Apply Unicode NFKC normalization.
    """
    if text is None:
        return ""
    return unicodedata.normalize("NFKC", str(text))


def clean_whitespace(text: str) -> str:
    """
    Collapse multiple spaces, normalize newlines to single spaces, and trim.
    """
    if not text:
        return ""
    # Normalize unicode first, then whitespace
    t = normalize_text(text)
    # Replace internal newlines/tabs with spaces
    t = re.sub(r"[\t\r\n]+", " ", t)
    # Collapse repeated spaces
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def chunk_by_punctuation(text: str, max_len: int = 400) -> List[str]:
    """
    Split text by major punctuation while keeping punctuation attached to the chunk.
    Ensures each chunk length <= max_len (best-effort, non-greedy).
    Intended as a generic utility (not used directly by translator if sentence segmentation is used).
    """
    text = clean_whitespace(text)
    if not text:
        return []

    # First split by sentence-ish boundaries (., !, ?) but keep punctuation
    parts: List[str] = []
    start = 0
    for m in re.finditer(r'([.!?]["\')\]]*)\s+', text):
        end = m.end(1)
        seg = text[start:end].strip()
        if seg:
            parts.append(seg)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)

    # Further split overly long segments
    chunks: List[str] = []
    for seg in parts:
        if len(seg) <= max_len:
            chunks.append(seg)
            continue
        # If segment is too long, split on commas/semicolons as a fallback
        buf = seg
        while len(buf) > max_len:
            cut = buf.rfind(",", 0, max_len)
            if cut == -1:
                cut = buf.rfind(";", 0, max_len)
            if cut == -1:
                cut = buf.rfind(" ", 0, max_len)
            if cut == -1:
                # Hard cut
                cut = max_len
            chunks.append(buf[:cut].strip())
            buf = buf[cut:].lstrip(",; ").strip()
        if buf:
            chunks.append(buf)
    return chunks


def minimal_clean(text: str) -> str:
    """
    Backwards-compatible light cleanup used by TTS:
    - Unicode NFKC normalize
    - Collapse whitespace/newlines/tabs into single spaces
    - Trim
    """
    if not text:
        return ""
    t = normalize_text(text)
    t = re.sub(r"[ \t\r\n]+", " ", t)
    return t.strip()


def sanitize_for_tts(text: str) -> str:
    """
    Remove IPA/phonetic and combining-diacritic marks which some TTS models don’t handle.
    - Normalizes text (NFKC)
    - Strips IPA extensions (U+0250–U+02AF)
    - Strips modifier letters (U+02B0–U+02FF)
    - Strips combining diacritics (U+0300–U+036F)
    - Collapses repeated whitespace
    """
    t = normalize_text(text)
    # IPA + Modifier letters + Combining diacritics
    t = re.sub(r"[\u0250-\u02AF\u02B0-\u02FF\u0300-\u036F]", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


# -----------------------------------------
# Dependency-free sentence segmentation
# (mask dots in protected patterns, split,
# then unmask) — no lookbehinds used.
# -----------------------------------------

# Abbreviations to protect (DE+EN, case-insensitive). Extend as needed.
_ABBREV_WORDS = [
    "z.B", "bzw", "ca", "Nr", "S", "vgl", "u.a", "u.ä", "u.s.w", "etc",
    "Dr", "Prof", "Dipl", "Ing", "Mio", "Mrd", "No",
    "Mr", "Mrs", "Ms", "e.g", "i.e", "vs"
]

# Mask char for protected dots (choose a char unlikely to appear in texts)
_DOTMASK = "¤"

# Precompiled regexes
_ABBREV_REGEX = re.compile(
    r"\b(" + "|".join(map(re.escape, _ABBREV_WORDS)) + r")\.", re.IGNORECASE
)
_DECIMAL_DOT_REGEX = re.compile(r"(?<=\d)\.(?=\d)")
_INITIALS_REGEX = re.compile(r"\b(?:[A-ZÄÖÜ]\.){2,}", re.UNICODE)

# Split on end punctuation followed by space(s) and a likely sentence start
_SPLIT_REGEX = re.compile(r'([.!?]["\')\]]*)\s+(?=[A-ZÄÖÜ0-9])', re.UNICODE)


def _mask_abbreviations(s: str) -> str:
    # Replace dots in known abbreviations with mask (e.g., "z.B." -> "z¤B¤")
    def _repl(m: re.Match) -> str:
        return m.group(1).replace(".", _DOTMASK)
    return _ABBREV_REGEX.sub(_repl, s)


def _mask_decimals(s: str) -> str:
    # 3.14 -> 3¤14
    return _DECIMAL_DOT_REGEX.sub(_DOTMASK, s)


def _mask_initials(s: str) -> str:
    # "A.B.C." -> "A¤B¤C¤"
    def _repl(m: re.Match) -> str:
        return m.group(0).replace(".", _DOTMASK)
    return _INITIALS_REGEX.sub(_repl, s)


def _unmask(s: str) -> str:
    return s.replace(_DOTMASK, ".")


def segment_sentences(text: str) -> List[str]:
    """
    Split a line/paragraph into sentences using conservative rules:
    - Protects abbreviations (z.B., e.g.), decimals (3.14), initials (A.B.)
    - Splits on ., !, ? followed by whitespace and a likely sentence start
    Returns trimmed sentences, preserving end punctuation.
    """
    s = clean_whitespace(text)
    if not s:
        return []

    # Mask protected dots
    masked = _mask_initials(_mask_decimals(_mask_abbreviations(s)))

    # Split using a forward-looking pattern (no lookbehinds)
    parts: List[str] = []
    start = 0
    for m in _SPLIT_REGEX.finditer(masked):
        end = m.end(1)
        chunk = masked[start:end].strip()
        if chunk:
            parts.append(chunk)
        start = m.end()
    tail = masked[start:].strip()
    if tail:
        parts.append(tail)

    # Unmask protected dots in each piece
    return [_unmask(p) for p in parts]