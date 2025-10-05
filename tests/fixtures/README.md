# Test Fixtures

This directory contains shared test resources used across multiple test modules.

## Structure

```
tests/fixtures/
├── audio/
│   └── zh.mp3       # Chinese speech audio for ASR testing
└── subtitle/
    └── sample_en.srt # English subtitle sample for subtitle processing tests
```

## Audio Files

### zh.mp3

- **Content**: Chinese speech saying "今天深圳天气怎么样" (What's the weather like in Shenzhen today?)
- **Duration**: ~2 seconds
- **Format**: MP3
- **Usage**: Used by ASR integration tests in `tests/test_asr/`
- **Access**: Via `test_audio_path` fixture in `tests/test_asr/conftest.py`

## Subtitle Files

### sample_en.srt

- **Content**: English tutorial about Python programming (10 segments)
- **Duration**: ~38 seconds
- **Format**: SRT (SubRip)
- **Usage**: Used by subtitle processing tests (split, optimize, translate)
- **Access**: Via fixtures in test modules

## Adding New Fixtures

When adding new shared test resources:

1. Create subdirectories by resource type (e.g., `audio/`, `video/`, `subtitle/`)
2. Use descriptive filenames indicating the content or purpose
3. Document the fixture in this README
4. Create appropriate fixtures in the relevant test module's `conftest.py`
5. Keep file sizes reasonable (commit only necessary test data)

## Guidelines

- **Keep it small**: Only commit minimal test data needed for tests
- **Reusable**: Place resources here if used by multiple test modules
- **Documented**: Update this README when adding new fixtures
- **Format**: Use common formats that don't require special codecs
