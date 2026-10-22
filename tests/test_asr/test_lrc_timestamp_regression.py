import pytest

from videocaptioner.core.asr.asr_data import ASRDataSeg


@pytest.mark.parametrize(
    "milliseconds, expected",
    [
        (0, "[00:00.00]"),
        (1234, "[00:01.23]"),
        (9999, "[00:09.99]"),
        (59999, "[00:59.99]"),
        (60000, "[01:00.00]"),
        (3599999, "[59:59.99]"),
        (3600000, "[60:00.00]"),
    ],
)
def test_lrc_timestamp_uses_two_digit_seconds_without_overflow(milliseconds, expected):
    assert ASRDataSeg("caption", milliseconds, milliseconds + 1000).to_lrc_ts() == expected
