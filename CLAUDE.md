# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

VideoCaptioner is an AI-powered video captioning tool: ASR (speech recognition) → subtitle optimization (LLM) → translation → styled subtitle video synthesis. It ships as both a CLI (`videocaptioner`) and a PyQt5 desktop GUI. The CLI is the primary interface; when invoked with no arguments, it falls back to GUI mode if `[gui]` extras are installed.

## Commands

```bash
# Dev environment
uv sync                                    # install all deps
uv run videocaptioner                      # run GUI (or CLI help if GUI missing)
uv run videocaptioner --help               # CLI help

# Build
uv build                                   # sdist + wheel via hatchling

# Lint & type-check
uv run ruff check videocaptioner/          # lint (E/F/I/W, line-length 100, py310+)
bash scripts/lint.sh                       # ruff auto-fix + sort imports + stats
uv run pyright videocaptioner/cli/         # type checking (basic mode, py3.12)

# Tests
uv run pytest                              # all tests
uv run pytest tests/test_cli/ -q           # CLI unit tests only
uv run pytest tests/test_translate/ -v     # specific module
uv run pytest -m "not integration" -v      # skip integration tests
uv run pytest -m translator -v             # run translator-marked tests
```

Pytest is configured with `-v --strict-markers --tb=short --disable-warnings` defaults. Available markers: `integration`, `slow`, `llm`, `translator`.

## Architecture

### Data flow
```
Video/Audio → ASR → ASRData → Segmentation → LLM Optimization → Translation → Subtitle File → Video Synthesis
```

### Package layout

| Package | Role |
|---|---|
| `videocaptioner/cli/` | Entry point (`main.py`), argparse config, subcommand runners (`commands/`), validators, exit codes |
| `videocaptioner/cli/config.py` | Layered config: CLI args > env vars > `~/.config/videocaptioner/config.toml` > defaults |
| `videocaptioner/core/entities.py` | `@dataclass` task types (`TranscribeTask`, `SubtitleTask`, `SynthesisTask`, `FullProcessTask`) and config/enum definitions |
| `videocaptioner/core/asr/` | ASR engines: BcutASR, JianYingASR (free, zh/en only), FasterWhisper, WhisperCpp, WhisperAPI |
| `videocaptioner/core/llm/` | OpenAI-compatible LLM client, request logging, context builder |
| `videocaptioner/core/translate/` | Translators: LLM, Bing (free), Google (free), DeepLX |
| `videocaptioner/core/subtitle/` | ASS renderer, rounded-background renderer (Pillow), style management |
| `videocaptioner/core/split/` | Subtitle segmentation (with/without LLM) |
| `videocaptioner/core/optimize/` | LLM-based subtitle optimization (fix ASR errors) |
| `videocaptioner/core/prompts/` | LLM prompt templates as `.md` files with `string.Template` substitution |
| `videocaptioner/core/utils/` | Cache (diskcache), logger, platform helpers, subprocess runner |
| `videocaptioner/ui/` | PyQt5 + QFluentWidgets MVC: views, components, thread workers, signal bus |
| `resource/` | Bundled fonts (2 TTF), style presets (4 JSON), QSS, translations (`.ts`/`.qm`) |
| `tests/` | Pytest suite with shared fixtures in `conftest.py` |

### Config system

Three-layer merge (highest to lowest priority):
1. CLI arguments → override dict
2. Environment variables (`VIDEOCAPTIONER_*`, `OPENAI_*`)
3. User TOML file (`~/.config/videocaptioner/config.toml`)
4. Built-in defaults

Config values are read/written via `videocaptioner/cli/config.py`. The merge is recursive with `_deep_merge`. Sensitive keys (api_key) are masked on display.

### Prompt system

LLM prompts live as Markdown files in `videocaptioner/core/prompts/` organized by function: `split/`, `optimize/`, `translate/`, `analysis/`. Loaded via `get_prompt(path, **kwargs)` with LRU caching and `string.Template` variable substitution (`$variable`). Always read the prompt file before modifying LLM behavior — the templates are the source of truth.

### ASR data model

`ASRData` holds a list of `ASRDataSeg` objects (start_time, end_time, text). All ASR engines normalize to this format. `SubtitleProcessData` wraps it with index, translated_text, and status fields for downstream processing.

### Task system (GUI/threads)

Tasks are typed `@dataclass` objects: `TranscribeTask`, `SubtitleTask`, `SynthesisTask`, `TranscriptAndSubtitleTask`, `FullProcessTask`. Each has a task_id, timestamps, file paths, and typed config. The `TaskFactory` in the UI layer creates them; thread workers execute them on background QThreads.

## Key conventions

- **Python**: 3.10–3.12 (not 3.13+)
- **Line length**: 100 (ruff)
- **Lint rules**: E, F, I, W (no E501)
- **Type checking**: pyright basic mode, only `videocaptioner/` is checked; `videocaptioner/ui/` is excluded
- **Cache disabled during tests**: `conftest.py` calls `cache.disable_cache()` globally
- **Versioning**: git tags → hatch-vcs → `videocaptioner/_version.py`; tagged commits must start with `v`
- **CI quality gate** (on publish): ruff check + pyright (cli only) + pytest CLI tests

## Test fixtures (conftest.py)

- `sample_asr_data` — 3-segment `ASRData` with English text
- `sample_translate_data` — 3-item `List[SubtitleProcessData]`
- `target_language` — `TargetLanguage.SIMPLIFIED_CHINESE`
- `check_env_vars` — callable that skips test if env vars are missing
- `expected_translations` — keyword dict for translation quality assertions
- `assert_translation_quality()` — helper to validate translation contains expected keywords
