# src/utils/ffmpeg_utils.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0


class FFmpegNotFound(Exception):
    """Raised when ffmpeg is not available on PATH."""


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg command fails."""


def ensure_ffmpeg() -> str:
    """
    Returns the absolute path to ffmpeg if found on PATH, else raises.
    """
    exe = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if not exe:
        raise FFmpegNotFound(
            "FFmpeg not found. Install it and make sure it's on PATH "
            "(e.g., https://ffmpeg.org/download.html)."
        )
    return exe


def _split_atempo_chain(factor: float) -> List[float]:
    """
    Splits an arbitrary tempo factor into a list of factors, each within [0.5, 2.0],
    so they can be chained as multiple `atempo=` filters.

    Examples:
      5.0  -> [2.0, 2.0, 1.25]
      0.125-> [0.5, 0.5, 0.5]
      1.75 -> [1.75]
    """
    if factor <= 0:
        raise ValueError("tempo factor must be > 0")

    pieces: List[float] = []
    f = float(factor)

    # Speed up (f >= 1)
    if f >= 1.0:
        while f > ATEMPO_MAX + 1e-9:
            pieces.append(ATEMPO_MAX)
            f /= ATEMPO_MAX
        pieces.append(round(f, 4))
    else:
        # Slow down (f < 1)
        while f < ATEMPO_MIN - 1e-9:
            pieces.append(ATEMPO_MIN)
            f /= ATEMPO_MIN
        pieces.append(round(f, 4))

    return pieces


def _fmt_cmd(cmd: list[str]) -> str:
    # Pretty printer for logs
    def q(x: str) -> str:
        return f'"{x}"' if (" " in x or "'" in x) else x
    return " ".join(q(c) for c in cmd)


def run_ffmpeg_command(cmd: list[str], log=print) -> None:
    """
    Runs an ffmpeg command and raises FFmpegError on failure.
    """
    log(f"$ {_fmt_cmd(cmd)}")
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    out = (proc.stdout or b"").decode(errors="ignore")
    if proc.returncode != 0:
        raise FFmpegError(out.strip() or "ffmpeg failed")
    # ffmpeg can be very verbose; keep success logs minimal
    tail = out.strip().splitlines()[-1] if out.strip() else "[ffmpeg ok]"
    log(tail)


def apply_atempo(
    input_audio: Path,
    output_audio: Path,
    tempo: float = 1.0,
    log=print,
    overwrite: bool = True,
) -> Path:
    """
    Applies a tempo change (speed without pitch shift) using ffmpeg's `atempo`.
    Works for arbitrary factors by chaining filters in [0.5, 2.0].

    Args:
        input_audio: path to source audio (any ffmpeg‑readable format)
        output_audio: path to destination (extension determines codec)
        tempo: e.g. 0.75 for 25% slower, 1.25 for 25% faster, 2.5, 0.33, etc.
        overwrite: pass -y to ffmpeg if True, otherwise -n

    Returns:
        Path to the written output file.
    """
    ffmpeg = ensure_ffmpeg()
    input_audio = Path(input_audio)
    output_audio = Path(output_audio)
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    if not input_audio.exists():
        raise FileNotFoundError(str(input_audio))

    # Fast path: if tempo==1 and same container, stream copy to avoid re-encode.
    if abs(tempo - 1.0) < 1e-9 and input_audio.suffix.lower() == output_audio.suffix.lower():
        cmd = [
            ffmpeg, "-hide_banner",
            "-y" if overwrite else "-n",
            "-i", str(input_audio),
            "-c:a", "copy",
            str(output_audio),
        ]
        run_ffmpeg_command(cmd, log)
        return output_audio

    # Build atempo filter chain
    chain = _split_atempo_chain(tempo)
    filter_expr = ",".join(f"atempo={p}" for p in chain)

    # Choose codec from extension (sensible defaults)
    ext = output_audio.suffix.lower()
    if ext in {".wav"}:
        audio_codec = ["-c:a", "pcm_s16le"]
    elif ext in {".m4a", ".mp4", ".aac"}:
        audio_codec = ["-c:a", "aac", "-b:a", "192k"]
    elif ext in {".mp3"}:
        audio_codec = ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        # Fallback to AAC which is widely compatible
        audio_codec = ["-c:a", "aac", "-b:a", "192k"]

    cmd = [
        ffmpeg, "-hide_banner",
        "-y" if overwrite else "-n",
        "-i", str(input_audio),
        "-filter:a", filter_expr,
        *audio_codec,
        str(output_audio),
    ]
    run_ffmpeg_command(cmd, log)
    return output_audio


def probe_duration_seconds(input_audio: Path) -> float | None:
    """
    Returns duration in seconds using ffprobe, or None on error.
    """
    ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_audio),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        return float((proc.stdout or b"").decode().strip())
    except Exception:
        return None
