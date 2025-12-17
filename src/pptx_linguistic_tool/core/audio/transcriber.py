# src/core/audio/transcriber.py
"""
Handles audio transcription using faster-whisper.
- Safe CUDA path patching on Windows virtualenvs with pip `nvidia/*` packages.
- Robust model init with fallback compute types (float16 -> float32 -> int8).
- Consistent logging that never raises.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, List, Optional

from pptx_linguistic_tool.utils.logging_utils import safe_log

DEFAULT_WHISPER_MODEL = "medium"
UNSAFE_LARGE_MODELS = {"large", "large-v2"}

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover
    WhisperModel = None  # allow tests to monkeypatch


def set_cuda_paths(log_fn: Optional[Callable[[str], None]] = None) -> None:
    """
    On Windows venvs with pip-installed `nvidia/*` wheels, add DLL folders to PATH.
    No-ops on other platforms. Never raises.
    """
    if os.name != "nt":
        return

    try:
        venv_base = Path(sys.executable).parent.parent
        nvidia_path = venv_base / "Lib" / "site-packages" / "nvidia"
        candidates = [
            nvidia_path / "cuda_runtime" / "bin",
            nvidia_path / "cublas" / "bin",
            nvidia_path / "cudnn" / "bin",
        ]
        to_prepend = [str(p) for p in candidates if p.exists()]

        if not to_prepend:
            return

        # Prepend to PATH; do not clobber existing value
        current = os.environ.get("PATH", "")
        new_path = os.pathsep.join(to_prepend + ([current] if current else []))
        os.environ["PATH"] = new_path
        # Set CUDA_PATH env hints if not set
        for key in ("CUDA_PATH", "CUDA_PATH_V12_4"):
            if key not in os.environ:
                os.environ[key] = os.pathsep.join(to_prepend)
        safe_log(log_fn, f"[INFO] CUDA DLL paths appended: {to_prepend}")
    except Exception as e:
        safe_log(log_fn, f"[WARN] set_cuda_paths failed (continuing without): {e}")


def _init_model(model_size: str, log_fn: Optional[Callable[[str], None]]) -> "WhisperModel":
    """
    Initialize WhisperModel with:
    - Automatic device choice (try CUDA, then CPU).
    - Safety guard: never run large/large-v2 on CUDA (fallback to DEFAULT_WHISPER_MODEL).
    - Graceful fallbacks for compute_type per device.
    """
    if WhisperModel is None:
        raise RuntimeError("faster-whisper is not installed or failed to import.")

    # What the user/config requested
    requested_model = model_size or DEFAULT_WHISPER_MODEL

    last_err: Optional[Exception] = None

    # Try CUDA first (fast), then CPU as fallback
    device_candidates = ["cuda", "cpu"]

    for device in device_candidates:
        # Pick the effective model name for this device
        effective_model = requested_model

        # Guard: large models on CUDA have been unstable → override to DEFAULT_WHISPER_MODEL
        if device == "cuda" and requested_model in UNSAFE_LARGE_MODELS:
            safe_log(
                log_fn,
                (
                    f"[WARN] Whisper model '{requested_model}' on CUDA has been unstable "
                    f"on this setup. Overriding to '{DEFAULT_WHISPER_MODEL}' for reliability."
                ),
            )
            effective_model = DEFAULT_WHISPER_MODEL

        # Compute-type candidates per device
        if device == "cuda":
            compute_candidates = ["float16", "float32", "int8"]
        else:
            compute_candidates = ["int8", "float32"]

        for compute_type in compute_candidates:
            try:
                safe_log(
                    log_fn,
                    f"[INFO] Loading faster-whisper model '{effective_model}' "
                    f"on device '{device}' (compute_type={compute_type})",
                )
                model = WhisperModel(
                    effective_model,
                    device=device,
                    compute_type=compute_type,
                )
                return model
            except Exception as e:
                last_err = e
                safe_log(
                    log_fn,
                    "[WARN] Model init failed with "
                    f"device={device}, compute_type={compute_type}, "
                    f"model='{effective_model}': {e}",
                )

    # If we reach here, all attempts failed
    raise RuntimeError(
        f"Failed to initialize faster-whisper model '{requested_model}' "
        f"on any device: {last_err}"
    )


def transcribe_audio_files(
    audio_dir: Path,
    output_dir: Path,
    model_size: str = DEFAULT_WHISPER_MODEL,
    log_fn: Callable[[str], None] = print,
) -> List[Path]:
    """
    Transcribes all .wav files in a directory using faster-whisper.

    Args:
        audio_dir: Directory containing WAV files.
        output_dir: Directory to save transcription .txt files.
        model_size: Whisper model variant (e.g., 'base', 'medium').
        log_fn: Logging function (GUI logger or print).

    Returns:
        List of saved .txt file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    set_cuda_paths(log_fn)

    try:
        model = _init_model(model_size, log_fn)
    except Exception as e:
        safe_log(log_fn, f"[ERROR] Could not load Whisper model '{model_size}': {e}")
        return []

    transcribed_files: List[Path] = []
    wav_files = sorted(audio_dir.glob("*.wav"))
    if not wav_files:
        safe_log(log_fn, f"[INFO] No .wav files found in: {audio_dir}")
        return transcribed_files

    for wav_file in wav_files:
        try:
            segments, _ = model.transcribe(str(wav_file))
            # Concatenate segment texts with spaces (simple, reliable)
            transcript = " ".join(getattr(s, "text", "") for s in segments).strip()
            out_path = output_dir / f"{wav_file.stem}.txt"
            out_path.write_text(transcript, encoding="utf-8")
            transcribed_files.append(out_path)
            safe_log(log_fn, f"[INFO] Transcribed: {wav_file.name} -> {out_path.name} ({len(transcript)} chars)")
        except Exception as e:
            safe_log(log_fn, f"[ERROR] Failed to transcribe {wav_file.name}: {e}")

    safe_log(log_fn, f"[INFO] Total transcripts written: {len(transcribed_files)}")
    return transcribed_files