# ASR Integration Tests

This directory contains integration tests for various ASR (Automatic Speech Recognition) services.

## Test Structure

```
tests/
├── fixtures/
│   └── audio/
│       └── zh.mp3           # Shared test audio file (Chinese speech)
└── test_asr/
    ├── conftest.py              # Shared fixtures and utilities
    ├── test_whisper_api_asr.py  # WhisperAPI tests (OpenAI-compatible)
    ├── test_bcut_asr.py         # BcutASR tests (Bilibili public API)
    └── test_jianying_asr.py     # JianYingASR tests (CapCut public API)
```

## Environment Variables

### WhisperAPI Tests

Required environment variables:

- `OPENAI_BASE_URL`: OpenAI API base URL (e.g., `https://api.openai.com/v1`)
- `OPENAI_API_KEY`: OpenAI API key
- `OPENAI_MODEL`: (Optional) Model name, defaults to `whisper-1`

Example `.env`:

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL=whisper-1
```

### Public API Tests (Bcut, JianYing)

These tests use public APIs and do not require environment variables, but they:

- Have rate limits
- Are marked as `@pytest.mark.slow`
- Should be used sparingly

## Running Tests

### Run all ASR tests

```bash
pytest tests/test_asr/ -v
```

### Run specific test file

```bash
pytest tests/test_asr/test_whisper_api_asr.py -v
```

### Run with output

```bash
pytest tests/test_asr/ -s
```

### Skip slow tests (public APIs)

```bash
pytest tests/test_asr/ -v -m "not slow"
```

### Run only integration tests

```bash
pytest tests/test_asr/ -v -m integration
```

## Test Guidelines

### Test Structure

All tests follow this structure:

1. **Type Annotations**: All parameters and return types are annotated

   ```python
   def test_transcribe_audio(self, whisper_api: WhisperAPI) -> None:
   ```

2. **English Documentation**: All docstrings and comments in English

   ```python
   """Test basic audio transcription functionality.

   Args:
       whisper_api: WhisperAPI instance
   """
   ```

3. **Print Output**: Tests print results for manual verification

   ```python
   print("\n" + "=" * 60)
   print(f"WhisperAPI Transcription Results:")
   print(f"  Total segments: {len(result.segments)}")
   print("=" * 60)
   ```

4. **Validation**: Use shared validation functions
   ```python
   assert_asr_result_valid(result, min_segments=0)
   ```

### Fixtures

- `test_audio_path`: Path to tests/fixtures/audio/zh.mp3 (real Chinese speech audio file)
  - Contains actual speech content for meaningful ASR testing
  - Shared across all tests (session scope)
  - Located in shared fixtures directory for potential reuse by other test modules
- `whisper_api`, `bcut_asr`, `jianying_asr`: Configured ASR instances
- `expected_asr_keywords`: Common keywords for result validation

### Skipping Tests

Tests are skipped if required environment variables are not set:

```python
@pytest.fixture(autouse=True)
def skip_if_no_env(self) -> None:
    if not check_env_vars("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        pytest.skip("Environment variables not set")
```

## Platform-Specific Notes

### Windows-Only Tests

FasterWhisper tests are not included as they only work on Windows.
Tests will be skipped automatically on macOS/Linux.

### Public API Rate Limits

Bcut and JianYing tests use public APIs with rate limits:

- Marked with `@pytest.mark.slow`
- Use caching to minimize API calls
- Should not be run frequently in CI

## Adding New Tests

When adding tests for new ASR services:

1. Create a new test file: `test_<service_name>_asr.py`
2. Follow the existing test structure
3. Add type annotations for all parameters
4. Use English documentation
5. Add print statements for output verification
6. Use `check_env_vars()` if environment variables required
7. Mark as `@pytest.mark.slow` if using rate-limited API
8. Update this README with environment variable requirements

## Test Audio File

The `zh.mp3` file is located in `tests/fixtures/audio/` directory:

- Contains real Chinese speech: "今天深圳天气怎么样"
- Shared across all ASR tests via the `test_audio_path` fixture
- Can be reused by other test modules if needed
- Should remain in the repository for testing purposes
