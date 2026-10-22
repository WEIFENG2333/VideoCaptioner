import ntpath

import pytest

from videocaptioner.core.asr.asr_data import handle_long_path


@pytest.mark.parametrize(
    "path",
    [
        "\\\\server\\share\\" + "nested\\" * 40 + "captions.srt",
        "//server/share/" + "nested/" * 40 + "captions.srt",
    ],
)
def test_long_unc_paths_use_extended_unc_prefix(monkeypatch, path):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("os.path.abspath", ntpath.abspath)
    expected = "\\\\?\\UNC\\" + ntpath.abspath(path)[2:]
    assert handle_long_path(path) == expected


def test_extended_unc_path_is_not_prefixed_twice(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    path = "\\\\?\\UNC\\server\\share\\" + "nested\\" * 40 + "captions.srt"
    assert handle_long_path(path) == path


def test_short_unc_path_is_unchanged(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    path = "\\\\server\\share\\captions.srt"
    assert handle_long_path(path) == path
