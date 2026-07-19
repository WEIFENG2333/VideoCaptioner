"""运行依赖（ffmpeg / voxgate）的下载清单与安装（纯 Python，无 PyQt）。

这是「以后 pip 安装等渠道缺二进制时，用一个弹窗补齐」的单一数据源：所有外部二进制的
下载地址集中在 :data:`DEPENDENCIES` 注册表，按 依赖 × 系统 × 架构 给镜像兜底
（ghproxy 镜像优先、GitHub Releases 直连兜底，与现有 HF→hf-mirror→ModelScope 思路一致）。

安装统一走「下载 → （压缩包则解压取出可执行）→ 补可执行位 → 落到 ``BIN_PATH``」。
``BIN_PATH`` 在启动时已被前置到 PATH（见 config.py），所以装好即可被发现。

要加新依赖：只在 :data:`DEPENDENCIES` 里加一项即可，UI/线程/检测全部自动适配。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from videocaptioner.config import BIN_PATH, CACHE_PATH, find_binary
from videocaptioner.core.download.downloader import (
    CancelCheck,
    DownloadError,
    DownloadProgress,
    ProgressCallback,
    download_file,
    gh_mirror_urls,
)
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("dependency_download")

# ffmpeg 发布在主项目 Release（用户自行上传，见 design/MANIFEST）；
# voxgate 有自己的发布仓库（CI 出全平台包），直接从那里取，固定版本以保证与客户端协议匹配。
_MAIN_REPO = "WEIFENG2333/VideoCaptioner"
# ffmpeg 放主仓库一个「专用、不随 app 版本移动」的固定 tag 的 release 里，
# 这样发 app 新版（latest 移动）不会影响 ffmpeg 下载。
_FFMPEG_TAG = "ffmpeg-bin"
_VOXGATE_REPO = "WEIFENG2333/voxgate"
_VOXGATE_TAG = "v0.3.0"  # 升级 voxgate：改这里 + 同步下方 sha256（需回归实时字幕协议）
# release 附带 checksums.txt 的 sha256：加速镜像是第三方代理，靠校验和防篡改/防错误页
_VOXGATE_SHA256 = {
    "voxgate_darwin_amd64.tar.gz": "7848a0cad309c38cdd1ddd07b471621aec4a43b24deec6f3febaee3180fba30f",
    "voxgate_darwin_arm64.tar.gz": "4054dc98aa11994fde3e649f0ba15178b14d58bc29016e3b2a7d589d7cd68af1",
    "voxgate_linux_amd64.tar.gz": "66ac755d9b8e9d4bedfb20c0afedb491c41dc67404aa2d1e856422fc5d438b33",
    "voxgate_linux_arm64.tar.gz": "a9b285d5622d8b5f043ea97d90ce469c0b7bc3c97f6b188fa46c213d986ceb99",
    "voxgate_windows_amd64.zip": "c7f953490daf53ba9fd2fdcc6987c24bf9da0bc86a828c33427f63700329e138",
}
PhaseCallback = Callable[[str], None]


def _gh_urls(repo: str, tag: str, asset: str) -> tuple[str, ...]:
    """某 release 资产的镜像兜底地址：加速镜像优先，GitHub 直连兜底。

    tag="latest" 用 releases/latest/download（永远指向最新 release 的同名资产）；
    具体 tag 用 releases/download/<tag>（固定版本，可复现）。
    """
    if tag == "latest":
        direct = f"https://github.com/{repo}/releases/latest/download/{asset}"
    else:
        direct = f"https://github.com/{repo}/releases/download/{tag}/{asset}"
    return gh_mirror_urls(direct)


def current_platform() -> tuple[str, str]:
    """归一当前系统/架构为 (os_key, arch)：os ∈ {macos, windows, linux}，arch ∈ {arm64, x64}。"""
    os_key = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return os_key, arch


@dataclass(frozen=True)
class DependencyAsset:
    """某依赖在某平台的下载件。"""

    asset: str  # release 资产名（也是 _gh_urls 的输入）
    executables: tuple[str, ...]  # 主可执行文件（可含相对子路径，用于检测/解压匹配）
    archive: bool = False  # True=压缩包（解压取出可执行+随附动态库）；False=裸二进制（重命名落地）
    extract: str = "flat"  # flat=按 basename 取 exe+动态库；tree=保留目录结构全量解压
    sha1: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    repo: str = _MAIN_REPO  # 资产所在仓库
    tag: str = "latest"  # release tag；latest=取最新
    urls_override: tuple[str, ...] = ()  # 非空则直接用这些地址（非 GitHub 资产）

    @property
    def urls(self) -> tuple[str, ...]:
        if self.urls_override:
            return self.urls_override
        return _gh_urls(self.repo, self.tag, self.asset)


@dataclass(frozen=True)
class DependencySpec:
    """一个运行依赖（含各平台下载件）。"""

    key: str  # "ffmpeg" | "voxgate"
    display_name: str
    description: str
    optional: bool  # 可选功能依赖（缺失只警告，不算硬错误）
    assets: dict[str, DependencyAsset]  # "{os}-{arch}" -> 下载件

    def asset_for(self, os_key: str, arch: str) -> Optional[DependencyAsset]:
        return self.assets.get(f"{os_key}-{arch}")


# ---- 注册表 -----------------------------------------------------------------

_PLATFORMS = (
    ("macos", "arm64"),
    ("macos", "x64"),
    ("windows", "x64"),
    ("linux", "x64"),
    ("linux", "arm64"),
)


def _voxgate_asset(os_key: str, arch: str) -> DependencyAsset:
    # voxgate 自己的 release 用 Go 命名（darwin/amd64）+ 压缩包；Windows 包内还随附
    # libogg/libopus.dll，靠解压时一并取出动态库来保证可运行。
    go_os = {"macos": "darwin", "windows": "windows", "linux": "linux"}[os_key]
    go_arch = {"arm64": "arm64", "x64": "amd64"}[arch]
    if os_key == "windows":
        asset = f"voxgate_{go_os}_{go_arch}.zip"
        exes = ("voxgate.exe",)
    else:
        asset = f"voxgate_{go_os}_{go_arch}.tar.gz"
        exes = ("voxgate",)
    return DependencyAsset(
        asset=asset,
        executables=exes,
        archive=True,
        sha256=_VOXGATE_SHA256.get(asset),
        repo=_VOXGATE_REPO,
        tag=_VOXGATE_TAG,
    )


def _ffmpeg_asset(os_key: str, arch: str) -> DependencyAsset:
    ext = ".exe" if os_key == "windows" else ""
    return DependencyAsset(
        asset=f"ffmpeg-{os_key}-{arch}.zip",
        executables=(f"ffmpeg{ext}",),
        archive=True,
        tag=_FFMPEG_TAG,
    )


DEPENDENCIES: tuple[DependencySpec, ...] = (
    DependencySpec(
        key="ffmpeg",
        display_name="FFmpeg",
        description="音视频转码与字幕压制",
        optional=False,
        assets={f"{o}-{a}": _ffmpeg_asset(o, a) for o, a in _PLATFORMS},
    ),
    DependencySpec(
        key="voxgate",
        display_name="voxgate",
        description="实时字幕本地转录引擎",
        optional=True,
        assets={f"{o}-{a}": _voxgate_asset(o, a) for o, a in _PLATFORMS},
    ),
)


def iter_dependencies() -> tuple[DependencySpec, ...]:
    return DEPENDENCIES


def dependency_for(key: str) -> DependencySpec:
    for spec in DEPENDENCIES:
        if spec.key == key:
            return spec
    raise KeyError(f"未知依赖：{key}")


def asset_for(spec: DependencySpec) -> Optional[DependencyAsset]:
    """当前平台的下载件；None 表示该平台暂无预编译件。"""
    os_key, arch = current_platform()
    return spec.asset_for(os_key, arch)


# ---- 检测 -------------------------------------------------------------------


def _find_executable(name: str) -> Optional[str]:
    """在 自带 bin / 用户 bin / PATH 里找可执行文件（统一走 config.find_binary）。"""
    return find_binary(name)


# (path, mtime, size) -> version。is_installed 在 GUI 线程被反复调用（诊断页/下载
# 对话框刷新），--version 子进程不能每次都跑（Windows 首启还会被杀软扫描卡几秒）。
_voxgate_version_cache: dict[tuple[str, float, int], str] = {}


def _voxgate_version(binary: str) -> str:
    """`voxgate --version` → "0.3.0"；探测失败返回空串（按版本未知处理，不拦使用）。"""
    try:
        stat = os.stat(binary)
        cache_key = (binary, stat.st_mtime, stat.st_size)
    except OSError:
        return ""
    if cache_key in _voxgate_version_cache:
        return _voxgate_version_cache[cache_key]
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        parts = (result.stdout or result.stderr).strip().split()
        version = parts[-1] if parts else ""
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    _voxgate_version_cache[cache_key] = version
    return version


def is_installed(spec: DependencySpec) -> bool:
    """该依赖是否已就绪（所有可执行文件都能找到）。"""
    if spec.key == "voxgate":
        # 复用 voxgate 的发现顺序（含用户在设置里指定的路径）
        from videocaptioner.core.realtime.backends.voxgate import find_voxgate_binary

        found = find_voxgate_binary()
        if found is None:
            return False
        # 我们装进 BIN_PATH 的实例跟着钉住的版本走：旧版本视为未就绪，诊断页
        # 的「下载 voxgate」即升级入口。用户自己指定/系统 PATH 的不做版本检查。
        if Path(found).parent == Path(BIN_PATH):
            version = _voxgate_version(found)
            if version and version != _VOXGATE_TAG.lstrip("v"):
                return False
        return True
    asset = asset_for(spec)
    if asset is None:
        return False
    return all(_find_executable(name) is not None for name in asset.executables)


def installed_path(spec: DependencySpec) -> Optional[str]:
    """已安装时返回主可执行文件路径，否则 None。"""
    if spec.key == "voxgate":
        from videocaptioner.core.realtime.backends.voxgate import find_voxgate_binary

        return find_voxgate_binary()
    asset = asset_for(spec)
    if asset is None or not asset.executables:
        return None
    return _find_executable(asset.executables[0])


# ---- 安装 -------------------------------------------------------------------


class DependencyUnsupported(RuntimeError):
    """当前平台没有该依赖的预编译件。"""


def install_dependency(
    spec: DependencySpec,
    *,
    on_progress: Optional[ProgressCallback] = None,
    on_phase: Optional[PhaseCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
    bin_dir: Optional[Path] = None,
) -> Path:
    """下载并安装一个依赖到 ``bin_dir``（默认 BIN_PATH），返回主可执行文件路径。

    流程：下载到缓存 → 压缩包则解压取出可执行（否则重命名）→ 补可执行位。下载阶段经
    ``on_progress`` 上报字节进度；解压阶段经 ``on_phase`` 上报一句状态文案。
    """
    asset = asset_for(spec)
    if asset is None:
        raise DependencyUnsupported(f"{spec.display_name} 暂无适用于当前系统的预编译件")
    return install_asset(
        asset,
        spec.display_name,
        on_progress=on_progress,
        on_phase=on_phase,
        should_cancel=should_cancel,
        bin_dir=bin_dir,
    )


def install_asset(
    asset: DependencyAsset,
    display_name: str,
    *,
    on_progress: Optional[ProgressCallback] = None,
    on_phase: Optional[PhaseCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
    bin_dir: Optional[Path] = None,
) -> Path:
    """下载并安装一个具体资产到 ``bin_dir``（默认 BIN_PATH），返回主可执行文件路径。"""
    bin_path = Path(bin_dir) if bin_dir is not None else Path(BIN_PATH)
    bin_path.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(CACHE_PATH) / "deps"
    download_dest = cache_dir / asset.asset

    download_file(
        asset.urls,
        download_dest,
        sha1=asset.sha1,
        sha256=asset.sha256,
        validate=_validate_archive if asset.archive else None,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )

    if asset.archive:
        if on_phase is not None:
            on_phase("正在解压…")
        if asset.extract == "tree":
            placed = _extract_tree(download_dest, bin_path)
        else:
            placed = _extract_runtime_files(download_dest, asset.executables, bin_path)
        download_dest.unlink(missing_ok=True)  # 解压完删压缩包，省空间
        main = bin_path / asset.executables[0]
        if not main.exists():
            raise RuntimeError(f"{display_name} 安装失败：压缩包里没有 {asset.executables[0]}")
    else:
        main = bin_path / asset.executables[0]
        os.replace(download_dest, main)
        placed = [main]

    # 给可执行文件补 +x（动态库不必，但 chmod 也无害）
    for path in placed:
        _make_executable(path)
    logger.info("%s 已安装：%s", display_name, f"{len(placed)} 个文件")
    return main


def _is_shared_lib(name: str) -> bool:
    """是否是运行所需的动态库（随可执行一起取出，否则 Windows 上缺 dll 跑不起来）。"""
    low = name.lower()
    return low.endswith((".dll", ".dylib", ".so")) or ".so." in low


def _validate_archive(path: Path) -> None:
    """压缩包验真：失效镜像会以 HTTP 200 返回 HTML 错误页，必须当场识破换下一个镜像。"""
    if path.suffix.lower() == ".7z":
        import py7zr

        if not py7zr.is_7zfile(path):
            raise DownloadError(f"{path.name}: 下载内容不是有效压缩包（镜像可能已失效）")
        return
    if not (zipfile.is_zipfile(path) or tarfile.is_tarfile(path)):
        raise DownloadError(f"{path.name}: 下载内容不是有效压缩包（镜像可能已失效）")


def _extract_tree(archive: Path, dest_dir: Path) -> list[Path]:
    """全量解压并保留目录结构（Faster-Whisper-XXL 等 exe 依赖同级数据目录的包）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".7z":
        import py7zr

        with py7zr.SevenZipFile(archive) as sz:
            names = sz.getnames()
            sz.extractall(dest_dir)
        return [dest_dir / n for n in names]
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
            return [dest_dir / i.filename for i in zf.infolist() if not i.is_dir()]
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest_dir)
            return [dest_dir / m.name for m in tf.getmembers() if m.isfile()]
    raise RuntimeError(f"无法识别的压缩格式：{archive.name}")


