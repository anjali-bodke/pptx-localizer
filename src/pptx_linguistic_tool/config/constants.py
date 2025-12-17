# src/config/constants.py

# ---- TTS / audio synthesis ----
TTS_LANGUAGE_MODEL_MAP = {
    "English": "tts_models/en/ljspeech/fast_pitch",
    "German": "tts_models/de/thorsten/fast_pitch",
}
TTS_BITRATE = "192k"
TTS_CHUNK_PAUSE_MS = 250
TTS_FADE_MS = 10

# Auto-tempo (duration matching)
AUTO_DEADBAND_SEC = 1.0
AUTO_DEADBAND_RATIO = 0.03
AUTO_CLAMP_BOUNDS = (0.50, 1.25)  # (min, max) tempo

# ---- Translation / pipeline ----
# reserved for future tweaks (line limits, etc.)
MAX_TRANSLATION_LINE_LEN = 2000
