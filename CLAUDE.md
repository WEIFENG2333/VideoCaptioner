# CLAUDE.md - AI Assistant Guide for VideoCaptioner

This document provides essential context for AI assistants working with the VideoCaptioner codebase.

## Project Overview

**VideoCaptioner** (卡卡字幕助手) is an AI-powered desktop application for video captioning that provides:

- **Speech Recognition (ASR)** - Convert audio to text via multiple backends (Whisper, B-Cut, Jianying APIs)
- **Subtitle Processing** - Intelligent splitting, optimization, and correction using LLMs
- **Translation** - AI-powered contextual translation with reflection mechanism
- **Video Synthesis** - Embed styled subtitles into videos

**Tech Stack:** Python 3.10-3.12, PyQt5 with Fluent Widgets (GUI), OpenAI-compatible LLM APIs

## Quick Reference

```bash
# Install CLI only (no GUI dependencies)
pip install videocaptioner

# Install with GUI
pip install videocaptioner[gui]

# Development install
uv sync

# Run GUI application
uv run python main.py

# Run CLI
uv run videocaptioner --help
uv run videocaptioner process video.mp4 --translate en
uv run videocaptioner transcribe audio.mp3 --model whisper-api

# Type checking
uv run pyright

# Code linting
uv run ruff check .

# Run tests
uv run pytest tests/
```

## CLI Usage

The CLI is completely decoupled from GUI and can be installed separately.

### Installation

```bash
# CLI only (lightweight, no PyQt5)
pip install videocaptioner

# With GUI support
pip install videocaptioner[gui]
```

### Commands

```bash
# Full pipeline: transcribe + split + translate
videocaptioner process video.mp4 --translate en --format srt

# Transcribe only
videocaptioner transcribe audio.mp3 --model whisper-api --language zh

# Process existing subtitle
videocaptioner subtitle input.srt --translate ja --translator google

# Initialize config file
videocaptioner config --init
```

### Environment Variables

```bash
VIDEOCAPTIONER_API_KEY      # LLM API key (or OPENAI_API_KEY)
VIDEOCAPTIONER_BASE_URL     # LLM API base URL (or OPENAI_BASE_URL)
VIDEOCAPTIONER_WHISPER_KEY  # Whisper API key
VIDEOCAPTIONER_WHISPER_URL  # Whisper API base URL
VIDEOCAPTIONER_OUTPUT_DIR   # Default output directory
```

### Configuration File

Place at `~/.videocaptioner/config.yaml` or `./videocaptioner.yaml`:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini

whisper:
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  model: whisper-1

transcribe:
  model: whisper-api
  language: ""  # auto-detect

translate:
  service: llm
  target_language: zh
