"""通用文件下载器。

设计要点：
- 一个文件可配多个镜像 URL，按顺序兜底（连接失败 / 超时 / 4xx/5xx 都切下一个）；
- 下载写入 ``<dest>.part``，完成并通过校验后原子替换到目标路径；
- 同一 URL 重试时用 HTTP Range 续传 ``.part``，服务器不支持就从头来；
- 进度通过回调上报，取消通过回调轮询，便于 CLI / Qt 线程各自接入。
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 60
CHUNK_SIZE = 256 * 1024

# GitHub 资产国内直连慢/被墙：加速镜像优先、直连兜底。镜像生态更迭快、死镜像常以
# 200 返回 HTML 错误页——调用方务必配 sha256/validate 验真。全项目共用这一份列表，
# 避免各模块自带副本漂移（update 模块曾复制了一份早已失效的 ghproxy.com）。
GH_MIRRORS = ("https://gh-proxy.com/", "https://ghfast.top/")


def gh_mirror_urls(direct_url: str) -> tuple[str, ...]:
    """一个 GitHub 直链的下载地址序列：镜像优先 + 直连兜底。"""
    return tuple(mirror + direct_url for mirror in GH_MIRRORS) + (direct_url,)


class DownloadError(Exception):
    """所有镜像都下载失败。"""


class DownloadCancelled(Exception):
    """调用方主动取消下载。"""


@dataclass(frozen=True)
class DownloadProgress:
    """单文件下载进度（total 未知时为 None）。"""

    file_name: str
    received: int
    total: int | None


ProgressCallback = Callable[[DownloadProgress], None]
CancelCheck = Callable[[], bool]


def download_file(
    urls: list[str] | tuple[str, ...],
    dest: Path,
    *,
    sha1: str | None = None,
    sha256: str | None = None,
    validate: Callable[[Path], None] | None = None,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    session: requests.Session | None = None,
) -> Path:
    """从镜像列表下载一个文件到 dest，返回 dest。

    任意镜像成功即返回；全部失败抛 DownloadError；
    取消抛 DownloadCancelled（保留 .part 供下次续传）。
    ``validate(part)`` 在校验和之后执行，抛 DownloadError 视为该镜像失败换下一个
    ——失效的加速镜像常以 HTTP 200 返回 HTML 错误页，校验和缺失时靠它兜底。
    """
    if not urls:
        raise DownloadError(f"{dest.name}: 没有可用的下载地址")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    http = session or requests.Session()

    errors: list[str] = []
    for url in urls:
        try:
            _fetch_to_part(http, url, part, dest.name, on_progress, should_cancel)
            _verify_digest(part, "sha256", sha256)
            _verify_digest(part, "sha1", sha1)
            if validate is not None:
                validate(part)
            os.replace(part, dest)
            return dest
        except DownloadCancelled:
            raise
        except (requests.RequestException, DownloadError, OSError) as exc:
            errors.append(f"{_host(url)}: {exc}")
            logger.warning("download failed from %s: %s", url, exc)
            if isinstance(exc, DownloadError):
                # 校验失败说明 .part 内容坏了，不能带到下一个镜像续传
                part.unlink(missing_ok=True)
    raise DownloadError(f"{dest.name} 下载失败（{len(urls)} 个镜像都不可用）：" + "；".join(errors))


def _fetch_to_part(
    http: requests.Session,
    url: str,
    part: Path,
    display_name: str,
    on_progress: ProgressCallback | None,
    should_cancel: CancelCheck | None,
) -> None:
    resume_from = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    response = http.get(
        url,
        stream=True,
        headers=headers,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        allow_redirects=True,
    )
    if resume_from and response.status_code == 200:
        # 服务器不支持 Range，从头下
        resume_from = 0
    elif response.status_code not in (200, 206):
        response.close()
        raise DownloadError(f"HTTP {response.status_code}")

    total = _total_size(response, resume_from)
    mode = "ab" if resume_from else "wb"
    received = resume_from
    with open(part, mode) as fh:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if should_cancel is not None and should_cancel():
                response.close()
                raise DownloadCancelled(display_name)
            if not chunk:
                continue
            fh.write(chunk)
            received += len(chunk)
            if on_progress is not None:
                on_progress(DownloadProgress(display_name, received, total))
    if total is not None and received < total:
        raise DownloadError(f"连接中断（{received}/{total} 字节）")


def _total_size(response: requests.Response, resume_from: int) -> int | None:
    length = response.headers.get("Content-Length")
    if length is None or not length.isdigit():
        return None
    if response.status_code == 206:
        return resume_from + int(length)
    return int(length)


def _verify_digest(path: Path, algo: str, expected: str | None) -> None:
    if not expected:
        return
    digest = hashlib.new(algo)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise DownloadError(f"{algo.upper()} 校验失败（{actual[:12]}… != {expected[:12]}…）")


def _host(url: str) -> str:
    return url.split("/")[2] if "://" in url else url
