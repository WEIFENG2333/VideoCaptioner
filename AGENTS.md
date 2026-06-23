# VideoCaptioner Agent Guide

This file is the entry point for Codex/Claude-style agents working in this
repository. `CLAUDE.md` is intentionally a symlink to this file so the project
has one source of truth.

## Product

VideoCaptioner is a desktop and CLI app for video subtitle workflows:

```text
video/audio input
  -> ASR transcription
  -> subtitle splitting / LLM polish / translation
  -> optional dubbing
  -> soft subtitle, hard subtitle, or dubbed final video
```

The app has two product surfaces:

- CLI: `videocaptioner transcribe|subtitle|synthesize|dub|process|download|`
  `models|doctor|style|config|gui`
- GUI: PyQt5 desktop app launched by `uv run videocaptioner`,
  `.venv/bin/python -m videocaptioner`, or `videocaptioner gui`

The UX is Chinese-first in the current desktop app. Many provider names and
settings labels are user-facing Chinese strings; keep them natural and concise.

## Current Architecture

Keep these boundaries strict:

```text
videocaptioner/core/        business logic, no PyQt dependency
videocaptioner/core/application/
  config_store.py           shared TOML persistence and defaults
  app_config.py             plain dataclass settings consumed by business flows
  task_builder.py           builds workflow task configs from AppConfig
videocaptioner/cli/         argparse commands, no UI imports
videocaptioner/cli/config_adapter.py
                            TOML/CLI dict -> AppConfig
videocaptioner/ui/          PyQt desktop app, may import core
videocaptioner/ui/config_adapter.py
                            UI state -> AppConfig
videocaptioner/ui/common/config.py
                            in-memory UI settings over the shared TOML store
videocaptioner/ui/common/settings_state.py
                            first-party SettingField state, not qfluent QConfig
videocaptioner/ui/thread/   QThread wrappers around long-running core tasks
videocaptioner/ui/view/     pages
videocaptioner/ui/components/
                            reusable first-party widgets
```

`core` must not import `ui`. `cli` must not import `ui`. GUI pages should not
construct business config directly from widgets; use `ui.config_adapter` /
`TaskFactory` / `TaskBuilder`.

## Shared Configuration

The current source of truth is TOML:

- Store: `videocaptioner.core.application.config_store`
- Default path: `platformdirs.user_config_dir("videocaptioner") / "config.toml"`
- Test override: `VIDEOCAPTIONER_CONFIG_FILE=/tmp/some-config.toml`
- Priority: CLI flags > environment variables > TOML file > defaults

Important sections:

- `[ui]`: theme, language, preview-only UI state
- `[llm]` and `[llm.providers.*]`: LLM provider settings and cached model options
- `[whisper_api]`, `[fun_asr]`: ASR provider settings
- `[transcribe]`: ASR workflow defaults
- `[subtitle]`, `[translate]`: split/polish/translate workflow defaults
- `[synthesize]`: video/subtitle synthesis defaults
- `[dubbing]`: TTS/dubbing defaults and clone reference state

Secrets must be stripped before saving or sending. API-key newline bugs have
caused invalid request headers such as `Bearer ...\n`; do not bypass the strip
paths in `SettingField`, `config_store`, `TTSConfig`, `SpeechProviderConfig`,
or the CLI/UI adapters.

The settings page taxonomy accepted by the user is:

- 转录配置
- LLM 配置
- 翻译服务
- 翻译与优化
- 字幕合成配置
- 配音配置
- 保存配置
- 个性化
- 关于

Provider-specific fields should only appear when that provider needs them. For
example: Edge dubbing hides key rows; SiliconFlow/Gemini show TTS key/model
rows; Whisper API and Fun-ASR show their own base/key/model fields.

The transcribe settings page has one unified "测试转录" row for ALL ASR
providers (B 接口 / J 接口 / Fun-ASR / Whisper API / whisper-cpp /
faster-whisper). It runs a real short-audio transcription through
`core/asr/check.py::check_transcribe` with `use_cache=False`, the same entry
`doctor --check-api` uses for `api.transcribe`. Do not reintroduce
per-provider "测试连接" buttons or lightweight auth-only probes.

## Output Naming And Task Workspace

`videocaptioner/core/application/output_paths.py` is the single source of
truth for output file naming and task directories. CLI and GUI share one
grammar; never hand-write output filename templates at call sites:

```text
{stem}.{tag}.{ext}        tags: <language code> | optimized | subtitled | dubbed
```

- Tags name the artifact role and compose in processing order
  (`video.dubbed.subtitled.mp4`). Parameters (soft/hard subtitle, provider,
  voice, timing) never go into filenames.
- Products land next to the source file. GUI paths go through
  `unique_path()` (auto-increment `" (2)"`); CLI default paths overwrite
  deterministically for scriptability.
- All intermediates live in a per-run task directory grouped by function:
  `{work_dir}/{task_type}/{YYYYMMDD-HHMMSS}-{stem}/` (task_type =
  `transcribe`/`synthesis`/`batch`/`dubbing`; pass it to `new_task_dir`) with
  fixed names (`transcript.srt`, `subtitle.ass`, `dubbing/…`). The flow owner
  (home pipeline tail, batch `JobRunner`, synthesis page controller) deletes the
  directory on success unless `app.keep_intermediates` is on; failures keep
  it for debugging; cancels always clean it. `cleanup_task_dir` only removes a
  dir whose parent name is a known task_type (never rmtrees into user dirs).
