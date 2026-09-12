"""本地 ASR 模型清单与安装管理。

清单覆盖 whisper-cpp（单个 ggml .bin）与 faster-whisper（目录式多文件）。
每个文件都带按序兜底的镜像链：HuggingFace 官方 → hf-mirror（国内可达的
HF 反代）→ ModelScope，保证国内外网络都能下载成功。

模型保存约定与 core/asr 的查找逻辑保持一致：
- whisper-cpp: ``<models_dir>/ggml-<name>.bin``
- faster-whisper: ``<models_dir>/faster-whisper-<name>/`` 目录
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from videocaptioner.core.download.downloader import (
    CancelCheck,
    DownloadProgress,
    download_file,
)

KIND_WHISPER_CPP = "whisper-cpp"
KIND_FASTER_WHISPER = "faster-whisper"

_HF = "https://huggingface.co"
_HF_MIRROR = "https://hf-mirror.com"
_MODELSCOPE = "https://www.modelscope.cn/models"


@dataclass(frozen=True)
class ModelFile:
    name: str
    urls: tuple[str, ...]
    sha1: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class ModelSpec:
    kind: str
    name: str
    label: str
    files: tuple[ModelFile, ...]
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.name}"

    @property
    def display_name(self) -> str:
        """用户视角的落盘名：单文件模型是文件名，目录模型是目录名。"""
        if self.kind == KIND_FASTER_WHISPER:
            return f"faster-whisper-{self.name}"
        return self.files[0].name

    @property
    def total_bytes(self) -> int:
        return sum(file.size_bytes or 0 for file in self.files)

    @property
    def size_text(self) -> str:
        return _format_size(self.total_bytes)

    def target_dir(self, models_dir: Path) -> Path:
        if self.kind == KIND_FASTER_WHISPER:
            return Path(models_dir) / f"faster-whisper-{self.name}"
        return Path(models_dir)


def _format_size(num_bytes: int) -> str:
    if num_bytes >= 1_000_000_000:
        return f"{num_bytes / 1_000_000_000:.1f} GB"
    return f"{num_bytes / 1_000_000:.0f} MB"


@dataclass(frozen=True)
class ModelDownloadProgress:
    """模型级下载进度。

    file 是当前文件的单文件进度；total_received / total_bytes 是按清单
    精确字节数聚合出的模型级总进度（含已完成文件）。
    """

    file_index: int
    file_count: int
    file: DownloadProgress
    total_received: int
    total_bytes: int


def _ggml_urls(filename: str) -> tuple[str, ...]:
    return (
        f"{_HF}/ggerganov/whisper.cpp/resolve/main/{filename}",
        f"{_HF_MIRROR}/ggerganov/whisper.cpp/resolve/main/{filename}",
        f"{_MODELSCOPE}/cjc1887415157/whisper.cpp/resolve/master/{filename}",
    )


# 模型用途一句话（弹窗/CLI 共用）
MODEL_DESCRIPTIONS = {
    "tiny": "轻量测试和快速预览",
    "base": "速度和准确率更均衡",
    "small": "课程视频常用模型",
    "medium": "更高准确率",
    "large-v1": "上一代高准确率模型",
    "large-v2": "高准确率离线转录",
    "large-v3": "高准确率离线转录",
    "large-v3-turbo": "提速版大模型，接近 large-v3",
}


def _whisper_cpp_spec(name: str, label: str, size_bytes: int, sha1: str) -> ModelSpec:
    filename = f"ggml-{name}.bin"
    return ModelSpec(
        kind=KIND_WHISPER_CPP,
        name=name,
        label=label,
        files=(ModelFile(filename, _ggml_urls(filename), sha1, size_bytes),),
        description=MODEL_DESCRIPTIONS.get(name, ""),
    )


# 字节数与 SHA1 均来自官方仓库实测（HEAD Content-Length / GET，2026-06-11 抓取）。
WHISPER_CPP_MODELS: tuple[ModelSpec, ...] = (
    _whisper_cpp_spec("tiny", "Tiny", 77_691_713, "bd577a113a864445d4c299885e0cb97d4ba92b5f"),
    _whisper_cpp_spec("base", "Base", 147_951_465, "465707469ff3a37a2b9b8d8f89f2f99de7299dac"),
    _whisper_cpp_spec("small", "Small", 487_601_967, "55356645c2b361a969dfd0ef2c5a50d530afd8d5"),
    _whisper_cpp_spec("medium", "Medium", 1_533_763_059, "fd9727b6e1217c2f614f9b698455c4ffd82463b4"),
    _whisper_cpp_spec("large-v1", "Large v1", 3_094_623_691, "b1caaf735c4cc1429223d5a74f0f4d0b9b59a299"),
    _whisper_cpp_spec("large-v2", "Large v2", 3_094_623_691, "0f4c8e34f21cf1a914c59d8b3ce882345ad349d6"),
)


def _faster_whisper_urls(name: str, filename: str) -> tuple[str, ...]:
    # Systran 没有发布 large-v3-turbo，社区 ct2 转换仓是事实标准
    hf_repo = (
        "deepdml/faster-whisper-large-v3-turbo-ct2"
        if name == "large-v3-turbo"
        else f"Systran/faster-whisper-{name}"
    )
    return (
        f"{_HF}/{hf_repo}/resolve/main/{filename}",
        f"{_HF_MIRROR}/{hf_repo}/resolve/main/{filename}",
        f"{_MODELSCOPE}/pengzhendong/faster-whisper-{name}/resolve/master/{filename}",
    )


def _faster_whisper_spec(
    name: str, label: str, file_sizes: dict[str, int]
) -> ModelSpec:
    return ModelSpec(
        kind=KIND_FASTER_WHISPER,
        name=name,
        label=label,
        files=tuple(
            ModelFile(
                filename,
                _faster_whisper_urls(name, filename),
                size_bytes=size_bytes,
            )
            for filename, size_bytes in file_sizes.items()
        ),
        description=MODEL_DESCRIPTIONS.get(name, ""),
    )


# 每个文件的字节数均来自官方仓库实测（HEAD Content-Length / GET，2026-06-11 抓取）。
FASTER_WHISPER_MODELS: tuple[ModelSpec, ...] = (
    _faster_whisper_spec("tiny", "Tiny", {
        "config.json": 2_249,
        "model.bin": 75_538_270,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("base", "Base", {
        "config.json": 2_309,
        "model.bin": 145_217_532,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("small", "Small", {
        "config.json": 2_370,
        "model.bin": 483_546_902,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("medium", "Medium", {
        "config.json": 2_257,
        "model.bin": 1_527_906_378,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("large-v1", "Large v1", {
        "config.json": 2_352,
        "model.bin": 3_086_912_962,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("large-v2", "Large v2", {
        "config.json": 2_796,
        "model.bin": 3_086_912_962,
        "tokenizer.json": 2_203_239,
        "vocabulary.txt": 459_861,
    }),
    _faster_whisper_spec("large-v3", "Large v3", {
        "config.json": 2_394,
        "model.bin": 3_087_284_237,
        "tokenizer.json": 2_480_617,
        "vocabulary.json": 1_068_114,
        "preprocessor_config.json": 340,
    }),
    _faster_whisper_spec("large-v3-turbo", "Large v3 Turbo", {
        "config.json": 2_263,
        "model.bin": 1_617_884_929,
        "tokenizer.json": 2_710_337,
        "vocabulary.json": 1_068_114,
        "preprocessor_config.json": 340,
    }),
)


def iter_models(kind: str | None = None) -> Iterator[ModelSpec]:
    for spec in (*WHISPER_CPP_MODELS, *FASTER_WHISPER_MODELS):
        if kind is None or spec.kind == kind:
            yield spec


def find_model(kind: str, name: str) -> ModelSpec | None:
    for spec in iter_models(kind):
        if spec.name == name:
            return spec
    return None


def model_install_state(spec: ModelSpec, models_dir: Path) -> bool:
    """模型文件是否已就位（与 core/asr 的查找口径一致）。"""
    target = spec.target_dir(models_dir)
    if spec.kind == KIND_WHISPER_CPP:
        # 与 whisper_cpp.py 的 glob 口径一致（兼容手动放入的同名变体）
        return any(Path(models_dir).glob(f"*ggml*{spec.name}*.bin"))
    return all((target / file.name).exists() for file in spec.files)


def has_partial_download(spec: ModelSpec, models_dir: Path) -> bool:
    """是否存在中断的下载（.part 文件，下次下载会续传）。"""
    target = spec.target_dir(models_dir)
    return any(
        (target / f"{file.name}.part").exists()
        for file in spec.files
        if not (target / file.name).exists()
    )


def remove_model(spec: ModelSpec, models_dir: Path) -> None:
    """删除模型的全部本地文件（含 .part 残留；faster-whisper 删整个目录）。"""
    target = spec.target_dir(models_dir)
    if spec.kind == KIND_FASTER_WHISPER:
        import shutil

        if target.exists():
            shutil.rmtree(target)
        return
    for file in spec.files:
        (target / file.name).unlink(missing_ok=True)
        (target / f"{file.name}.part").unlink(missing_ok=True)
    # 同名变体（手动放入的 ggml-*tiny*.bin）也一并清掉，保证状态判定翻转
    for matched in Path(models_dir).glob(f"*ggml*{spec.name}*.bin"):
        matched.unlink(missing_ok=True)


def download_model(
    spec: ModelSpec,
    models_dir: Path,
    *,
    on_progress: Callable[[ModelDownloadProgress], None] | None = None,
    should_cancel: CancelCheck | None = None,
) -> Path:
    """下载模型的全部文件（已存在的跳过），返回模型所在目录。"""
    target = spec.target_dir(models_dir)
    count = len(spec.files)
    done_bytes = 0
    for index, file in enumerate(spec.files, start=1):
        dest = target / file.name
        if dest.exists():
            done_bytes += file.size_bytes or 0
            continue

        def report(
            progress: DownloadProgress, _index: int = index, _base: int = done_bytes
        ) -> None:
            if on_progress is not None:
                on_progress(
                    ModelDownloadProgress(
                        _index,
                        count,
                        progress,
                        _base + progress.received,
                        spec.total_bytes,
                    )
                )

        download_file(
            file.urls,
            dest,
            sha1=file.sha1,
            on_progress=report if on_progress is not None else None,
            should_cancel=should_cancel,
        )
        done_bytes += file.size_bytes or 0
    return target
