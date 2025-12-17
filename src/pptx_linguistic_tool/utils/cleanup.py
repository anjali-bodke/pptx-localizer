from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Optional

_TERM_MAP_CACHE: Optional[Dict[str, str]] = None


def _load_term_map(path: Path) -> Dict[str, str]:
    """Load and cache the JSON term map. Returns {} if file is missing/invalid."""
    global _TERM_MAP_CACHE
    if _TERM_MAP_CACHE is not None:
        return _TERM_MAP_CACHE
    try:
        if not path.exists():
            _TERM_MAP_CACHE = {}
            return _TERM_MAP_CACHE
        with path.open("r", encoding="utf-8") as f:
            _TERM_MAP_CACHE = json.load(f)
        _TERM_MAP_CACHE = {str(k).strip(): str(v).strip() for k, v in _TERM_MAP_CACHE.items()}
        return _TERM_MAP_CACHE
    except Exception:
        _TERM_MAP_CACHE = {}
        return _TERM_MAP_CACHE


def _light_line_cleanup(s: str) -> str:
    """
    Light, line-scoped cleanup that preserves literal '\\n' tokens:
      - trim
      - collapse internal whitespace (except across the literal '\\n')
      - normalize German quotes to straight quotes
      - normalize colon spacing
    """
    s = (s or "").strip()

    # keep literal '\n' tokens as markers inside a single PPT paragraph
    parts = s.split("\\n")
    parts = [" ".join(p.split()) for p in parts]
    s = "\\n".join(parts)

    # normalize quotes
    s = s.replace("„", "\"").replace("“", "\"").replace("‚", "'").replace("‘", "'")

    # normalize colon spacing (e.g., "Qzu : Heat" -> "Qzu: Heat")
    s = s.replace(" : ", ": ").replace("  :", ":")

    return s


# -------------------------
# Domain normalizations
# -------------------------

def _ordinal_en(n: int) -> str:
    """Return English ordinal suffix for editions."""
    if 10 <= n % 100 <= 20:
        suff = "th"
    else:
        suff = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suff}"


def _normalize_editions_line(line: str) -> str:
    """
    Convert patterns like:
      - '17. Auflage' -> '17th ed.'
      - '05. Auflage' -> '5th ed.'
    Only triggers when 'Auflage/Aufl.' explicitly appear (safe).
    """
    def repl_aufl(m: re.Match) -> str:
        num = int(m.group(1))
        return f"{_ordinal_en(num)} ed."

    # 17. Auflage / 05. Auflage
    line = re.sub(r"\b0*([0-9]{1,2})\.\s*Auflage\b", repl_aufl, line, flags=re.IGNORECASE)
    # 17. Aufl.
    line = re.sub(r"\b0*([0-9]{1,2})\.\s*Aufl\.\b", repl_aufl, line, flags=re.IGNORECASE)

    # Very specific mistranslation seen: "17. This article ..." -> replace only when that boilerplate follows.
    line = re.sub(
        r"\b0*([0-9]{1,2})\.\s+(?=This article incorporates text.*public domain\.)",
        lambda m: f"{_ordinal_en(int(m.group(1)))} ed.; ",
        line,
        flags=re.IGNORECASE,
    )
    return line


# --- Minimal, safe terminology normalization for recurring issues ---
# Keep this conservative: exact phrases or tight regexes only.
_NORMALIZATION_RULES: List[tuple[re.Pattern, str]] = [
    # Seiliger cycle name normalization (fix "Seiler" / "Sieliger")
    (re.compile(r"\bSeiler\b"), "Seiliger"),
    (re.compile(r"\bSieliger\b"), "Seiliger"),
    (re.compile(r"\bSieliger cycle\b", flags=re.IGNORECASE), "Seiliger cycle"),
    (re.compile(r"\bSeiler cycle\b", flags=re.IGNORECASE), "Seiliger cycle"),

    # Isochor -> isochoric, and phrasing for heat removal
    (re.compile(r"\bisochor heat\b", flags=re.IGNORECASE), "isochoric heat"),
    (re.compile(r"\bisochoric heat (dissipation|rejection)\b", flags=re.IGNORECASE), "isochoric heat removal"),

    # Known literal mistranslation from "Probeklausur"
    (re.compile(r"^Sample clearance$", flags=re.IGNORECASE), "Sample exam"),

    # Bibliography hallucinations: remove the boilerplate line entirely
    (re.compile(r"^This article incorporates text.*public domain\.\s*$", flags=re.IGNORECASE), ""),
    # Another spurious line observed
    (re.compile(r"^The European Community and the United States of America.*$", flags=re.IGNORECASE), ""),
    # Odd tail: "French literature" -> likely meant "Further literature"
    (re.compile(r"^\s*French literature\s*$", flags=re.IGNORECASE), "Further literature"),
]


def _apply_normalizations(line: str) -> str:
    out = line
    for pat, repl in _NORMALIZATION_RULES:
        out = pat.sub(repl, out)
    # Edition normalization (separate pass to allow context-sensitive handling)
    out = _normalize_editions_line(out)

    # Cleanup any accidental double spaces after removals
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


# -------------------------
# Public helpers
# -------------------------

def apply_glossary_cleanup_to_lines(
    lines: List[str],
    term_map_path: Path = Path("src/utils/term_map.json"),
    expand_exact_matches: bool = True,
) -> List[str]:
    """
    Legacy helper: Light cleanup + optional exact-key expansion using only the translated line.
    Preserves 1:1 line mapping and keeps literal '\\n' tokens intact.
    """
    term_map = _load_term_map(term_map_path)
    cleaned: List[str] = []

    for raw in lines:
        line = (raw or "").rstrip("\n")
        line_clean = _light_line_cleanup(line)

        if expand_exact_matches:
            key = line_clean.strip()
            if key and key in term_map:
                line_clean = f"{key}: {term_map[key]}"

        # final small normalizations (incl. bibliography/editions)
        line_clean = _apply_normalizations(line_clean)

        cleaned.append(line_clean)

    return cleaned


def apply_glossary_cleanup_with_source(
    src_lines: List[str],
    out_lines: List[str],
    term_map_path: Path = Path("src/utils/term_map.json"),
    expand_exact_matches: bool = True,
) -> List[str]:
    """
    Preferred helper: Light cleanup + EXACT expansion based on the ORIGINAL SOURCE LINE.
    If the *source* line exactly matches a glossary key, we force the mapped expansion,
    regardless of what the translator produced.

    Preserves 1:1 line mapping and keeps literal '\\n' tokens intact.
    """
    term_map = _load_term_map(term_map_path)
    cleaned: List[str] = []
    n = max(len(src_lines), len(out_lines))

    for i in range(n):
        src = (src_lines[i] if i < len(src_lines) else "") or ""
        out = (out_lines[i] if i < len(out_lines) else "") or ""

        src_key = _light_line_cleanup(src).strip()
        out_clean = _light_line_cleanup(out)

        if expand_exact_matches and src_key and src_key in term_map:
            # Force canonical expansion using the *source* key
            out_clean = f"{src_key}: {term_map[src_key]}"

        # final small normalizations (incl. bibliography/editions)
        out_clean = _apply_normalizations(out_clean)

        cleaned.append(out_clean)

    return cleaned
0