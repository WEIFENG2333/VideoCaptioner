"""本地 ASR 运行程序的检测与安装方案。

模型文件之外，whisper-cpp / faster-whisper 还各需要一个可执行程序：

- whisper-cpp：macOS 走 Homebrew；Windows 用官方预编译包。
- faster-whisper：独立程序（Purfview standalone）只有 Windows 版，
  CPU 版单文件可直接下载到 ``BIN_PATH``（启动时已注入 PATH）。

检测口径与 ``core/asr`` 保持一致：先查 PATH，再查应用 bin 目录。
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from videocaptioner.core.download.dependencies import DependencyAsset
from videocaptioner.core.download.models import KIND_FASTER_WHISPER, KIND_WHISPER_CPP, ModelFile

WHISPER_CPP_EXECUTABLES = ("whisper-cli", "whisper-cpp", "whisper", "whisper-cpp-main")
FASTER_WHISPER_EXECUTABLES = (
    "faster-whisper-xxl",
    "faster-whisper",
    "whisper-faster",
    "faster_whisper",
)

_EXECUTABLES = {
    KIND_WHISPER_CPP: WHISPER_CPP_EXECUTABLES,
    KIND_FASTER_WHISPER: FASTER_WHISPER_EXECUTABLES,
}

WHISPER_CPP_RELEASES_URL = "https://github.com/ggml-org/whisper.cpp/releases"
_WHISPER_CPP_REPO = "ggml-org/whisper.cpp"
_WHISPER_CPP_TAG = "v1.9.1"

# 官方预编译包（sha256 来自 release 页）。CPU 用 BLAS 加速版；GPU 用 CUDA 12.4 版。
WHISPER_CPP_CPU_ASSET = DependencyAsset(
    asset="whisper-blas-bin-x64.zip",
    executables=("whisper-cli.exe",),
    archive=True,
    sha256="3c319eab3e87f85883e1ff3d14426c0a1986c661c5eb5985e8af431ed9c4f71f",
    size_bytes=20_800_000,
    repo=_WHISPER_CPP_REPO,
    tag=_WHISPER_CPP_TAG,
)
WHISPER_CPP_GPU_ASSET = DependencyAsset(
    asset="whisper-cublas-12.4.0-bin-x64.zip",
    executables=("whisper-cli.exe",),
    archive=True,
    sha256="106a2030eff8998e4ef320fe72e263a78449e9040386ee27c41ea80b001b601b",
    size_bytes=677_000_000,
    repo=_WHISPER_CPP_REPO,
    tag=_WHISPER_CPP_TAG,
)
# Faster-Whisper-XXL 完整包：exe 依赖同级 _xxl_data 目录，须保留目录结构解压
FASTER_WHISPER_XXL_ASSET = DependencyAsset(
    asset="Faster-Whisper-XXL_r245.2_windows.7z",
    executables=(r"Faster-Whisper-XXLaster-whisper-xxl.exe",),
    archive=True,
    extract="tree",
    size_bytes=1_400_000_000,
    urls_override=(
        "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/"
        "Faster-Whisper-XXL_r245.2_windows.7z",
    ),
)

# Windows CPU 版单文件程序（88.4 MB）
_FASTER_WHISPER_CPU_EXE = ModelFile(
    name="whisper-faster.exe",
    urls=(
        "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster.exe",
    ),
    size_bytes=88_436_526,
)


@dataclass(frozen=True)
class ProgramStatus:
    installed: bool
    name: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ProgramVariant:
    """运行程序的一个可安装形态（弹窗"运行程序"区一行）。

    操作优先级：download（可直接下载）> command（可复制命令）> link（打开页面）。
    """

    key: str
    title: str
    description_missing: str
    description_ready: str
    executables: tuple[str, ...]
    command: str | None = None
    download: ModelFile | None = None
    asset: DependencyAsset | None = None
    link: str | None = None

    def detect(self, extra_dirs: tuple[Path, ...] | None = None) -> ProgramStatus:
        return _detect_executables(self.executables, extra_dirs)


@dataclass(frozen=True)
class ProgramInstallPlan:
    """未安装时的引导方案：summary 必有，其余按平台可选。"""

    summary: str
    command: str | None = None  # 可复制到终端执行的安装命令
    download: ModelFile | None = None  # 可直接下载的单文件程序（落到 bin 目录）
    link: str | None = None  # 手动下载页面
    supported: bool = True  # 当前平台是否支持该引擎


def detect_program(kind: str, extra_dirs: tuple[Path, ...] | None = None) -> ProgramStatus:
    """检测运行程序：PATH + 应用 bin 目录（含 Faster-Whisper-XXL 子目录）。"""
    return _detect_executables(_EXECUTABLES.get(kind, ()), extra_dirs)


def _detect_executables(
    names: tuple[str, ...], extra_dirs: tuple[Path, ...] | None = None
) -> ProgramStatus:
    dirs = extra_dirs if extra_dirs is not None else _default_bin_dirs()
    for name in names:
        path = shutil.which(name)
        if path:
            return ProgramStatus(True, name, path)
        for directory in dirs:
            for candidate in (directory / name, directory / f"{name}.exe"):
                if candidate.exists():
                    return ProgramStatus(True, name, str(candidate))
    return ProgramStatus(False)


def _default_bin_dirs() -> tuple[Path, ...]:
    from videocaptioner.config import BIN_PATH, FASTER_WHISPER_PATH

    return (Path(BIN_PATH), Path(FASTER_WHISPER_PATH))


def program_variants(kind: str, platform: str | None = None) -> tuple[ProgramVariant, ...]:
    """弹窗"运行程序"区展示的安装形态（按推荐顺序）。"""
    plat = platform or sys.platform
    if kind == KIND_WHISPER_CPP:
        if plat == "darwin":
            return (
                ProgramVariant(
                    key="default",
                    title="Whisper CPP 程序",
                    description_missing="在终端执行右侧命令安装，装好后点「重新检测」",
                    description_ready="运行程序已就绪",
                    executables=WHISPER_CPP_EXECUTABLES,
                    command="brew install whisper-cpp",
                    link=WHISPER_CPP_RELEASES_URL,
                ),
            )
        return (
            ProgramVariant(
                key="cpu",
                title="CPU 版",
                description_missing="通用版本，无需显卡，约 20 MB",
                description_ready="运行程序已就绪",
                executables=WHISPER_CPP_EXECUTABLES,
                asset=WHISPER_CPP_CPU_ASSET,
            ),
            ProgramVariant(
                key="gpu",
                title="GPU 版",
                description_missing="需 NVIDIA 显卡，转录更快，约 650 MB",
                description_ready="运行程序已就绪",
                executables=WHISPER_CPP_EXECUTABLES,
                asset=WHISPER_CPP_GPU_ASSET,
            ),
        )
    if kind == KIND_FASTER_WHISPER:
        if not plat.startswith("win"):
            return ()
        return (
            ProgramVariant(
                key="cpu",
                title="CPU 版",
                description_missing="通用版本，无需显卡，约 88 MB",
                description_ready="运行程序已就绪",
                executables=("whisper-faster",),
                download=_FASTER_WHISPER_CPU_EXE,
            ),
            ProgramVariant(
                key="gpu",
                title="GPU 版",
                description_missing="需 NVIDIA 显卡，长视频更快，完整包约 1.4 GB",
                description_ready="运行程序已就绪",
                executables=("faster-whisper-xxl", "faster-whisper", "faster_whisper"),
                asset=FASTER_WHISPER_XXL_ASSET,
            ),
        )
    raise ValueError(f"unknown program kind: {kind}")


def program_install_plan(kind: str, platform: str | None = None) -> ProgramInstallPlan:
    plat = platform or sys.platform
    if kind == KIND_WHISPER_CPP:
        if plat == "darwin":
            return ProgramInstallPlan(
                summary="用 Homebrew 安装 whisper.cpp，完成后点重新检测。",
                command="brew install whisper-cpp",
                link=WHISPER_CPP_RELEASES_URL,
            )
        if plat.startswith("win"):
            return ProgramInstallPlan(
                summary="在「设置 → 转录配置 → 管理模型」里一键下载 CPU 或 GPU 版。",
                download=None,
                link=WHISPER_CPP_RELEASES_URL,
            )
        return ProgramInstallPlan(
            summary="用系统包管理器安装 whisper.cpp（或自行编译），完成后点重新检测。",
            link=WHISPER_CPP_RELEASES_URL,
        )
    if kind == KIND_FASTER_WHISPER:
        if plat.startswith("win"):
            return ProgramInstallPlan(
                summary="在「设置 → 转录配置 → 管理模型」里一键下载 CPU 或 GPU 版。",
                download=_FASTER_WHISPER_CPU_EXE,
                link=WHISPER_CPP_RELEASES_URL,
            )
        return ProgramInstallPlan(
            summary="Faster Whisper 独立程序仅支持 Windows，当前系统请改用 WhisperCpp。",
            supported=False,
        )
    raise ValueError(f"unknown program kind: {kind}")
