# Configuration Architecture Notes

## Original Problem

`qfluentwidgets` setting cards directly mutated global config state:

- The native switch and options cards wrote through qfluent's global config
  setter.
- The setter mutated the item, wrote JSON immediately, and emitted restart/theme
  signals.

That makes the widget, persistence format, validation, and business config source the same object. It is hard to reuse in CLI and hard to replace visually.

## Current Boundary

Shared persistence now lives in core:

- `videocaptioner.core.application.config_store`
- default file: `videocaptioner.config.APPDATA_PATH / "config.toml"`
- test override: `VIDEOCAPTIONER_CONFIG_FILE=/path/to/config.toml`

There is no separate CLI config module anymore. CLI code imports the core store
directly.

Business execution should consume plain application config:

- `videocaptioner.core.application.app_config.AppConfig`
- `videocaptioner.core.application.task_builder.TaskBuilder`

Adapters are responsible for translating existing surfaces:

- shared TOML/CLI dict -> `videocaptioner.cli.config_adapter.app_config_from_cli`
- UI memory state -> `videocaptioner.ui.config_adapter.app_config_from_ui`

`videocaptioner.ui.common.config` is an in-memory binding over the shared TOML
file. It does not read or write qfluentwidgets' old JSON settings file.
`cfg.set(...)` and direct `SettingField.value` changes are synced back to TOML.
The UI config state is implemented by `videocaptioner.ui.common.settings_state`,
not qfluentwidgets' `QConfig`.

Existing UI pages still call `TaskFactory`, but task construction itself lives
in `TaskBuilder`.

The settings page no longer uses qfluentwidgets' native setting-card classes.
`videocaptioner.ui.components.form_cards` owns the page's card/group
widgets and writes through the shared settings state.

All settings controls now read from our `SettingField` objects and write through
`cfg.set(...)`. Theme and language state are stored in the shared TOML-backed
settings state instead of a widget-library config object.

## Next Migration Direction

Next UI refactors should keep the same clean boundary:

- Read and write through `config_store` or a small repository wrapper around it.
- Keep UI-only settings under `[ui]`; keep workflow settings under `[transcribe]`,
  `[subtitle]`, `[translate]`, `[synthesize]`, `[dubbing]`, and provider sections.
- Keep moving large page-local layouts into first-party reusable widgets when
  those pages are redesigned.
- Keep theme state first-party through `theme_tokens` and `settings_state`.

The removed `signal_bus` pattern should not return for configuration
propagation. Config changes should move through the shared config store and
small page-local signals only where a specific widget needs immediate refresh.
