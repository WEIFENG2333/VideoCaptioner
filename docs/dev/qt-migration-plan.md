# qfluentwidgets / PyQt5 Removal Record

This is the migration record for removing `PyQt-Fluent-Widgets`, removing the
hidden VLC player path, and moving the desktop UI to PySide6.

## Baseline

- Checkpoint commit before the migration: `55532cf chore: checkpoint shared config and ui refresh`.
- Baseline screenshots:
  - `/tmp/vc-qfluent-baseline-20260609-dark/contact-sheet.png`
  - `/tmp/vc-qfluent-baseline-20260609-dark/settings-contact-sheet.png`
  - `/tmp/vc-qfluent-baseline-20260609-dark/compact-contact-sheet.png`
  - `/tmp/vc-qfluent-baseline-20260609-light/contact-sheet.png`
  - `/tmp/vc-qfluent-baseline-20260609-light/settings-contact-sheet.png`
  - `/tmp/vc-qfluent-baseline-20260609-light/compact-contact-sheet.png`
- Last verified local suite before migration:
  - `126 passed, 1 warning`
  - `ruff check videocaptioner tests scripts` passed.

## Current Dependency Surface

The cutover is complete at the source/dependency level:

- Runtime UI code imports PySide6 directly.
- Runtime UI code no longer imports `qfluentwidgets`.
- `PyQt-Fluent-Widgets`, PyQt5, PyQt5-Qt5, and PyQt5-sip are removed from
  `pyproject.toml` and `uv.lock`.
- `VideoCaptioner.spec` hidden imports target PySide6 and `shiboken6`.
- The app uses first-party Qt controls from
  `videocaptioner/ui/components/controls.py`.

VLC removal has started:

- Removed `videocaptioner/ui/components/video_widget.py`.
- Removed `videocaptioner/ui/common/signal_bus.py`, because it only served the
  hidden VLC player.
- Removed `PYTHON_VLC_MODULE_PATH` setup from `videocaptioner/config.py`.
- Subtitle row clicks now only select rows; they no longer emit hidden playback
  signals.

## Target Architecture

Use PySide6 directly and keep project-owned UI controls in one place:

- `videocaptioner/ui/components/`
  - reusable cards, setting rows, file pickers, pill/tag widgets, buttons,
    progress/status rows, and form controls.
- `videocaptioner/ui/common/`
  - app theme tokens, icon loading, settings state, and Qt-only helpers.
- `videocaptioner/ui/view/`
  - page composition only; avoid local copies of button/card/input styling when
    a reusable component exists.

The UI must not depend on qfluentwidgets for configuration, navigation, theme,
icons, messages, buttons, cards, combo boxes, scroll areas, dialogs, or menus.

## Completed Migration Steps

- Added PySide6 dependency and updated packaging.
- Converted Qt imports from PyQt5 to PySide6.
- Converted `pyqtSignal` to `Signal`.
- Updated multimedia API usage:
  - `QMediaPlayer.setMedia(QMediaContent(...))` became `setSource(QUrl)`.
  - Preview players now use `QAudioOutput`.
  - Voice-clone recording now uses `QMediaCaptureSession`, `QAudioInput`, and
    `QMediaRecorder`.
- Removed qfluent runtime/dependency surface.
- Kept first-party controls clean:
   - Do not introduce a qfluent-compatible shim or old class names.
   - Keep generic controls in `ui/components/controls.py`.
   - Keep workflow design-language atoms in `workbench.py`, form cards in
     `form_cards.py`, and settings controls in `settings_controls.py`.

## Remaining Follow-Up

- Continue visual polish of the first-party controls, especially native-looking
  combo boxes/buttons in light mode and compact navigation.
- Keep screenshot smoke tooling producing dark/light/compact contact sheets.
- Use `docs/dev/e2e-acceptance-checklist.md` for broader live-provider and
  end-to-end validation.

## Acceptance Standard

- `rg "qfluentwidgets|PyQt-Fluent-Widgets|pyqt-fluent|python-vlc|\\bvlc\\b"`
  returns no relevant project dependency or import.
- `rg "from PyQt5|import PyQt5|PyQt5-Qt5|PyQt5-sip"` returns no relevant
  project dependency or import.
- `uv run videocaptioner` starts the GUI with PySide6.
- Baseline pages can be screenshot in dark, light, normal width, and compact
  width.
- Core local tests and ruff pass.
- No hidden VLC player dependency remains.
- Settings values still persist to the shared TOML config and survive page
  switching.
- Provider-specific fields, model loading, connection tests, dubbing preview,
  subtitle processing, subtitle style preview, video synthesis, diagnostics, and
  full flow still behave according to `docs/dev/e2e-acceptance-checklist.md`.
