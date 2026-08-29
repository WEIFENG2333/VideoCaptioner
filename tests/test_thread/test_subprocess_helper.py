"""Unit tests for cancellable subprocess execution."""

import sys

import pytest

from videocaptioner.core.utils.subprocess_helper import (
    SynthesisCancelled,
    run_process_with_cancellation,
)


def test_run_process_with_cancellation_stops_process():
    """A cancellation request should terminate a running child process."""
    command = [sys.executable, "-c", "import time; time.sleep(30)"]

    with pytest.raises(SynthesisCancelled):
        run_process_with_cancellation(command, check_cancel_callback=lambda: True)
