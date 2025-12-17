# src/core/audio/audio_converter.py
"""
Converts extracted audio files from various formats to standardized .wav
using pydub (FFmpeg backend). Logs are consistent and never raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from pydub import AudioSegment

from pptx_linguistic_tool.utils.logging_utils import safe_log

SUPPORTED_INPUT_SUFFIXES = (".mp3", ".aac", ".wma", ".m4a", ".wav")


def convert_audio_to_wav(
    input_dir: Path,
    output_dir: Path,
    log_fn: Callable[[str], None] = print,
) -> List[Path]:
    """
    Converts all supported audio files in input_dir to .wav format.

    Args:
        input_dir: Directory containing input audio files.
        output_dir: Directory to store converted .wav files.
        log_fn: Logging function (GUI logger or print).

    Returns:
        List of converted .wav file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    converted_files: List[Path] = []

    files = sorted(p for p in input_dir.glob("*") if p.suffix.lower() in SUPPORTED_INPUT_SUFFIXES)
    if not files:
        safe_log(log_fn, f"[INFO] No supported audio found in: {input_dir}")
        return converted_files

    for file_path in files:
        try:
            audio = AudioSegment.from_file(file_path)  # ffmpeg detects codec/format
            wav_path = output_dir / f"{file_path.stem}.wav"
            audio.export(wav_path, format="wav")  # default PCM 16-bit
            converted_files.append(wav_path)
            safe_log(log_fn, f"[INFO] Converted: {file_path.name} -> {wav_path.name}")
        except Exception as e:
            safe_log(log_fn, f"[ERROR] Failed to convert {file_path.name}: {e}")

    safe_log(log_fn, f"[INFO] Total converted to WAV: {len(converted_files)}")
    return converted_files
