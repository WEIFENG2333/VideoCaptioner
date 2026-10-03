"""ModelScope download API compatibility tests."""

import inspect
from functools import wraps

from videocaptioner.ui.thread import modelscope_download_thread as download_module


def test_download_matches_installed_modelscope_signature(monkeypatch, tmp_path):
    downloader = download_module.snapshot_download
    signature = inspect.signature(downloader)
    calls = []

    @wraps(downloader)
    def snapshot_download(*args, **kwargs):
        signature.bind(*args, **kwargs)
        calls.append(kwargs)

    monkeypatch.setattr(download_module, "snapshot_download", snapshot_download)
    thread = download_module.ModelscopeDownloadThread("test/model", str(tmp_path))
    errors = []
    thread.error.connect(errors.append)

    thread.run()

    assert errors == []
    assert len(calls) == 1
    assert calls[0]["local_dir"] == str(tmp_path)
    assert ("progress_callbacks" in calls[0]) == ("progress_callbacks" in signature.parameters)


def test_download_without_progress_callback_support(monkeypatch, tmp_path):
    calls = []

    def snapshot_download(model_id, *, local_dir):
        calls.append((model_id, local_dir))

    monkeypatch.setattr(download_module, "snapshot_download", snapshot_download)
    thread = download_module.ModelscopeDownloadThread("test/model", str(tmp_path))
    progress = []
    errors = []
    thread.progress.connect(lambda value, message: progress.append(value))
    thread.error.connect(errors.append)

    thread.run()

    assert calls == [("test/model", str(tmp_path))]
    assert progress == [0, 100]
    assert errors == []


def test_download_preserves_supported_progress_callbacks(monkeypatch, tmp_path):
    calls = []

    def snapshot_download(model_id, *, local_dir, progress_callbacks):
        calls.append((model_id, local_dir))
        callback = progress_callbacks[0]("model.bin", 100)
        callback.update(50)
        callback.update(50)
        callback.end()

    monkeypatch.setattr(download_module, "snapshot_download", snapshot_download)
    thread = download_module.ModelscopeDownloadThread("test/model", str(tmp_path))
    progress = []
    errors = []
    thread.progress.connect(lambda value, message: progress.append(value))
    thread.error.connect(errors.append)

    thread.run()

    assert calls == [("test/model", str(tmp_path))]
    assert progress == [0, 50, 99, 100]
    assert errors == []


def test_download_reports_internal_type_error_without_retry(monkeypatch, tmp_path):
    calls = []

    def snapshot_download(model_id, *, local_dir, progress_callbacks):
        calls.append(model_id)
        raise TypeError("download failed internally")

    monkeypatch.setattr(download_module, "snapshot_download", snapshot_download)
    thread = download_module.ModelscopeDownloadThread("test/model", str(tmp_path))
    progress = []
    errors = []
    thread.progress.connect(lambda value, message: progress.append(value))
    thread.error.connect(errors.append)

    thread.run()

    assert calls == ["test/model"]
    assert progress == [0]
    assert errors == ["download failed internally"]
