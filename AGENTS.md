# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

VideoCaptioner (卡卡字幕助手) is a PyQt5 desktop application for AI-powered video subtitle processing. See `README.md` for full details.

### Services

| Service | How to run | Notes |
|---|---|---|
| Main App (PyQt5 GUI) | `DISPLAY=:99 uv run python main.py` | Requires Xvfb running on `:99` |
| Docs (VitePress) | `npm run docs:dev` (in `docs/`) | Optional |

### Running the app headless

The app requires a display server. Start Xvfb before launching:

```bash
Xvfb :99 -screen 0 1280x1024x24 &
export DISPLAY=:99
```

Required system packages for Qt xcb plugin: `libxcb-xinerama0 libxcb-cursor0 libxcb-keysyms1 libxcb-image0 libxcb-icccm4 libxcb-render-util0 libxkbcommon-x11-0`.

### Dev commands

Standard commands are in `README.md` under "开发者指南":

- **Install deps**: `uv sync`
- **Run app**: `uv run python main.py`
- **Lint**: `uv run ruff check .`
- **Type check**: `uv run pyright`
- **Tests**: `QT_QPA_PLATFORM=offscreen uv run pytest tests/`

### Gotchas

- Tests need `QT_QPA_PLATFORM=offscreen` to avoid needing a display.
- Some tests require external API keys (see `tests/.env.example`); they are skipped when env vars are absent.
- `tests/test_subtitle/` tests require fixture files that may be missing; expect errors from those.
- `tests/test_asr/test_chunking.py` has pre-existing failures (outdated API usage).
- `tests/test_asr/test_jianying_asr.py` requires external network access to a signing server.