```

## Project Structure

```
VideoCaptioner/
├── app/                        # Main application source code
│   ├── cli/                    # CLI module (no GUI dependency)
│   │   ├── __init__.py
│   │   ├── main.py            # CLI entry point
│   │   ├── config.py          # CLI config loader (env/file/args)
│   │   └── pipeline.py        # Synchronous processing pipeline
│   ├── common/                 # Shared modules
│   │   ├── config.py          # GUI configuration management
│   │   └── signal_bus.py      # PyQt5 signal bus for event communication
│   ├── components/             # Reusable UI components (dialogs, widgets)
│   ├── core/                   # Core business logic (GUI-independent)
│   │   ├── asr/               # Speech recognition (Whisper, APIs)
│   │   ├── translate/         # Translation engines (LLM, Google, Bing)
│   │   ├── split/             # Subtitle splitting algorithms
│   │   ├── optimize/          # Text optimization
│   │   ├── subtitle/          # Subtitle rendering (ASS format)
│   │   ├── tts/               # Text-to-speech
│   │   ├── llm/               # LLM client and utilities
│   │   ├── prompts/           # LLM prompt templates
│   │   ├── utils/             # Utility modules
│   │   ├── entities.py        # Data models and enums
│   │   └── task_factory.py    # Task creation factory
│   ├── thread/                 # Background worker threads (GUI)
│   └── view/                   # UI views/interfaces (GUI)
├── resource/                   # Application resources
│   ├── assets/                # UI assets, QSS stylesheets
│   ├── fonts/                 # Font files
│   ├── subtitle_style/        # Subtitle style templates
│   └── translations/          # i18n translation files
├── tests/                      # Test suite
├── scripts/                    # Development and build scripts
├── docs/                       # VitePress documentation
├── main.py                     # GUI application entry point
└── pyproject.toml             # Project configuration
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `main.py` | GUI application entry point, PyQt5 setup |
| `app/cli/main.py` | CLI entry point, argument parsing |
| `app/cli/config.py` | CLI config loader (env vars, yaml, args) |
| `app/cli/pipeline.py` | Synchronous processing pipeline for CLI |
| `app/core/entities.py` | Core data models: `SubtitleProcessData`, task configs, enums |
| `app/core/task_factory.py` | Creates typed task objects from user inputs |
| `app/common/config.py` | GUI persistent settings management |
| `app/common/signal_bus.py` | Inter-component event communication (GUI) |
| `app/view/main_window.py` | Main application window (GUI) |
| `app/core/asr/base.py` | Base ASR class with caching support |
| `app/core/translate/base.py` | Base translator interface |

## Architecture Patterns

### Layered Architecture

```
UI Layer (PyQt5 + Fluent Widgets)
    ↓
Signal Bus (Event Communication)
    ↓
Threading Layer (Background Workers)
    ↓
Core Business Logic (ASR, Translation, Rendering)
    ↓
Utilities & Infrastructure
```

### Key Design Patterns

1. **Factory Pattern** - `TaskFactory` creates typed task objects
2. **Signal/Slot Pattern** - PyQt5 signals for UI communication
3. **Strategy Pattern** - Multiple interchangeable ASR/translation implementations
4. **Worker Thread Pattern** - Background processing for non-blocking UI

### Data Flow

```
User Input → Task Creation → ASR (Speech→Text) → Splitting → Optimization → Translation → Rendering → Output
```

## Code Conventions

### Python Style

- **Line length:** 100 characters (ruff configured)
- **Linting:** E, F, I, W rules via ruff
- **Type checking:** pyright in basic mode
- **Python version:** 3.10+ syntax allowed

### Import Organization

```python
# Standard library
import os
from pathlib import Path

# Third-party
from PyQt5.QtCore import Qt
from openai import OpenAI

# Local imports
from app.core.entities import SubtitleProcessData
from app.common.config import cfg
```

### Naming Conventions

- **Files:** `snake_case.py`
- **Classes:** `PascalCase`
- **Functions/methods:** `snake_case`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private members:** `_leading_underscore`

### Dataclass Usage

The codebase uses dataclasses extensively for data models:

```python
@dataclass
class SubtitleProcessData:
    """字幕处理数据"""
    index: int
    original_text: str
    translated_text: str = ""
    optimized_text: str = ""
```

### Error Handling

- Use `tenacity` for retry logic on API calls
- Log errors via the centralized logger (`app/core/utils/logger.py`)
- Emit signals for UI error feedback

## Testing

### Test Structure

```
tests/
├── test_asr/          # Speech recognition tests
├── test_translate/    # Translation tests
├── test_optimize/     # Optimization tests
├── test_split/        # Splitting algorithm tests
├── test_subtitle/     # Subtitle rendering tests
├── test_tts/          # Text-to-speech tests
├── test_thread/       # Threading tests
├── fixtures/          # Test data
└── conftest.py        # Shared fixtures
```

### Test Markers

```python
@pytest.mark.integration  # Requires external services
@pytest.mark.slow         # Long-running tests
@pytest.mark.llm          # Requires LLM API access
@pytest.mark.translator   # Translation module tests
```

### Running Tests

