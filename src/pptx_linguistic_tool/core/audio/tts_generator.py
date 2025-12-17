# src/core/audio/tts_generator.py
"""
Generates TTS audio from text files using Coqui TTS, and converts output to .m4a format.
Supports pitch-preserving tempo adjustment via FFmpeg's `atempo` filter.
Dynamic tempo selection matches original audio durations when available.

User-controlled tempo has been removed. Only automatic duration matching is applied,
driven by the detected synthesized vs original durations and deadband/clamp settings.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from TTS.api import TTS
from pydub import AudioSegment

from pptx_linguistic_tool.config.constants import (
    TTS_BITRATE,
    TTS_CHUNK_PAUSE_MS,
    TTS_FADE_MS,
)

from pptx_linguistic_tool.utils.preprocessing import (
    minimal_clean,
    chunk_by_punctuation as split_by_punctuation,
    sanitize_for_tts,
)
from pptx_linguistic_tool.utils.ffmpeg_utils import (
    apply_atempo,
    probe_duration_seconds,
    FFmpegNotFound,  # ensure this exists in ffmpeg_utils
)



def _safe_log(log: Callable[[str], None], msg: str) -> None:
    try:
        log(msg)
    except Exception:
        # never allow logging to crash pipeline
        pass


def _choose_tempo_to_match(
    synth_dur: Optional[float],
    orig_dur: Optional[float],
    *,
    deadband_sec: float = 1.0,
    deadband_ratio: float = 0.03,
    clamp_bounds: Tuple[float, float] = (0.50, 1.25),
) -> Optional[float]:
    """
    Decide an auto-tempo so that (synth_dur / tempo) ~= orig_dur.

    formula:
        tempo = synth_dur / orig_dur
    because FFmpeg applies: new_duration = synth_dur / tempo

    Returns:
        float tempo if both durations are available and outside deadband; otherwise None.
    """
    if synth_dur is None or orig_dur is None:
        return None
    if synth_dur <= 0 or orig_dur <= 0:
        return None

    # Skip if already close to target duration
    if abs(synth_dur - orig_dur) <= max(deadband_sec, deadband_ratio * orig_dur):
        return None  # means "keep as-is (1.0)"

    raw = synth_dur / orig_dur  # ← FIXED (previously inverted)
    lo, hi = clamp_bounds
    tempo = min(max(raw, lo), hi)
    return tempo


def _find_original_audio(stem: str, original_audio_dir: Optional[Path]) -> Optional[Path]:
    """
    Resolve the path to the original audio using the same stem (e.g., media1.m4a).
    Tries common audio extensions if the exact m4a doesn't exist.
    """
    if not original_audio_dir:
        return None
    if not original_audio_dir.exists():
        return None

    candidates = [
        original_audio_dir / f"{stem}.m4a",
        original_audio_dir / f"{stem}.mp3",
        original_audio_dir / f"{stem}.wav",
        original_audio_dir / f"{stem}.aac",
        original_audio_dir / f"{stem}.m4b",
        original_audio_dir / f"{stem}.ogg",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def text_to_speech(
    text_dir: Path,
    output_dir: Path,
    source_lang: str,
    target_lang: str,
    model_map: Dict[str, str],
    log: Callable[[str], None] = print,
    output: Optional[Callable[[str], None]] = None,
    *,
    bitrate: str = "192k",
    # Folder where the original (pre-existing) slide audio lives
    original_audio_dir: Optional[Path] = None,
    # Auto-tempo controls
    auto_deadband_sec: float = 1.0,
    auto_deadband_ratio: float = 0.03,
    auto_clamp_bounds: Tuple[float, float] = (0.50, 1.25),
    tts_lang: str | None = None
) -> List[Path]:
    """
    Converts .txt files in `text_dir` to .m4a audio using Coqui TTS.
    Optionally matches durations to original audio by dynamically choosing tempo.

    Args:
        source_lang (str): Reserved for future multilingual TTS support.
        target_lang (str): "en" → English model map key; else "German".
        bitrate (str): AAC bitrate for final m4a.
        original_audio_dir (Path): Directory containing original audio files with same stem (e.g., media1.m4a).
        auto_deadband_sec (float): Absolute seconds tolerance where tempo change is skipped.
        auto_deadband_ratio (float): Relative tolerance of original duration (e.g., 0.03 = 3%).
        auto_clamp_bounds (tuple): Min/max tempo to apply when auto-tempo kicks in.

    Returns:
        List[Path]: Paths to generated .m4a files.
    """
    # Decide model based on dropdown (tts_lang) if provided
    if tts_lang and tts_lang in model_map:
        lang_key = tts_lang
    else:
        # Fallback: old behavior
        lang_key = "English" if target_lang == "en" else "German"

    model_name = model_map.get(lang_key)
    if not model_name:
        raise ValueError(f"No TTS model configured for {lang_key}")

    tts = TTS(model_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files: List[Path] = []

    for text_file in sorted(text_dir.glob("*.txt")):
        try:
            raw_text = text_file.read_text(encoding="utf-8")
            cleaned = minimal_clean(raw_text)

            # Sanitize for TTS (remove unsupported chars)
            safe = sanitize_for_tts(cleaned)
            removed = len(cleaned) - len(safe)
            if removed > 0:
                _safe_log(log, f"[INFO] Sanitized {removed} character(s) not supported by TTS in {text_file.name}")

            # Chunk by punctuation (existing utility)
            chunks = split_by_punctuation(safe)

            combined = AudioSegment.silent(duration=0)
            pause = AudioSegment.silent(duration=TTS_CHUNK_PAUSE_MS)

            for i, chunk in enumerate(chunks):
                chunk_wav = output_dir / f"{text_file.stem}_chunk{i}.wav"
                tts.tts_to_file(text=chunk, file_path=str(chunk_wav))
                chunk_audio = AudioSegment.from_wav(chunk_wav)
                combined += chunk_audio.fade_in(TTS_FADE_MS).fade_out(TTS_FADE_MS) + pause
                try:
                    chunk_wav.unlink()
                except Exception:
                    pass

            # Export synthesized audio
            m4a_path = output_dir / f"{text_file.stem}.m4a"
            combined.export(m4a_path, format="ipod", bitrate=bitrate or TTS_BITRATE)

            # --- Measure synthesized duration
            synth_dur = probe_duration_seconds(m4a_path)

            # --- Try to locate and measure original audio
            orig_path = _find_original_audio(text_file.stem, original_audio_dir)
            orig_dur = probe_duration_seconds(orig_path) if orig_path else None

            # --- Decide on dynamic tempo (no manual tempo path)
            auto_tempo = _choose_tempo_to_match(
                synth_dur,
                orig_dur,
                deadband_sec=auto_deadband_sec,
                deadband_ratio=auto_deadband_ratio,
                clamp_bounds=auto_clamp_bounds,
            )

            if auto_tempo is not None:
                try:
                    tmp_out = m4a_path.with_suffix(".tmp.m4a")
                    apply_atempo(m4a_path, tmp_out, tempo=auto_tempo)
                    tmp_out.replace(m4a_path)

                    new_dur = probe_duration_seconds(m4a_path)

                    if orig_dur is not None and synth_dur is not None and new_dur is not None:
                        _safe_log(log, (
                            f"[INFO] Auto-tempo applied to {m4a_path.name}: "
                            f"synth {synth_dur:.3f}s → new {new_dur:.3f}s vs orig {orig_dur:.3f}s "
                            f"(tempo={auto_tempo:.3f})"
                        ))
                    else:
                        _safe_log(log, f"[INFO] Auto-tempo applied to {m4a_path.name} (tempo={auto_tempo:.3f}).")

                except FFmpegNotFound:
                    _safe_log(log, f"[WARN] FFmpeg not found. Skipping auto-tempo for {m4a_path.name} (wanted tempo={auto_tempo}).")
                except Exception as e:
                    _safe_log(log, f"[WARN] Tempo change failed for {m4a_path.name}: {e}. Keeping unmodified audio.")
            else:
                # Nothing to do; either within deadband or no durations available
                if orig_dur is not None and synth_dur is not None:
                    _safe_log(log, (
                        f"[INFO] Within deadband for {m4a_path.name}: synth {synth_dur:.3f}s vs orig {orig_dur:.3f}s. "
                        "No tempo change applied."
                    ))

            audio_files.append(m4a_path)
            _safe_log(log, f"[INFO] Generated TTS: {m4a_path.name} from {len(chunks)} chunks")

        except Exception as e:
            _safe_log(log, f"[ERROR] Failed TTS for {text_file.name}: {e}")

    if output:
        try:
            output(f"{len(audio_files)} audio files saved in: {output_dir}")
        except Exception:
            pass

    return audio_files