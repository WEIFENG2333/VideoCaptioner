"""models command — manage local ASR models (whisper-cpp / faster-whisper)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.core.download import (
    DownloadCancelled,
    DownloadError,
    find_model,
    iter_models,
    model_install_state,
)


def _models_dir(args: Namespace) -> Path:
    custom = getattr(args, "models_dir", None)
    if custom:
        path = Path(custom).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    from videocaptioner.config import MODEL_PATH

    return Path(MODEL_PATH)


def run(args: Namespace, config: dict) -> int:
    action = getattr(args, "models_action", None)
    if action == "download":
        return _run_download(args)
    return _run_list(args)


def _run_list(args: Namespace) -> int:
    models_dir = _models_dir(args)
    kind = getattr(args, "kind", None)
    print(f"Models directory: {models_dir}")
    current_kind = None
    for spec in iter_models(kind):
        if spec.kind != current_kind:
            current_kind = spec.kind
            print(f"\n{current_kind}")
        installed = model_install_state(spec, models_dir)
        mark = "✓ installed" if installed else "  -"
        print(f"  {spec.name:<16} {spec.size_text:>8}   {mark:<12} {spec.description}")
    print()
    print("Download with: videocaptioner models download <kind> <name>")
    return EXIT.SUCCESS


def _run_download(args: Namespace) -> int:
    spec = find_model(args.kind, args.name)
    if spec is None:
        output.error(f"Unknown model: {args.kind}/{args.name}")
        output.hint("List available models with: videocaptioner models list")
        return EXIT.USAGE_ERROR

    models_dir = _models_dir(args)
    if model_install_state(spec, models_dir):
        output.success(f"{spec.key} is already installed in {models_dir}")
        return EXIT.SUCCESS

    quiet = getattr(args, "quiet", False)
    progress = None if quiet else output.ProgressLine(f"Downloading {spec.key}").start()

    def report(event) -> None:
        if progress is None:
            return
        if event.total_bytes:
            percent = int(event.total_received * 100 / event.total_bytes)
        elif event.file.total:
            percent = int(event.file.received * 100 / event.file.total)
        else:
            percent = 0
        label = f"{event.file.file_name} ({event.file_index}/{event.file_count})"
        progress.update(percent, f"Downloading {label}")

    from videocaptioner.core.download import download_model

    try:
        target = download_model(spec, models_dir, on_progress=report)
    except DownloadCancelled:
        if progress:
            progress.fail("Download cancelled")
        return EXIT.GENERAL_ERROR
    except DownloadError as exc:
        if progress:
            progress.fail(str(exc))
        else:
            output.error(str(exc))
        output.hint("Check your network or retry later; partial files resume automatically.")
        return EXIT.RUNTIME_ERROR

    if progress:
        progress.finish(f"{spec.key} ready at {target}")
    else:
        output.success(f"{spec.key} ready at {target}")
    return EXIT.SUCCESS
