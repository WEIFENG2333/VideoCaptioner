# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VideoCaptioner（卡卡字幕助手）is a video subtitle processing assistant based on Large Language Models (LLM). It's a PyQt5 desktop application that supports speech recognition, subtitle segmentation, optimization, and translation workflows.

## Development Commands

### Running the Application

```bash
python main.py
```

### Installing Dependencies

```bash
pip install -r requirements.txt
```

### Running Tests

The project uses a test utility for OpenAI API connectivity testing:

```bash
python app/core/utils/test_opanai.py
```

## Architecture Overview

### Core Components

1. **Main Entry Point**: `main.py` - Initializes the PyQt5 application with proper exception handling and translation support

2. **Application Structure**:
   - `app/view/` - PyQt5 UI components and interfaces
   - `app/core/` - Core business logic
   - `app/thread/` - Background processing threads
   - `app/components/` - Reusable UI components
   - `app/common/` - Shared utilities and configuration

3. **Core Processing Pipeline**:
   - **Speech Recognition** (`app/core/bk_asr/`) - Multiple ASR engines including Whisper variants
   - **Subtitle Processing** (`app/core/subtitle_processor/`) - LLM-based optimization, splitting, and translation
   - **Task Management** (`app/core/task_factory.py`) - Creates and manages different task types
   - **Storage** (`app/core/storage/`) - Database and caching layer

4. **Key Services**:
   - **Transcription**: B接口, J接口, WhisperCpp, FasterWhisper
   - **LLM Integration**: OpenAI-compatible APIs for subtitle optimization
   - **Translation**: LLM-based, DeepL, Microsoft, Google translation services

5. **Configuration**:
   - Settings stored in `AppData/settings.json`
   - Paths configured in `app/config.py`
   - User preferences managed via `app/common/config.py`

6. **Resource Management**:
   - Models stored in `AppData/models/`
   - Subtitle styles in `resource/subtitle_style/`
   - Binary dependencies in `resource/bin/`

## Key Architectural Patterns

- **Multi-threaded Processing**: Heavy operations run in separate QThreads to keep UI responsive
- **Signal-based Communication**: Uses PyQt5 signals for thread-safe communication
- **Task Factory Pattern**: Centralized task creation with proper configuration
- **Caching Strategy**: ASR results and LLM responses cached to reduce API calls
- **Modular ASR Support**: Abstract base class allows easy addition of new ASR engines
