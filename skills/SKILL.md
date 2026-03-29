---
name: videocaptioner
description: Process video subtitles — transcribe speech, optimize/translate text, burn styled subtitles into video. Use when you need to add subtitles to a video, transcribe audio, translate subtitles, or customize subtitle styles.
allowed-tools: Bash(videocaptioner *, ffprobe *, ffmpeg -ss *)
---

# VideoCaptioner CLI

AI-powered video captioning: transcribe speech → optimize subtitles → translate → burn into video with beautiful styles.

## When to use

- User wants to **add subtitles to a video**
- User wants to **transcribe audio/video** to text
- User wants to **translate subtitles** to another language
- User wants to **customize subtitle appearance** (colors, fonts, rounded backgrounds)
- User wants to **download and subtitle online videos**

## Before you start

**Always run `videocaptioner <command> --help` first** to check the latest options and defaults before executing a command. The examples below are common patterns, but --help is the source of truth.

- Install: `pip install videocaptioner`
- FFmpeg required for video synthesis (`brew install ffmpeg` on macOS)
- **Free (no API key):** transcription (bijian/jianying), translation (Bing/Google)
- **Requires LLM API key:** subtitle optimization, subtitle re-segmentation, LLM translation. Set via `OPENAI_API_KEY` env var or `--api-key` flag

## Common scenarios

### 1. Give a Chinese video English subtitles (one command, all free)

```bash
videocaptioner process video.mp4 --asr bijian --translator bing --target-language en \
  --subtitle-mode hard --quality high -o output.mp4
```

### 2. Transcribe a video to SRT (free)

```bash
videocaptioner transcribe video.mp4 --asr bijian -o output.srt

# Output as JSON format to a directory
videocaptioner transcribe video.mp4 --asr bijian --format json -o ./subtitles/
```

### 3. Translate existing subtitles

```bash
# Free Bing → English, bilingual output with translation above original
videocaptioner subtitle input.srt --translator bing --target-language en --layout target-above -o translated.srt

# Free Google → Japanese, translation only (discard original text)
videocaptioner subtitle input.srt --translator google --target-language ja --no-optimize --layout target-only -o output_ja.srt

# High quality LLM translation with reflective mode
videocaptioner subtitle input.srt --translator llm --target-language en --reflect \
  --api-key $OPENAI_API_KEY -o output_en.srt
```

### 4. Full pipeline with beautiful styled subtitles

```bash
# Anime-style subtitles (warm color + orange outline), high quality video
videocaptioner process video.mp4 --asr bijian --translator bing --target-language ja \
  --subtitle-mode hard --style anime --quality high -o output_ja.mp4

# Modern rounded background subtitles
videocaptioner process video.mp4 --asr bijian --translator google --target-language ko \
  --subtitle-mode hard --render-mode rounded -o output_ko.mp4

# Custom colors: white text with red outline, ultra quality
videocaptioner process video.mp4 --asr bijian --translator bing --target-language en \
  --subtitle-mode hard --quality ultra \
  --style-override '{"outline_color": "#ff0000", "primary_color": "#ffffff"}' -o output_en.mp4
```

### 5. Subtitle only, output as ASS format (no video synthesis)

```bash
videocaptioner process video.mp4 --asr bijian --translator bing --target-language en \
  --format ass --no-synthesize -o ./output/
```

### 6. Step-by-step control (transcribe → translate → synthesize separately)

```bash
# Step 1: Transcribe
videocaptioner transcribe video.mp4 --asr bijian -o video.srt

# Step 2: Translate (bilingual, original text above translation)
videocaptioner subtitle video.srt --translator bing --target-language en --layout source-above -o video_en.srt

# Step 3: Burn into video with rounded background, high quality
videocaptioner synthesize video.mp4 -s video_en.srt --subtitle-mode hard \
  --render-mode rounded --quality high -o video_with_subs.mp4
```

### 7. Process audio file (auto-skips video synthesis)

```bash
videocaptioner process podcast.mp3 --asr bijian --translator bing --target-language en -o ./output/
```

### 8. Transcribe other languages (whisper-api)

```bash
videocaptioner transcribe french_video.mp4 --asr whisper-api \
  --whisper-api-key $OPENAI_API_KEY --language fr -o french.srt
```

### 9. Only optimize subtitles with LLM (fix ASR errors, no translation)

```bash
videocaptioner subtitle raw_subtitle.srt --no-translate --api-key $OPENAI_API_KEY -o optimized.srt
```

### 10. Custom rounded background style with custom font

```bash
videocaptioner synthesize video.mp4 -s subtitle.srt --subtitle-mode hard \
  --style-override '{"text_color": "#ffffff", "bg_color": "#000000cc", "corner_radius": 10, "font_size": 36}' \
  --font-file ./NotoSansSC.ttf --quality high -o styled_video.mp4
```

## Command reference

| Command | Purpose |
|---------|---------|
| `transcribe` | Speech → subtitles. Engines: `bijian`(free) `jianying`(free) `whisper-api` `whisper-cpp` |
| `subtitle` | Optimize (LLM) and/or translate (LLM/Bing/Google) subtitle files |
| `synthesize` | Burn subtitles into video with customizable styles |
| `process` | Full pipeline: transcribe → optimize → translate → synthesize |
| `download` | Download video from YouTube, Bilibili, etc. |
| `config` | Manage settings (`show` `set` `get` `path` `init`) |
| `style` | List all subtitle style presets with parameters |

Run `videocaptioner <command> --help` for full options.

## Subtitle styles

Two rendering modes for beautiful subtitles:

**ASS mode** (default) — outline/shadow style:
- Presets: `default` (white+black outline), `anime` (warm+orange outline), `vertical` (portrait videos)
- Customizable fields: `font_name`, `font_size`, `primary_color`, `outline_color`, `outline_width`, `bold`, `spacing`, `margin_bottom`

**Rounded mode** — modern rounded background boxes:
- Preset: `rounded` (dark text on semi-transparent background)
- Customizable fields: `font_name`, `font_size`, `text_color`, `bg_color` (#rrggbbaa), `corner_radius`, `padding_h`, `padding_v`, `margin_bottom`

Style options only work with `--subtitle-mode hard`.

## Target languages

BCP 47 codes: `zh-Hans` `zh-Hant` `en` `ja` `ko` `fr` `de` `es` `ru` `pt` `it` `ar` `th` `vi` `id` and 23 more.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_BASE_URL` | LLM API base URL |

## Exit codes

`0` success · `2` bad arguments · `3` file not found · `4` missing dependency · `5` runtime error

## Tips

- Use `-q` for scripting (stdout = result path only)
- Bing/Google translation is free, no API key needed
- `bijian`/`jianying` ASR is free but only supports Chinese & English
- Run `videocaptioner style` to see all style presets