- Raw TTS segments are a content-addressed global cache in
  `CACHE_PATH/tts_segments` keyed by text + every synthesis-affecting config
  field (see `DubbingPipeline._segment_hash`). Adding a config field that
  changes audible output requires extending that hash.
- Paths flow through task dataclass fields (`task_dir`, explicit
  subtitle/video paths). Do not rediscover files by name patterns or glob;
  the legacy `【原始字幕】/【卡卡】` bracket-prefix scheme is removed and must
  not come back.
- The grammar is pinned by `tests/test_application/test_output_paths.py`;
  changing naming starts there.

## UI Direction

The current migration direction is first-party UI components with qfluentwidgets
only as a low-level widget/icon source while the shell is being migrated.

Do:

- Use `videocaptioner.ui.common.theme_tokens.app_palette()` for colors.
- Use `videocaptioner.ui.common.app_icons` for app-owned SVG icons.
- Put SVGs in `resource/assets/icons/`.
- Prefer reusable widgets in:
  - `ui/components/workbench.py` (design-language atoms: buttons, pills,
    drop zones, panels; use these first)
  - `ui/components/app_dialog.py` (`AppDialog` shell + `ConfirmDialog`; every
    in-app dialog must use these instead of qfluent `MessageBox`/
    `MessageBoxBase`. The shell promotes `parent` to `parent.window()` so
    dialogs always center on the whole program window, never a tab page.)
  - `ui/components/form_cards.py`
  - `ui/components/settings_controls.py`
  - `ui/components/subtitle_style_controls.py`
- Keep manual stylesheet inside reusable components or page-specific media
  preview areas. Avoid scattering large anonymous styles across pages.
- Keep page layouts stable at compact widths; button clicks must not resize
  columns or create large blank bands.

Do not:

- Reintroduce qfluentwidgets native setting-card/config binding.
- Recreate deleted legacy files such as `MySettingCard.py`,
  `app_setting_cards.py`, `WhisperAPISettingWidget.py`, or
  `TranscriptionOutputDialog.py`.
- Use raw unicode arrows for production icons; use `app_icons` or FluentIcon.
- Add explanatory cards just to fill space. This project prefers compact,
  task-oriented pages.

Design mocks live in `docs/dev/design-*.html` (roughly one per page) as a
development-time visual reference; superseded variants are archived under
`design-archive/`. **Do NOT reference these HTML paths or their CSS class names
from code comments / docstrings** — the mocks change and get deleted, so the
references rot into dead links. A comment should describe what the widget IS, not
which mock it came from. Use the mocks while building, then drop the reference.
Take reference screenshots with
`scripts/design_reference_shots.py <html> <out-dir> [selector]`.

For visual work, follow this rhythm:

1. Inspect the current PyQt page and the relevant HTML demo.
2. Make the smallest coherent component/page changes.
3. Run offscreen UI smoke screenshots in dark and light themes.
4. Open the contact sheets and inspect alignment, spacing, text overflow,
   button centering, blank areas, and theme contrast.
5. Only then call the visual work done.

UI smoke commands:

```bash
# Full smoke: screenshots + behavior assertions + compact-window checks.
.venv/bin/python scripts/ui_smoke_check.py /tmp/vc-ui-check-dark --theme dark
.venv/bin/python scripts/ui_smoke_check.py /tmp/vc-ui-check-light --theme light

# Fast iteration: screenshots only, no assertions (seconds per page).
# --pages implies shots-only; settings subpages are setting-<key>.
.venv/bin/python scripts/ui_smoke_check.py --pages dubbing,setting-dubbing
.venv/bin/python scripts/ui_smoke_check.py --shots-only --theme both
.venv/bin/python scripts/ui_smoke_check.py --list
```

The full mode exercises page construction, settings navigation, provider
switching, dubbing clone UI, video synthesis mode changes, subtitle-style
fullscreen state, and compact-window states. Both modes write contact sheets
and print one `shot=<path>` line per screenshot. Pages are registered in
`PAGE_REGISTRY` inside the script; add new pages there.

## Dubbing And Provider Rules

Dubbing providers currently include Edge, Gemini TTS, and SiliconFlow CosyVoice.

- Edge is the no-key baseline, but still needs network access for real TTS.
- Gemini and SiliconFlow require a TTS API key before preview/generation.
- SiliconFlow CosyVoice is the provider that exposes voice-clone controls:
  upload audio, record, clear, `clone_audio`, and `clone_text`.
- Edge and Gemini should not show unsupported clone controls.
- If Gemini/SiliconFlow preview fails while Edge works, first check provider key
  state; do not diagnose it as a generic audio playback bug.
- If preview errors mention `Invalid header value` or `Bearer ...\n`, inspect
  shared config sanitation across `task_factory.py`, `core/entities.py`,
  `core/speech/models.py`, `core/tts/tts_data.py`, and adapters.

Provider switching has historically caused stale base URL/model/voice state.
Verify switching in the real app and in `scripts/ui_smoke_check.py`; do not
patch only one page.

