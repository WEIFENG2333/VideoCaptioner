"""CLI output formatting — progress display, status messages, error formatting."""

import sys
import threading
from typing import Optional


def info(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr)


def success(msg: str) -> None:
    print(f"\u2713 {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"\u2717 Error: {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"! Warning: {msg}", file=sys.stderr)


def hint(msg: str) -> None:
    """Print a hint message (e.g. how to fix a config issue)."""
    print(f"  {msg}", file=sys.stderr)


def clean_error(msg: str) -> str:
    """Strip internal noise (ffmpeg build info, stack traces) from error messages."""
    lines = msg.strip().splitlines()
    # Filter ffmpeg build noise but keep Python errors like [Errno]
    noise_prefixes = ("configuration:", "--", "lib", "built with", "Copyright", "ffmpeg version", "[lib", "[swscaler", "[avist", "[mp3")
    meaningful = [line for line in lines if not line.strip().startswith(noise_prefixes)]
    if meaningful:
        # Take the last meaningful line — usually the actual error, not debug context
        return meaningful[-1].strip()[:200]
    return "Operation failed (internal error)"


def config_missing_error(what: str, key: str, env_var: str, cli_flag: str) -> None:
    """Print a standardized 'config missing' error with fix instructions."""
    error(f"{what} is not configured")
    print(file=sys.stderr)
    hint("Fix with any of:")
    hint(f"  1. videocaptioner config set {key} <value>")
    hint(f"  2. export {env_var}=<value>")
    hint(f"  3. videocaptioner ... {cli_flag} <value>")


class ProgressLine:
    """Simple single-line progress indicator for CLI."""

    SPINNER = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"]

    def __init__(self, message: str = ""):
        self.message = message
        self.percent: Optional[int] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame = 0
        self._is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def start(self) -> "ProgressLine":
        self._stop.clear()
        if self._is_tty:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def update(
        self,
        percent: int,
        message: str = "",
        current_time: Optional[float] = None,
        total_duration: Optional[float] = None,
    ) -> None:
        self.percent = percent
        if message:
            self.message = message
        if current_time is not None and total_duration is not None:
            self._time_display = f" {format_time(current_time)} / {format_time(total_duration)}"
        elif total_duration is not None:
            self._time_display = f" / {format_time(total_duration)}"
        else:
            self._time_display = ""

    def _cleanup(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._is_tty:
            sys.stderr.write("\r\033[K")

    def finish(self, message: str = "") -> None:
        self._cleanup()
        if message:
            success(message)

    def fail(self, message: str = "") -> None:
        self._cleanup()
        if message:
            error(message)

    def _spin(self) -> None:
        while not self._stop.is_set():
            char = self.SPINNER[self._frame % len(self.SPINNER)]
            time_display = getattr(self, "_time_display", "")
            if self.percent is not None:
                line = f"\r{char} {self.message} [{self.percent}%]"
                if time_display:
                    line += time_display
            else:
                line = f"\r{char} {self.message}"
            sys.stderr.write(f"{line}\033[K")
            sys.stderr.flush()
            self._frame += 1
            self._stop.wait(0.1)


def format_time(seconds: float) -> str:
    """Format seconds to MM:SS or HH:MM:SS format."""
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