```bash
# All tests
uv run pytest tests/

# Specific module
uv run pytest tests/test_translate/ -v

# Skip integration tests
uv run pytest tests/ -m "not integration"

# With coverage
uv run pytest tests/ --cov=app
```

### Test Environment

Tests use a `.env` file in the `tests/` directory for API keys:

```
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
```

## LLM Integration

### Client Usage

```python
from app.core.llm.client import get_llm_client

client = get_llm_client()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}]
)
```

### Prompt Templates

Prompts are stored in `app/core/prompts/`:
- `analysis_prompts.py` - Content analysis
- `translate_prompts.py` - Translation instructions
- `split_prompts.py` - Splitting rules
- `optimize_prompts.py` - Optimization guidelines

## UI Development

### Signal Bus Pattern

```python
from app.common.signal_bus import signalBus

# Emit signal
signalBus.subtitle_layout_changed.emit()

# Connect to signal
signalBus.subtitle_layout_changed.connect(self.on_layout_changed)
```

### Thread Communication

Worker threads emit signals to update UI:

```python
class TranscriptThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(ASRData)
    error = pyqtSignal(str)
```

## Common Tasks

### Adding a New ASR Backend

1. Create class in `app/core/asr/` extending `BaseASR`
2. Implement `transcribe()` method
3. Add to `app/core/asr/__init__.py`
4. Register in transcription interface

### Adding a New Translator

1. Create class in `app/core/translate/` extending base translator
2. Implement `translate()` method
3. Add to `TranslatorServiceEnum` in `entities.py`
4. Register in factory (`app/core/translate/factory.py`)

### Adding a New UI Component

1. Create widget in `app/components/`
2. Use PyQt-Fluent-Widgets for consistent styling
3. Connect via signal bus if needed
4. Add to relevant view/interface

## Dependencies

### Core Dependencies (CLI)

- **openai** - LLM API client
- **yt-dlp** - Video downloading
- **diskcache** - Caching layer
- **pydub** - Audio processing
- **tenacity** - Retry logic
- **pyyaml** - Configuration files
- **pillow** - Image processing

### GUI Dependencies (optional)

- **PyQt5** (5.15.11) - UI framework
- **PyQt-Fluent-Widgets** (1.8.4) - Modern UI components

### Development Dependencies

- **pyright** - Type checking
- **ruff** - Linting and formatting
- **pytest** - Testing

## Platform Notes

### Windows
- Uses PyQt5-Qt5==5.15.2 (specific version for compatibility)
- Pre-built executables available in releases

### macOS/Linux
- Uses PyQt5-Qt5>=5.15.11
- Requires FFmpeg installed (`brew install ffmpeg`)
- Run via `./scripts/run.sh` for automated setup

## Important Paths

```python
from app.config import (
    ROOT_PATH,      # Project root
    RESOURCE_PATH,  # resource/
    APPDATA_PATH,   # AppData/
    WORK_PATH,      # work-dir/ (output)
    MODEL_PATH,     # AppData/models/
    CACHE_PATH,     # AppData/cache/
    LOG_PATH,       # AppData/logs/
)
```

## Debugging Tips

1. **Enable logging:** Check `AppData/logs/` for detailed logs
2. **LLM debugging:** Use `app/view/llm_logs_interface.py` to view LLM requests
3. **Cache issues:** Clear `AppData/cache/` or disable cache in settings
4. **PyQt issues:** Check `QT_QPA_PLATFORM_PLUGIN_PATH` environment variable

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- Commit messages: Descriptive, in English or Chinese

## Documentation

- **User docs:** `docs/` (VitePress, Chinese/English)
- **API docs:** `docs/en/dev/`
- **Changelog:** `CHANGELOG.md`

## Resources

- **GitHub:** https://github.com/WEIFENG2333/VideoCaptioner
- **Documentation:** https://weifeng2333.github.io/VideoCaptioner/
- **Issues:** https://github.com/WEIFENG2333/VideoCaptioner/issues