## Live Caption (实时字幕)

Real-time speech transcription + translation shown in a draggable desktop
overlay (the "实时字幕" nav page). Backend-agnostic by design: three transcription
backends ship today (voxgate / fun-asr / qwen-asr); adding another only means
implementing the `LiveTranscriber` interface.

```text
core/realtime/            business logic, NO PyQt. Grouped into subpackages by role;
                          top level keeps only protocol + orchestration + wiring.
  events.py        TranscriptSegment / CaptionEntry  ← our own protocol (leaf, no deps)
  config.py        LiveCaptionConfig / LiveCaptionSource
  caption.py       CaptionAssembler: upsert by seg_id + dual-color + async translate
                   (segmentation is the BACKEND's job, not here)
  factory.py       config → backend / translate_fn (conditionally imports the chosen
                   backend so unused backends don't pull websocket into startup)
  session.py       orchestrates audio+backend+assembler+recorder (start/pump/stop)
  check.py         diagnostics: real short transcription through a backend
  backends/        transcription backends (import the specific submodule you need; the
                   package __init__ does NOT re-export, to keep backends lazy)
    base.py        LiveTranscriber ABC + audio contract consts (SAMPLE_RATE/CHANNELS/
                   SAMPLE_WIDTH) + On* callback types + TranscriberState/LiveCaptionError +
                   shared `_reconnect_with_backoff` (exp backoff + log throttle + give-up
                   cap) reused by the WS backends
    voxgate.py     `voxgate transcribe -` subprocess (stdio: stdin PCM16 → stdout
                   `-f protocol` raw Doubao frames); own per-sentence seg_id (not raw `index`); also
                   holds find_voxgate_binary. No server/WS. Doubao is a zh/en BILINGUAL
                   model; `-l` is a hint not a limit, `auto` → factory passes `zh`
                   (still recognizes English). Only zh/en + auto.
    fun_asr.py     Alibaba DashScope realtime WS client; per-`sentence_id` seg_id; VAD
                   segmentation (semantic off); reconnects on drop AND mid-session
                   task-finished. `_language_hints` uses languages.FUN_ASR_MTL_LANGS /
                   FUN_ASR_REALTIME_LANGS (model-aware). mtl model = zh/yue/en/ja/th/vi/id
                   (NOT Spanish etc.); realtime model = zh/en/ja.
    qwen_asr.py    DashScope `qwen3-asr-flash-realtime` WS (OpenAI-realtime style:
                   session.update/input_audio_buffer.append; transcription in `.text`
                   event's `stash` (text empty), final in `.completed.transcript`);
                   per-`item_id` seg_id; 27 languages incl Spanish; `auto` omits language
                   → server auto-detects. Reconnect治理 shared with fun-asr via base
                   `_reconnect_with_backoff`; frequent "Connection lost" is the network,
                   not a code bug (real-API soak: idle 130s / busy 117s both 0 drops).
    languages.py   SINGLE SOURCE OF TRUTH for which source languages each provider
                   supports (codes only, no Qt/labels): voxgate=zh/en, fun-asr=mtl 7,
                   qwen-asr=27; all 3 include "auto" (always first). UI labels (中文) live
                   in ui/common/config.py `source_language_options(provider)`; backends +
                   the source-language validator import from here. Don't redefine lang sets.
  audio/           capture sources, all → 16k/mono/s16le, drop-in start()/read()/stop()
    capture.py     sounddevice/PortAudio input device (mic/loopback) + device enumeration.
                   `_sd()` lazy-imports sounddevice (loads PortAudio) — KEEP lazy: it both
                   defers PortAudio load and gracefully degrades if PortAudio is missing
                   (realtime is imported at startup via main_window).
    system_mac.py  macOS native system audio (ScreenCaptureKit subprocess), no BlackHole
  recording/       session recording + history persistence
    history.py     LiveCaptionStore + LiveCaptionRecord/CaptionSegment (persist/list/
                   search/delete/export SRT,TXT); records live in {work_dir}/live-caption/
                   (a user work product, not app data); migrate_legacy_root moves the old
                   APPDATA/live_captions once on GUI startup (from main.py, NOT widget ctor)
    recorder.py    SessionRecorder: tee PCM→WAV + collect paragraphs → LiveCaptionRecord
    debug_tap.py   optional debug dump (raw events + fed PCM + assembler output;
                   enabled by `VC_DEBUG=live`, the project-wide debug switch in
                   core/utils/debug.py)
ui/thread/live_caption_thread.py   WorkerThread shell; Qt signals (caption/level/state/
                   error/recorded) + checkpoint cancel
ui/components/caption_overlay.py   frameless translucent always-on-top overlay
ui/components/caption_overlay_settings.py  in-overlay settings popover
ui/components/live_caption/        in-app page widgets (app_palette, reuse workbench):
  transcript.py    TranscriptEntry/TranscriptList (timeline bubbles, live + detail)
  player.py        AudioPlayerBar (QMediaPlayer: seek, per-sentence marks, click-to-jump)
  views.py         SessionView (ready/live/paused/ended/error) / HistoryView / DetailView
ui/view/live_caption_interface.py  QStackedWidget host of the 3 views + thread/overlay/
                   recording lifecycle; never builds business config from widgets directly
```

