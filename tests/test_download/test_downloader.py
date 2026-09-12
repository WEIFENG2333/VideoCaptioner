"""downloader 单测：本地 HTTP 服务模拟镜像，离线覆盖核心路径。"""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from videocaptioner.core.download import (
    DownloadCancelled,
    DownloadError,
    download_file,
)

PAYLOAD = b"0123456789abcdef" * 65536  # 1 MB，大于下载 chunk，保证取消能落在中途
PAYLOAD_SHA1 = hashlib.sha1(PAYLOAD).hexdigest()
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    """支持 Range 的静态响应；路径决定行为。"""

    def do_GET(self):  # noqa: N802
        if self.path == "/missing.bin":
            self.send_error(404)
            return
        if self.path == "/flaky.bin" and not getattr(self.server, "flaky_served", False):
            self.server.flaky_served = True
            self.send_error(503)
            return

        data = PAYLOAD
        start = 0
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start = int(range_header.split("=")[1].rstrip("-"))
            self.send_response(206)
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()


def test_download_success_with_sha1(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    result = download_file([f"{server}/ok.bin"], dest, sha1=PAYLOAD_SHA1)
    assert result == dest
    assert dest.read_bytes() == PAYLOAD
    assert not dest.with_suffix(".bin.part").exists()


def test_download_success_with_sha256(server, tmp_path: Path):
    dest = tmp_path / "update.zip"
    result = download_file([f"{server}/ok.bin"], dest, sha256=PAYLOAD_SHA256)
    assert result == dest
    assert dest.read_bytes() == PAYLOAD
    assert not dest.with_suffix(".zip.part").exists()


def test_sha256_mismatch_fails(server, tmp_path: Path):
    dest = tmp_path / "update.zip"
    with pytest.raises(DownloadError) as excinfo:
        download_file([f"{server}/ok.bin"], dest, sha256="0" * 64)
    assert "SHA256" in str(excinfo.value)
    assert not dest.exists()


def test_mirror_fallback_on_404(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    download_file([f"{server}/missing.bin", f"{server}/ok.bin"], dest)
    assert dest.read_bytes() == PAYLOAD


def test_mirror_fallback_on_5xx(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    download_file([f"{server}/flaky.bin", f"{server}/ok.bin"], dest)
    assert dest.read_bytes() == PAYLOAD


def test_all_mirrors_fail(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    with pytest.raises(DownloadError) as excinfo:
        download_file([f"{server}/missing.bin", f"{server}/missing.bin"], dest)
    assert "2 个镜像" in str(excinfo.value)
    assert not dest.exists()


def test_resume_from_part_file(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    part = tmp_path / "model.bin.part"
    part.write_bytes(PAYLOAD[: 16 * 1024])
    download_file([f"{server}/ok.bin"], dest, sha1=PAYLOAD_SHA1)
    assert dest.read_bytes() == PAYLOAD
    assert not part.exists()


def test_sha1_mismatch_tries_next_mirror_then_fails(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    with pytest.raises(DownloadError) as excinfo:
        download_file([f"{server}/ok.bin"], dest, sha1="0" * 40)
    assert "SHA1" in str(excinfo.value)
    assert not dest.exists()
    # 校验失败的 .part 必须清掉，避免坏数据被续传
    assert not dest.with_suffix(".bin.part").exists()


def test_cancel_keeps_part_for_resume(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    calls = {"n": 0}

    def cancel_after_first_chunk() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(DownloadCancelled):
        download_file(
            [f"{server}/ok.bin"], dest, should_cancel=cancel_after_first_chunk
        )
    assert not dest.exists()
    # 部分数据保留在 .part，下次可走 Range 续传
    part = dest.with_suffix(".bin.part")
    assert part.exists() and 0 < part.stat().st_size < len(PAYLOAD)


def test_progress_reported(server, tmp_path: Path):
    dest = tmp_path / "model.bin"
    seen: list[tuple[int, int | None]] = []
    download_file(
        [f"{server}/ok.bin"],
        dest,
        on_progress=lambda p: seen.append((p.received, p.total)),
    )
    assert seen
    assert seen[-1][0] == len(PAYLOAD)
    assert seen[-1][1] == len(PAYLOAD)
