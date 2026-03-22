---
name: videocaptioner
description: Process video/audio files with AI — transcribe speech, optimize subtitles, translate to other languages, and burn subtitles into video. Use when the user asks to transcribe, caption, subtitle, or translate a video or audio file.
argument-hint: <command> [options] (e.g. "transcribe video.mp4", "subtitle input.srt --target-language ja")
allowed-tools: Bash(videocaptioner *, ls *, file *, cat *, head *)
---

# VideoCaptioner CLI

AI-powered video captioning tool. Install: `pip install videocaptioner`

## Available Commands

### Transcribe (speech → subtitles)
```bash
videocaptioner transcribe <file> [options]
```
- `--asr`: ASR engine — `faster-whisper` (local GPU, default) | `whisper-api` | `bijian` (free) | `jianying` (free) | `whisper-cpp`
- `--language CODE`: Source language as ISO 639-1 code, or `auto` (default)
- `-o PATH`: Output file path
- `--format`: Output format — `srt` (default) | `ass` | `txt` | `json`

### Subtitle (optimize / translate)
```bash
videocaptioner subtitle <file.srt> [options]
```
- `--translator`: Translation service — `llm` (default, needs API key) | `bing` (free) | `google` (free)
- `--target-language CODE`: BCP 47 code — `zh-Hans`, `en`, `ja`, `ko`, `fr`, `de`, `es`, etc.
- `--no-optimize`: Skip LLM optimization
- `--no-translate`: Skip translation
- `--reflect`: Enable reflective translation (slower, more accurate)
- `--prompt TEXT`: Custom prompt for optimization/translation
- `--layout`: `target-above` | `source-above` | `target-only` | `source-only`

### Synthesize (burn subtitles into video)
```bash
videocaptioner synthesize <video> -s <subtitle> [options]
```
- `--subtitle-mode`: `soft` (embedded track, default) | `hard` (burned in)
- `--quality`: `ultra` | `high` | `medium` (default) | `low`

### Full Pipeline
```bash
videocaptioner process <file> [options]
```
Runs: transcribe → optimize → translate → synthesize. Supports all options from individual commands.

### Download
```bash
videocaptioner download <url> [-o DIR]
```
Downloads video from YouTube, Bilibili, etc. via yt-dlp.

### Configuration
```bash
videocaptioner config show          # Show current config
videocaptioner config set KEY VAL   # Set a value (e.g. llm.api_key)
videocaptioner config path          # Show config file location
videocaptioner config init          # Interactive setup
```

Config priority: CLI args > environment variables (`VIDEOCAPTIONER_*`) > config file > defaults.

## Quick Examples

```bash
# Transcribe with free API (no config needed)
videocaptioner transcribe video.mp4 --asr bijian

# Translate to English with free Bing
videocaptioner subtitle input.srt --translator bing --target-language en

# Full pipeline with LLM optimization
videocaptioner process video.mp4 --target-language ja --api-key sk-xxx

# Quiet mode (outputs only the result file path)
videocaptioner transcribe video.mp4 --asr bijian -q
```

## Setup (if LLM features needed)

LLM API key is only required for `--translator llm`, subtitle optimization, and semantic splitting. Free alternatives (`--asr bijian`, `--translator bing`) work without any API key.

```bash
videocaptioner config set llm.api_key <your-key>
videocaptioner config set llm.api_base https://api.openai.com/v1
videocaptioner config set llm.model gpt-4o-mini
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Usage/config error (missing required config, invalid args) |
| 3 | Input file not found |
| 4 | Dependency missing (FFmpeg, yt-dlp) |
| 5 | Runtime error (API failure, processing error) |

## How to Use This Skill

Run `$ARGUMENTS` as a VideoCaptioner command. If the user's request is vague (e.g. "transcribe this video"), infer the appropriate command and options. Always:
1. Verify input files exist before running
2. Use `-v` for verbose output when debugging
3. Use `-q` when piping output to other commands
4. Check `videocaptioner config show` if API errors occur
5. Suggest `--asr bijian` and `--translator bing` as free alternatives when API key is not configured