def _extract_runtime_files(archive: Path, executables: tuple[str, ...], dest_dir: Path) -> list[Path]:
    """从压缩包里取出可执行文件 + 随附动态库，按 basename 扁平落到 dest_dir。

    支持 zip 与 tar(.gz/.xz)；按 basename 匹配以兼容压缩包内的嵌套目录。除目标可执行外，
    一并取出 .dll/.dylib/.so（如 voxgate Windows 包随附的 libopus/libogg.dll），跳过
    LICENSE/README 等文档。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(executables)

    def _want(base: str) -> bool:
        return base in wanted or _is_shared_lib(base)

    placed: list[Path] = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = Path(info.filename).name
                if _want(base):
                    target = dest_dir / base
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                    placed.append(target)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                base = Path(member.name).name
                if _want(base):
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    target = dest_dir / base
                    with extracted as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                    placed.append(target)
    else:
        raise RuntimeError(f"无法识别的压缩格式：{archive.name}")
    return placed


def _make_executable(path: Path) -> None:
    """补上可执行位（Windows 无需）。"""
    if os.name == "nt":
        return
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | 0o111)  # u+x g+x o+x
    except OSError:
        logger.debug("chmod +x 失败：%s", path, exc_info=True)


# 进度类型对外（UI 线程引用）
__all__ = [
    "DependencyAsset",
    "DependencySpec",
    "DependencyUnsupported",
    "DEPENDENCIES",
    "DownloadProgress",
    "asset_for",
    "current_platform",
    "dependency_for",
    "install_dependency",
    "installed_path",
    "is_installed",
    "iter_dependencies",
]
