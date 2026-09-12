"""download command — download online video via the shared core engine.

与 GUI 下载共用 core/download/media.py：代理分流、B 站 buvid、
浏览器登录态兜底、同语言字幕 sidecar 全部一致。
"""

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output


def run(args: Namespace, config: dict) -> int:
    url = args.url
    out_dir = getattr(args, "output", None) or "."
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)

    from videocaptioner.core.download.media import MediaDownloader

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    progress = None if quiet else output.ProgressLine(f"Downloading {url}").start()

    def on_progress(value: int, message: str) -> None:
        if progress:
            progress.update(value, message)

    try:
        video_path, subtitle_path = MediaDownloader(
            url,
            out_dir,
            on_progress=on_progress,
        ).run()
    except Exception as exc:
        message = output.clean_error(str(exc))
        if progress:
            progress.fail(message)
        else:
            output.error(message)
        if verbose:
            import traceback

            traceback.print_exc()
        return EXIT.RUNTIME_ERROR

    if not video_path:
        if progress:
            progress.fail("下载完成但未找到视频文件")
        return EXIT.RUNTIME_ERROR
    if progress:
        progress.finish(f"Done -> {video_path}")
    if subtitle_path and not quiet:
        output.info(f"Subtitle -> {subtitle_path}")
    if quiet:
        print(video_path)
    return EXIT.SUCCESS