Protocol rules:

- Our protocol is `TranscriptSegment(seg_id, text, is_final, start_time, end_time)`
  → `CaptionEntry(seg_id, seq, source_text, source_stable_len, target_text,
  is_final, started_at, start_time, end_time)`. UI upserts captions by `seg_id`.
  The active paragraph and the history paragraph it settles into share one
  `seg_id` — finalization is a state flip, not a new row. `text` is ONE cumulative
  growing full text for that sentence (rewritten, not just appended).
- **Segmentation is the BACKEND's job, NOT the assembler's.** Each backend assigns
  a stable per-sentence `seg_id` and flips `is_final` on its own sentence-boundary
  signal. The `CaptionAssembler` only upserts by `seg_id`, computes dual-color, runs
  async translate, and guards finalized segments. There is no pause/over-length
  splitting in the assembler anymore (`_PARAGRAPH_PAUSE_S`/`_para_cut` removed).
- Audio contract is 16 kHz / mono / s16le PCM, fed in arbitrary chunks. Backends
  re-frame internally; do not pre-chunk to 20 ms in the client.
- Dual-color uses longest-common-prefix (`source_stable_len`) because backends
  rewrite interim text, not just append: the common prefix is stable (bright), the
  tail is "floaty" (dim); on `is_final` the whole line goes stable.
