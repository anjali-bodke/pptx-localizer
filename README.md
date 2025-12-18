# PPTX Linguistic Tool

An **offline Windows desktop application** that automates **audio extraction, transcription, translation, text-to-speech (TTS), and reintegration** for PowerPoint (`.pptx`) files.  
Designed for **educational use** and **non-technical users**.

---

## Overview

The **PPTX Linguistic Tool** enables multilingual transformation of PowerPoint presentations by:

- Extracting embedded audio and slide text
- Transcribing spoken content using Whisper
- Translating text using NLLB models
- Regenerating speech via TTS
- Reintegrating translated text and audio back into the original presentation

All processing is **fully offline** once models are downloaded.

---

## Features

- Windows GUI application (Tkinter)
- Step-by-step processing pipeline
- Offline transcription, translation, and TTS
- Handles large presentations with embedded audio
- Modular, extensible architecture
- No cloud services or external APIs

---

## Processing Pipeline

1. **Extract**
   - Embedded audio
   - Slide text (paragraph-level)
2. **Convert**
   - Audio normalization and WAV conversion
3. **Transcribe**
   - Speech-to-text using Faster-Whisper
4. **Translate**
   - Text translation using NLLB (offline)
5. **Generate TTS**
   - Speech synthesis using Coqui TTS
6. **Reintegrate**
   - Replace slide text and audio in the original PPTX

---

## System Architecture (High Level)

- **GUI Layer**
  - Handles user interaction and step control
- **Core Pipeline**
  - Extraction, transcription, translation, TTS, reintegration
- **Utilities**
  - Logging, preprocessing, cleanup, FFmpeg helpers
- **Packaging Layer**
  - Python package and Windows executable (in progress)

---