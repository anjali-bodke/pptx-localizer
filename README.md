# OpenEduVoice

<p align="center">
  <img src="assets/logo.png" alt="Project Logo" width="200"/>
</p>

An **offline Windows desktop application** that automates **audio extraction, transcription, translation, text-to-speech (TTS), and reintegration** for PowerPoint (`.pptx`) files.  
Designed for **educational use** and **non-technical users**.

---

## Overview

The **OpenEduVoice** enables multilingual transformation of PowerPoint presentations by:

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

## Reproduce & Run OpenEduVoice (Windows)

### Prerequisites

1. **Python v3.11**
   - Only **Python 3.11.x** is supported.
   - Download installer:  
     https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe  
   - During installation, **check “Add Python to PATH”**.

2. **NVIDIA GPU + Driver**  
   - Strongly recommended for faster transcription and TTS.
   - CPU mode is supported but significantly slower.

Once you ensure prerequisites are fullfilled.

---

### 1. Clone the Repository

#### Option A: Using Git(If git is preinstalled in the system)
```bash
git clone https://github.com/anjali-bodke/openeduvoice.git
```

#### Option B: If Git not present on Computer
- Click the Code button on the repository page.
- Select Download ZIP and extract the folder.

- (Optional) Install Git for future use: https://github.com/git-for-windows/git/releases/download/v2.52.0.windows.1/Git-2.52.0-64-bit.exe

### 2. Launch the Application.
- Open the project folder
- Click on **start_OpenEduVoice.bat**, It will require some time to install and configure everything.
- Successfull installation will open the GUI.

### 3. Utilize GUI to test out the project

1. Select a `.pptx` file

2. Choose the step to be performed:
   - Extract Audio
   - Convert to WAV
   - Transcribe
   - Translate Text
   - Generate TTS Audio
   - Reintegrate

All output will be stored in:
```
YourFile_transcript/
├── media/             # Extracted audio
├── converted_wav/     # Converted .wav files
├── transcripts/       # Whisper transcripts
├── translated/        # NLLB-200 based translated text
├── tts_audio/         # Coqui-regenerated speech
└── {original_name}_combined.pptx  #Presentation with translated Audio
```
---