- voxgate runs `voxgate transcribe - --input-format pcm16 --stream -f protocol -l
  <lang>` as a subprocess (raw Doubao send/recv frames, one JSON per line; full
  research in `docs/dev/voxgate-protocol.md`). Each `result_json.results[]` item
  carries `index` (the sentence number), a cumulative full `text`, and sentence
  `start/end_time`. **DO NOT use `index` directly as the seg_id.** Short/paused
  audio increments `index` and emits `is_vad_finished` per sentence — but
  **continuous speech (watching video / meetings, no clear pauses) keeps the same
  `index` for the whole session, never fires VAD, and at the ~118-char per-sentence
  cap "rolling-resets" `text` (sudden shrink, prefix fully replaced)**. Keying on
  `index` alone overwrites the whole session down to the last fragment (real
  evidence: a 118s video session stored only 1 sentence). So `_consume_results`
  keeps its own global sentence counter `_sentence_no` and treats **`index` change
  OR a rolling reset (`_is_reset`)** as a sentence boundary — finalize the in-flight
  segment there, start a new one. `_is_reset(old,new)` is length-halving ONLY:
  `bool(old) and len(new)*2 < len(old)` (e.g. 211→15, 118→1). NEVER add a
  "common-prefix shrank" rule — twopass rewrites (whose fault→who spots, punctuation
  edits) shorten by a char or two with a changed prefix and that rule splits one
  growing sentence into repeated prefixes (the real cause of the "English opening 3
  duplicate lines"; those were all vad=0 growth frames, not VAD-triggered).
  **Finalize on `is_vad_finished` (real pause); `is_force_finished` is a twopass
  mid-sentence flush — the same `index` keeps growing after it, never finalize on
  it.** Skip the trailing empty `text:""` placeholder. `stop()` closes stdin (EOF)
  and keeps the receive thread alive until voxgate flushes and exits — killing first
  truncates the last sentence. No server, no port, no WS. (The old `-f ndjson` /
  `snapshot` / `stream_asr_finish` / cover-count model is gone.)
- fun-asr keys each sentence by `funasr#{sentence_id}` and finalizes the previous
  sentence when the next `sentence_id` appears (`sentence_end` is unreliable).

Hard rules:

- `core/realtime` must not import PyQt; widgets only touch the overlay from the
  GUI thread. The transcribe/translate callbacks fire on the backend receive
  thread and translation executor — they reach the overlay ONLY through
  `LiveCaptionThread`'s Qt signals (queued to the GUI thread). Calling
  `overlay.upsert_caption` off-thread aborts with "Cannot create children for a
  parent in a different thread".
- The overlay is its own fixed dark-glass visual world — it uses the design
  tokens in `caption_overlay.py`, NOT `app_palette()`, and does not recolor with
  the app theme. Its translucency intentionally bleeds the video behind it; do
  not "fix" the neutral card color to look bluer (that tint is the wallpaper
  showing through in design screenshots).
- Ship a `voxgate` binary per platform (CGO build; the repo's are arm64 macOS
  only and gitignored). `VoxgateBackend` spawns it directly as a `voxgate
  transcribe` subprocess (no `voxgate serve`); users override the path in
  设置 → 实时字幕配置. Binary discovery is `find_voxgate_binary` in
  `backends/voxgate.py` (configured path → bundled bin → user bin → PATH).
- Translation reuses `TranslatorFactory` (default Bing: no key, low latency).
  Per-sentence finalize translates once; the active sentence translates on a
  debounce. Do not add a separate live-translation backend.
- `LiveCaptionInterface` MUST be in `main_window.closeEvent`'s shutdown tuple and
  stop its thread + overlay on close, or exit aborts on a running QThread. Before
  deleting the overlay, disconnect BOTH `thread.caption` (→ host `_on_caption`) and
  `thread.level` (→ `overlay.set_level`); a queued signal to a freed overlay aborts.
- Every session auto-records: `SessionRecorder` tees PCM to `audio.wav` and collects
  finalized paragraphs into a `LiveCaptionRecord` saved under
  `{work_dir}/live-caption/{YYYYMMDD-HHMMSS}/transcript.json`. One `LiveCaptionStore`
  (rooted at the configured work_dir) is built by the interface and passed through the
  thread into the session, so recording-writes and history-reads share one root.
  Empty sessions are
  discarded. Segment `start` = paragraph `started_at − session_start` (aligns with the
  continuously-recorded WAV). The detail page plays that WAV with per-sentence marks;
  clicking a sentence/mark seeks. Don't invent a new on-disk layout — go through
  `LiveCaptionStore`.
- The in-app page (`ui/components/live_caption/`) is the normal app visual world
  (`app_palette()`, reuse `workbench`); only the floating `caption_overlay` is the
  separate dark-glass world. Pixel-anchor the 3 views to
  `docs/dev/design-live-caption-proposals.html` (render with Chrome via
  `/opt/homebrew/bin/python3.11` + playwright; capture each `data-mode`).

The overlay has two states — standard (compact current line, for overlaying video)
and tall (full timeline) — plus the in-overlay settings popover and a paused state;
WIDE / DOCK / COMPACT were removed. Verify overlay edits by rendering the card
offscreen and diffing against `scripts/design_reference_shots.py`-style shots.

## Online Download And Diagnostics

The yt-dlp download engine lives in `core/download/media.py`
(`MediaDownloader`, no Qt) and is shared by the GUI thread
(`ui/thread/media_download_thread.py`, a thin signal shell), the CLI
`download` command, and the diagnostics source check
(`core/download/source_check.py`). Network environment helpers (proxy
routing, cookies, bilibili buvid, browser-cookie fallback ladder, friendly
errors) live in `core/download/net.py`. Keep all three callers on the shared
engine so "diagnostics says OK" always matches real download behavior:

- Proxy is routed per site (`proxy_for_url`): Bilibili connects directly
  (global proxies usually have overseas exits and trigger Bilibili risk
  control); other sites use `system_proxy()` (env vars, then OS proxy —
  GUI processes do not inherit shell `HTTP_PROXY`).
- Bilibili returns `HTTP 412 Precondition Failed` for anonymous requests
  without a `buvid` device cookie. `inject_bilibili_buvid` fetches one from
  Bilibili's public `x/frontend/finger/spi` endpoint before parsing.
- Even with buvid + direct connection + browser headers, Bilibili sometimes
  412-blocks python/yt-dlp TLS fingerprints while `curl` works. This is an
  upstream yt-dlp arms race; do NOT burn time re-deriving it.
- Login-state failures go through ONE fallback ladder
  (`net.run_with_browser_cookie_fallback`): anonymous/cookies.txt first, then
  installed browsers' login cookies. Download AND diagnostics use it — so the
  source check reports "可用（已通过 X 登录态验证）" when the fallback works,
  and only reports unavailable after the ladder is exhausted. Do not
  reintroduce a diagnostics path that fails on anonymous 412 with a
  "downloads will probably still work" hedge.
- `doctor --check-api` and the doctor page both resolve one stable public
  video per source (`api.download.youtube` = "Me at the zoo",
  `api.download.bilibili` = official MV) via `check_download_sources()`.
- Frequent probing gets rate-limited by both sites for minutes. Space out
  real network verification runs; a 412/bot-check after repeated tests is
  risk control, not a code regression.

## FFmpeg And Subtitle Rendering

Do not treat `ffmpeg` existence as enough. ASS/rounded subtitle rendering needs
real filter support.

Quick checks:

```bash
.venv/bin/python - <<'PY'
from videocaptioner.core.subtitle.ass_renderer import ffmpeg_supports_ass_filter
print(ffmpeg_supports_ass_filter())
PY
.venv/bin/python -m videocaptioner doctor
```

Known failure signatures:

- `Unknown filter 'ass'`
- `Unknown filter 'subtitles'`
- `No option name near ... ass=...:fontsdir=...`
- `Error parsing filterchain`
- `Exception: FFmpeg Return code: 234`

If `resource/bin/ffmpeg` or `resource/bin/ffprobe` is relinked or replaced,
restart the running desktop app before retesting. The live process can keep an
old binary/path snapshot.

## Testing Standards

Use fast local checks before expensive or online checks:

```bash
.venv/bin/python -m ruff check videocaptioner tests scripts
.venv/bin/python -m compileall videocaptioner scripts tests
.venv/bin/python -m pytest tests/test_cli/test_config.py tests/test_cli/test_parser.py
.venv/bin/python -m pytest tests/test_asr/test_chunking.py tests/test_asr/test_chunked_asr.py tests/test_asr/test_check.py
.venv/bin/python -m pytest tests/test_tts/test_tts_core.py tests/test_subtitle/test_ass_renderer.py
.venv/bin/python -m pytest tests/test_dubbing/test_pipeline.py tests/test_dubbing/test_presets.py
.venv/bin/python -m pytest tests/test_download tests/test_thread tests/test_ui
```

Full `pytest` includes tests that hit online ASR, Bing/Google translation, and
LLM paths. In restricted shell environments these often fail with DNS or missing
key errors. Classify those failures honestly instead of calling the whole app
broken. For external-service checks, report which host/provider failed and
whether the local validation path passed.

When the user asks for broad acceptance or says the app should be "actually
tested", use `docs/dev/e2e-acceptance-checklist.md` as the working checklist.
Do not replace that with a single unit test run. A useful acceptance pass
includes:

- GUI click smoke through home, transcription, subtitle processing, subtitle
  style, video synthesis, dubbing, doctor, logs, and settings.
- Settings changes with an isolated `VIDEOCAPTIONER_CONFIG_FILE`, followed by a
  reload check that proves TOML persistence and UI state agree.
- Provider switching for ASR, LLM, translation, and dubbing, including
  provider-specific row visibility and key/no-key error states.
- Local fixture-based CLI checks for subtitle synthesis and other flows that do
  not require a paid or online provider.
- Clear separation between deterministic local proof, mocked-provider proof,
  and live external-provider proof.
- Screenshot/contact-sheet inspection for visual regressions, not just "script
  exited 0".

Useful real CLI smoke paths with local fixture assets:

```bash
# Create a tiny input video from fixture audio in /tmp.
mkdir -p /tmp/vc-e2e-assets /tmp/vc-e2e-out
cp tests/fixtures/audio/zh.mp3 /tmp/vc-e2e-assets/source-zh.mp3
cp tests/fixtures/audio/zh.srt /tmp/vc-e2e-assets/source-zh.srt
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i color=c=0x202323:s=1280x720:d=3 \
  -i /tmp/vc-e2e-assets/source-zh.mp3 \
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac \
  /tmp/vc-e2e-assets/input-video.mp4

# Soft subtitles.
.venv/bin/python -m videocaptioner synthesize \
  /tmp/vc-e2e-assets/input-video.mp4 \
  -s /tmp/vc-e2e-assets/source-zh.srt \
  --subtitle-mode soft \
  -o /tmp/vc-e2e-out/synth-soft.mp4

# Hard ASS subtitles.
.venv/bin/python -m videocaptioner synthesize \
  /tmp/vc-e2e-assets/input-video.mp4 \
  -s /tmp/vc-e2e-assets/source-zh.srt \
  --subtitle-mode hard --render-mode ass --quality low \
  -o /tmp/vc-e2e-out/synth-hard-ass.mp4

# Rounded subtitle rendering with style override.
.venv/bin/python -m videocaptioner synthesize \
  /tmp/vc-e2e-assets/input-video.mp4 \
  -s /tmp/vc-e2e-assets/source-zh.srt \
  --subtitle-mode hard --render-mode rounded --quality low \
  --style-override '{"font_size":52,"background_radius":28}' \
  -o /tmp/vc-e2e-out/synth-hard-rounded.mp4
```

For UI tests, prefer `/tmp` output folders. Do not commit generated screenshots,
`__pycache__`, `.pytest_cache`, or `.DS_Store`. `work-dir/`, `AppData/`, and
`screenshots/` are local/runtime artifact areas.

Keep acceptance artifacts out of the source tree unless the user explicitly
asks for a persistent design/reference artifact. Use `/tmp/vc-*` for generated
videos, audios, subtitles, screenshots, and isolated config files. Before
calling a broad pass done, clean or at least report any generated artifacts that
remain in the worktree.

## Code Quality Rules

- Prefer deletion and simplification over compatibility layers when old code is
  no longer part of the desired architecture.
- Keep names literal and domain-specific: provider, preset, voice, clone_audio,
  subtitle_mode, render_mode, etc.
- Keep core functions testable without PyQt.
- Keep UI state and business config connected through adapters, not widget
  imports in core/CLI.
- Add focused tests for shared config, parser behavior, rendering command
  quoting, provider normalization, and cache behavior when changing those areas.
- When fixing a visual bug, include screenshot verification. When fixing a
  runtime bug, include the command, test, or log signature that proves the path.
- Be explicit about external limits: no network, missing API key, provider quota,
  or stale running app process.
- Treat open IDE tabs as hints only. If the tab points at a deleted legacy file,
  inspect the current filesystem and imports before recreating it.
- Prefer a small shared component over repeated page-local styling when two
  pages share the same shape: card rows, segmented controls, status pills,
  file/action rows, provider cards, or preview panels.
- When extracting UI components, keep them visually boring and predictable:
  stable width/height, no surprise relayout on click, no one-off color tokens,
  no hidden persistence side effects.
- For provider model lists, separate "load available models" from "test this
  connection". Cache loaded model options per provider in shared config state
  only when they are safe to reuse.
- Comments describe what the code IS now, not how it got there. Delete debugging
  anecdotes ("实测 100ms", "线上 bug", "用户反馈…"), changelog-style narration,
  line-number references, and "we chose NOT to do X" justifications for absent
  features. Keep only non-obvious WHY: anti-regression constraints and domain rules.
- When you change code, fix its comment/docstring in the SAME edit — a comment that
  still describes the old behavior is a stale lie the next reader trusts.
- Don't cite design-mock HTML files or their CSS class names in comments/docstrings
  (see UI Direction); describe the widget, not the mock it came from.

## Workspace Hygiene

This repo often contains large user-approved refactors. Before deleting or
renaming anything, inspect current imports with `rg` and preserve unrelated user
changes. Good cleanup targets are generated artifacts and dead legacy UI files;
bad cleanup targets are user-created design demos or work-in-progress docs that
are still referenced by the conversation.

Legacy files intentionally removed during the settings/component migration
should stay removed unless the user explicitly asks to restore them:

- `videocaptioner/ui/components/MySettingCard.py`
- `videocaptioner/ui/components/app_setting_cards.py`
- `videocaptioner/ui/components/WhisperAPISettingWidget.py`
- `videocaptioner/ui/components/WhisperCppSettingWidget.py`
- `videocaptioner/ui/components/FasterWhisperSettingWidget.py`
- `videocaptioner/ui/components/TranscriptionSettingDialog.py`
- `videocaptioner/ui/components/TranscriptionOutputDialog.py`
- `videocaptioner/ui/components/SubtitleSettingDialog.py`

If an old import is still needed, replace the usage with the current first-party
component or settings page section instead of reviving the old file.

## Current High-Risk Files

Large page files still contain too much UI and state logic:

- `videocaptioner/ui/view/setting_interface.py`
- `videocaptioner/ui/view/dubbing_interface.py`
- `videocaptioner/ui/view/video_synthesis_interface.py`
- `videocaptioner/ui/view/subtitle_style_interface.py`
- `videocaptioner/ui/view/subtitle_interface.py`

Refactor them by extracting reusable rows/panels into `ui/components/`, not by
adding more page-local helper classes. Keep every extraction backed by a smoke
screenshot if it touches layout.

`signal_bus.py` currently exists mostly for video preview playback events. Do
not use it for broad configuration propagation; config changes should flow
through the shared settings/config store.

## Internationalization (i18n)

UI 国际化是 **key-based gettext**，**只翻 UI（PyQt）；core 与 CLI 不翻译**。

- 写文案：`from videocaptioner.ui.i18n import tr`（顶部模块级导入），`label.setText(tr("域.语义"))`。
  key 命名 `<域>.<组件>.<语义>`，通用词用 `common.*`。**禁止** `self.tr(...)` 或把中文当 msgid。
- 枚举下拉标签不手写：`options_from(...)`（`ui/components/settings_controls.py`，内部走 `enum_label`）
  或 `enum_options(EnumCls)`（`ui/common/enum_labels.py`）自动经 `tr(enum.<类>.<成员>)`。
  新增需翻译枚举：加进 `enum_labels.py` 的 `TRANSLATABLE_ENUMS`。
- 动态拼接的 key（配音 provider/voice/tag、识别语言 lclang.\*）和 `tr(常量)` 的 key：前者由
  `dubbing_options.i18n_base_map()`/`config.source_language_i18n_map()` 注册表注入 `.pot`，后者在
  常量定义处用 `N_("key")` 标记让 pybabel 抽取。
- 资源在 `resource/i18n/<lang>/LC_MESSAGES/videocaptioner.{po,mo}`；基准 `zh_Hans` 是 key→中文
  真相源；en/zh_Hant 缺译时运行时回退基准中文（不显示 key）。
- 改了文案后跑 `scripts/i18n.py extract→update→fill-base→translate→compile`（详见
  `docs/dev/i18n-workflow.md`）。CI 跑 `scripts/i18n.py check`（源码 key 集==.pot、基准无空译文）。
- 语言切换 = 保存即弹确认自动重启（不做逐页热刷新）。完整方案见 `docs/dev/i18n-plan.md`。

## Software Update (自动更新)

应用内自动更新 + 实时公告：启动后台拉清单 → 有新版弹「更新提示条」→ 一键下载（带校验）→
「重启并安装」；同一清单里可带公告，按 id 弹一次。**业务在 `core/update`（无 PyQt），UI 只是薄壳。**

```text
core/update/manifest.py    拉 GitHub Release 的 latest.json、选当前平台资产、比版本、取公告
                           （fetch_manifest → (UpdateInfo, Announcement)；fetch_update 是其薄包装；
                           select_announcement / is_newer / select_asset）
core/update/installer.py   下载（复用 core/download，sha256 校验）+ 退出后替换重启
                           （download_update / apply_update / can_self_update / install_root）
ui/thread/update_thread.py UpdateCheckThread（启动后台检查）/ UpdateDownloadThread（进度+取消）
ui/components/update_banner.py  提示条状态机：可用→下载中 NN%→重启并安装；失败可重试
scripts/gen_update_manifest.py  发版时按产物生成 latest.json（CI 跑，挂到同一 Release）
```

硬规则：

- **manifest 与资产同源、可回滚**：`scripts/build_desktop.py` 产物名决定平台键与 kind
  （`*-windows-x64.zip`→`windows-x64`/`onedir-zip`；`*-macos-*-app.zip`→`macos-*`/`app-zip`；
  macOS 裸 onedir 不参与更新）。改产物命名要同步改 `gen_update_manifest.py` 的解析。
  `.github/workflows/build-desktop.yml` 的 `manifest` job 在所有平台构建后生成并 `gh release upload`。
- **安装器/dmg 只给人工首次下载，不参与自动更新**：`scripts/build_windows_installer.py`
  （Inno Setup，`packaging/windows/VideoCaptioner.iss`，per-user 装到 `%LOCALAPPDATA%\Programs`
  → 目录可写、自更新照常）出 `*-windows-x64-setup.exe`；`scripts/build_macos_dmg.py`
  （ad-hoc 签名 + hdiutil）出 `*-macos-*.dmg`。自动更新仍只拉 onedir-zip/app-zip 走 rm+mv 换装，
  故 `gen_update_manifest.py` 只 `rglob VideoCaptioner-*.zip`、忽略 exe/dmg。**无 Apple 证书时
  macOS 首次打开必被 Gatekeeper 提示**（需右键→打开），ad-hoc 签名只避免「已损坏」硬拦截；
  消除提示需付费证书 + 公证。
- **onedir 运行中无法原地覆盖自身**：`apply_update` 解压到临时目录 → 写平台 helper
  （Win `.cmd` / Unix `.sh`，等本进程 PID 退出后 rm+mv 换装并重启，macOS 还要清 quarantine）→
  调用方必须立即 `QApplication.quit()`，否则 helper 一直等。
- **不能自更新就退化**：非 frozen / 安装目录不可写时 `can_self_update()` 为假，提示条按钮变
  「前往下载」开 Release 页（开发态、`VERSION` 以 `0.0.0` 开头时启动检查直接 upToDate，不联网）。
- 下载走 `core/download/downloader.download_file`（镜像兜底 + 续传 + sha256），**不要**另起一套下载。
- **macOS 打包/解压必须用 `ditto`，不能用 Python `zipfile`**：zipfile 会把 .app 的符号链接
  （Qt/Python framework 的 `Versions/Current` 等）拍平成普通文件、丢掉可执行位，解压出的 .app
  起不来。`build_desktop._archive_dir` 与 `installer._extract` 在 Darwin 分支都走 ditto（产物仍是
  标准 zip）；Windows onedir 无软链/执行位，继续用 zipfile。改这两处务必保持 ditto。
- 更新检查/下载线程必须在 `main_window.closeEvent` 里停掉（`updateBanner.stop()` +
  `updateCheckThread.wait()`），否则退出销毁运行中 QThread 触发 abort。
- 旧的 `vc.bkfeng.top/api/version` 轮询 + `version_checker_thread.py` 已删除，不要复活。
- **实时公告**并进同一 `latest.json` 的 `announcement` 块（零服务器：发版后 `gh release upload
  latest.json --clobber` 即可随时改）：`enabled`/`content` + `start_date~end_date` 时间窗 +
  `min_version~max_version` 版本定向（比旧版多的"控制版本看谁"）；客户端按 `id`（缺省取 content
  哈希）去重只弹一次，去重态存 `get_version_state_cache()`，公告与是否有新版互相独立（最新版用户也能收）。
  生成时用 `gen_update_manifest.py --announcement notice.json` 嵌入。
- **强制更新/版本控制**：`mandatory`（一刀切）+ `min_supported`（低于即强制）；命中后 main_window
  禁用 home/batch 页 + 提示条不可关闭。
- 新增更新/公告 UI 文案要走 i18n（`app.update.*` / `app.announcement.*`），改完重跑
  `scripts/i18n.py extract→update→…→compile`。

## Useful Docs

- `docs/dev/config-architecture.md`
- `docs/dev/view-structure.md`
- `docs/dev/asr-chunking.md`
- `docs/dev/translate-module.md`
- `docs/dev/tts-provider-research.md`
- `docs/dev/i18n-workflow.md` · `docs/dev/i18n-plan.md`
- `docs/dev/packaging-and-update-plan.md`
- `videocaptioner/core/subtitle/README.md`

`docs/dev/architecture.md`, `api.md`, and `contributing.md` are public pages
of the VitePress docs site (see `docs/.vitepress/config.*`) — do not move or
delete them. Superseded design mocks and internal review notes live in the
local-only `design-archive/` directory (gitignored).

## Common Commands

```bash
# Launch desktop app.
uv run videocaptioner
.venv/bin/python -m videocaptioner gui

# CLI help.
.venv/bin/python -m videocaptioner --help
.venv/bin/python -m videocaptioner process --help

# Local ASR models (whisper-cpp / faster-whisper). Mirror fallback
# HuggingFace -> hf-mirror -> ModelScope, resumable downloads. Core logic in
# videocaptioner/core/download/, shared by this CLI and the settings UI.
.venv/bin/python -m videocaptioner models list
.venv/bin/python -m videocaptioner models download whisper-cpp tiny

# Config with an isolated test TOML.
VIDEOCAPTIONER_CONFIG_FILE=/tmp/vc-config.toml \
  .venv/bin/python -m videocaptioner config init --non-interactive --force
VIDEOCAPTIONER_CONFIG_FILE=/tmp/vc-config.toml \
  .venv/bin/python -m videocaptioner config show
```

Always check the actual worktree state before editing. This repo often has
large in-progress diffs, HTML design mocks, and generated comparison artifacts.
Do not revert user changes unless explicitly asked.
