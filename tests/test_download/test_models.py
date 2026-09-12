"""模型清单与安装状态单测（不依赖网络）。"""

from __future__ import annotations

from pathlib import Path

from videocaptioner.core.download import (
    FASTER_WHISPER_MODELS,
    WHISPER_CPP_MODELS,
    find_model,
    iter_models,
    model_install_state,
)
from videocaptioner.core.download.models import KIND_FASTER_WHISPER, KIND_WHISPER_CPP


def test_catalog_covers_expected_models():
    assert [spec.name for spec in WHISPER_CPP_MODELS] == [
        "tiny", "base", "small", "medium", "large-v1", "large-v2",
    ]
    assert [spec.name for spec in FASTER_WHISPER_MODELS] == [
        "tiny", "base", "small", "medium",
        "large-v1", "large-v2", "large-v3", "large-v3-turbo",
    ]


def test_every_file_has_three_mirrors_in_priority_order():
    for spec in iter_models():
        for file in spec.files:
            assert len(file.urls) == 3, f"{spec.key}/{file.name}"
            assert file.urls[0].startswith("https://huggingface.co/")
            assert file.urls[1].startswith("https://hf-mirror.com/")
            assert file.urls[2].startswith("https://www.modelscope.cn/")


def test_whisper_cpp_models_have_sha1():
    for spec in WHISPER_CPP_MODELS:
        assert spec.files[0].sha1, spec.key


def test_every_file_has_exact_size_bytes():
    # 尺寸来自官方仓库实测 Content-Length；展示文案由字节数换算
    for spec in iter_models():
        for file in spec.files:
            assert file.size_bytes and file.size_bytes > 0, f"{spec.key}/{file.name}"
        assert spec.total_bytes > 0


def test_size_text_derived_from_real_bytes():
    cpp_tiny = find_model(KIND_WHISPER_CPP, "tiny")
    assert cpp_tiny is not None
    assert cpp_tiny.total_bytes == 77_691_713
    assert cpp_tiny.size_text == "78 MB"
    fw_large = find_model(KIND_FASTER_WHISPER, "large-v2")
    assert fw_large is not None
    assert fw_large.size_text == "3.1 GB"


def test_find_model():
    spec = find_model(KIND_WHISPER_CPP, "tiny")
    assert spec is not None and spec.files[0].name == "ggml-tiny.bin"
    assert find_model(KIND_WHISPER_CPP, "nope") is None


def test_whisper_cpp_install_state(tmp_path: Path):
    spec = find_model(KIND_WHISPER_CPP, "tiny")
    assert spec is not None
    assert not model_install_state(spec, tmp_path)
    (tmp_path / "ggml-tiny.bin").write_bytes(b"x")
    assert model_install_state(spec, tmp_path)


def test_faster_whisper_install_state_requires_all_files(tmp_path: Path):
    spec = find_model(KIND_FASTER_WHISPER, "tiny")
    assert spec is not None
    target = spec.target_dir(tmp_path)
    target.mkdir(parents=True)
    (target / "model.bin").write_bytes(b"x")
    assert not model_install_state(spec, tmp_path)
    for file in spec.files:
        (target / file.name).write_bytes(b"x")
    assert model_install_state(spec, tmp_path)


def test_target_dir_layout(tmp_path: Path):
    cpp = find_model(KIND_WHISPER_CPP, "base")
    fw = find_model(KIND_FASTER_WHISPER, "base")
    assert cpp is not None and fw is not None
    assert cpp.target_dir(tmp_path) == tmp_path
    assert fw.target_dir(tmp_path) == tmp_path / "faster-whisper-base"


def test_model_descriptions_and_display_names():
    for spec in iter_models():
        assert spec.description, spec.key
    cpp = find_model(KIND_WHISPER_CPP, "tiny")
    fw = find_model(KIND_FASTER_WHISPER, "tiny")
    assert cpp is not None and cpp.display_name == "ggml-tiny.bin"
    assert fw is not None and fw.display_name == "faster-whisper-tiny"


def test_remove_model_whisper_cpp(tmp_path: Path):
    from videocaptioner.core.download import remove_model

    spec = find_model(KIND_WHISPER_CPP, "tiny")
    assert spec is not None
    (tmp_path / "ggml-tiny.bin").write_bytes(b"x")
    (tmp_path / "ggml-tiny.bin.part").write_bytes(b"y")
    assert model_install_state(spec, tmp_path)
    remove_model(spec, tmp_path)
    assert not model_install_state(spec, tmp_path)
    assert not (tmp_path / "ggml-tiny.bin.part").exists()
    # 不误删其他模型
    (tmp_path / "ggml-base.bin").write_bytes(b"x")
    remove_model(spec, tmp_path)
    assert (tmp_path / "ggml-base.bin").exists()


def test_remove_model_faster_whisper(tmp_path: Path):
    from videocaptioner.core.download import remove_model

    spec = find_model(KIND_FASTER_WHISPER, "tiny")
    assert spec is not None
    target = spec.target_dir(tmp_path)
    target.mkdir(parents=True)
    for file in spec.files:
        (target / file.name).write_bytes(b"x")
    assert model_install_state(spec, tmp_path)
    remove_model(spec, tmp_path)
    assert not target.exists()


def test_has_partial_download(tmp_path: Path):
    from videocaptioner.core.download import has_partial_download

    spec = find_model(KIND_WHISPER_CPP, "base")
    assert spec is not None
    assert not has_partial_download(spec, tmp_path)
    (tmp_path / "ggml-base.bin.part").write_bytes(b"y")
    assert has_partial_download(spec, tmp_path)
    # 下载完成后 .part 已被替换，不再算续传态
    (tmp_path / "ggml-base.bin.part").unlink()
    (tmp_path / "ggml-base.bin").write_bytes(b"x")
    assert not has_partial_download(spec, tmp_path)
