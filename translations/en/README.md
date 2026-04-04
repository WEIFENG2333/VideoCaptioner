<div align="center">
  <img src="./docs/images/logo.png" alt="VideoCaptioner Logo" width="100">
  <h1>VideoCaptioner</h1>
  <p>A video subtitle processing tool based on large language models — a one-stop solution for speech recognition, subtitle optimization, translation, and video synthesis</p>

  [Online Documentation](https://weifeng2333.github.io/VideoCaptioner/) · [CLI Usage](#cli-usage) · [GUI Desktop Version](#gui-desktop-version) · [Claude Code Skill](#claude-code-skill)
</div>

## Installation

```bash
pip install videocaptioner          # Install CLI only (lightweight, no GUI dependencies)
pip install videocaptioner[gui]     # Install CLI + GUI desktop version
```

Free features (Bijiang speech recognition, Bing/Google translation) **require no configuration, ready to use after installation**.

## CLI Usage

```bash
# Speech transcription (free, no API Key required)
videocaptioner transcribe video.mp4 --asr bijian

# Subtitle translation (free Bing translation)
videocaptioner subtitle input.srt --translator bing --target-language en

# Full process: transcription → optimization → translation → synthesis
videocaptioner process video.mp4 --target-language ja

# Burn subtitles into video
videocaptioner synthesize video.mp4 -s subtitle.srt

# Download online videos
videocaptioner download "https://youtube.com/watch?v=xxx"
```

When LLM features (subtitle optimization, large model translation) are needed, configure API Key:

```bash
videocaptioner config set llm.api_key <your-key>
videocaptioner config set llm.api_base https://api.openai.com/v1
videocaptioner config set llm.model gpt-4o-mini
```

Configuration priority: `command line arguments > environment variables (VIDEOCAPTIONER_*) > configuration files > default values`. Run `videocaptioner config show` to view the current configuration.

<details>
<summary>All CLI Commands Overview</summary>

| Command | Description |
|---------|-------------|
| `transcribe` | Speech to subtitle. Engines: `faster-whisper`, `whisper-api`, `bijian` (free), `jianying` (free), `whisper-cpp` |
| `subtitle` | Subtitle optimization/translation. Translation services: `llm`, `bing` (free), `google` (free) |
| `synthesize` | Burn subtitles into video (soft subtitles/hard subtitles) |
| `process` | Full process handling |
| `download` | Download videos from platforms like YouTube and Bilibili |
| `config` | Configuration management (`show`, `set`, `get`, `path`, `init`) |

Run `videocaptioner <command> --help` to see full parameters. Complete CLI documentation available at [docs/cli.md](docs/cli.md).

</details>

## GUI Desktop Version

```bash
pip install videocaptioner[gui]
videocaptioner                      # Automatically opens desktop version with no parameters
```

<details>
<summary>Other Installation Methods: Windows Installer / macOS One-Click Script</summary>

**Windows**: Download the installer from [Release](https://github.com/WEIFENG2333/VideoCaptioner/releases)

**macOS**:
```bash
curl -fsSL https://raw.githubusercontent.com/WEIFENG2333/VideoCaptioner/master/scripts/run.sh | bash
```

</details>


<!-- <div align="center">
  <img src="https://h1.appinn.me/file/1731487405884_main.png" alt="Interface Preview" width="90%" style="border-radius: 5px;">
</div> -->

![Page Preview](https://h1.appinn.me/file/1731487410170_preview1.png)
![Page Preview](https://h1.appinn.me/file/1731487410832_preview2.png)

## LLM API Configuration

LLM is used only for subtitle optimization and large model translation; free functions (Bijiang recognition, Bing translation) require no configuration.

Supports all OpenAI-compatible service providers:

| Provider | Website |
|----------|---------|
| **VideoCaptioner Relay** | [api.videocaptioner.cn](https://api.videocaptioner.cn) — High concurrency, cost-effective, supports GPT/Claude/Gemini, etc. |
| SiliconCloud | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/i/HF95kaoz) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) |

Fill in the API Base URL and API Key in the software settings or CLI. [Detailed configuration tutorial](https://weifeng2333.github.io/VideoCaptioner/config/llm)

## Claude Code Skill

This project provides a [Claude Code Skill](https://code.claude.com/docs/en/skills.md), allowing the AI programming assistant to directly call VideoCaptioner to process videos.

Install to Claude Code:

```bash
mkdir -p ~/.claude/skills/videocaptioner
cp skills/SKILL.md ~/.claude/skills/videocaptioner/SKILL.md
```

Then enter `/videocaptioner transcribe video.mp4 --asr bijian` in Claude Code to use it.

## Working Principle

```
Audio/Video Input → Speech Recognition → Subtitle Segmentation → LLM Optimization → Translation → Video Synthesis
```

- Word-level timestamps + VAD speech activity detection, high accuracy
- LLM semantic understanding for segmentation, providing a natural and smooth subtitle reading experience
- Context-aware translation, supporting reflective optimization mechanisms
- High-efficiency bulk concurrent processing

## Development

```bash
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
cd VideoCaptioner
uv sync && uv run videocaptioner     # Run GUI
uv run videocaptioner --help          # Run CLI
uv run pyright                        # Type checking
uv run pytest tests/test_cli/ -q      # Run tests
```

## License

[GPL-3.0](LICENSE)

[![Star History Chart](https://api.star-history.com/svg?repos=WEIFENG2333/VideoCaptioner&type=Date)](https://star-history.com/#WEIFENG2333/VideoCaptioner&Date)