"""运行程序检测与安装方案单测（不依赖网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from videocaptioner.core.download import detect_program, program_install_plan
from videocaptioner.core.download.models import KIND_FASTER_WHISPER, KIND_WHISPER_CPP


def test_detect_program_finds_bin_dir_executable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    (tmp_path / "whisper-faster.exe").write_bytes(b"x")
    status = detect_program(KIND_FASTER_WHISPER, extra_dirs=(tmp_path,))
    assert status.installed
    assert status.name == "whisper-faster"
    assert status.path == str(tmp_path / "whisper-faster.exe")


def test_detect_program_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    status = detect_program(KIND_WHISPER_CPP, extra_dirs=(tmp_path,))
    assert not status.installed
    assert status.name is None


def test_detect_program_prefers_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/whisper-cli" if name == "whisper-cli" else None
    )
    status = detect_program(KIND_WHISPER_CPP, extra_dirs=(tmp_path,))
    assert status.installed and status.name == "whisper-cli"


def test_whisper_cpp_plan_mac_has_brew_command():
    plan = program_install_plan(KIND_WHISPER_CPP, platform="darwin")
    assert plan.supported
    assert plan.command == "brew install whisper-cpp"


def test_whisper_cpp_plan_windows_links_releases():
    plan = program_install_plan(KIND_WHISPER_CPP, platform="win32")
    assert plan.supported
    assert plan.command is None
    assert plan.link and "whisper.cpp/releases" in plan.link


def test_faster_whisper_plan_windows_has_direct_download():
    plan = program_install_plan(KIND_FASTER_WHISPER, platform="win32")
    assert plan.supported
    assert plan.download is not None
    assert plan.download.name == "whisper-faster.exe"
    assert plan.download.size_bytes
    assert plan.link  # 引导页兜底


def test_faster_whisper_plan_mac_unsupported():
    plan = program_install_plan(KIND_FASTER_WHISPER, platform="darwin")
    assert not plan.supported
    assert plan.command is None and plan.download is None
    assert "Windows" in plan.summary


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        program_install_plan("nope", platform="darwin")


def test_available_model_kinds_platform_filter():
    from videocaptioner.ui.components.model_manager_dialog import available_model_kinds

    assert available_model_kinds("darwin") == ["whisper-cpp"]
    assert available_model_kinds("win32") == ["whisper-cpp", "faster-whisper"]
    assert available_model_kinds("linux") == ["whisper-cpp"]


def test_program_variants_whisper_cpp_mac():
    from videocaptioner.core.download import program_variants

    variants = program_variants("whisper-cpp", platform="darwin")
    assert len(variants) == 1
    assert variants[0].command == "brew install whisper-cpp"


def test_program_variants_faster_whisper_windows():
    from videocaptioner.core.download import program_variants

    variants = program_variants("faster-whisper", platform="win32")
    assert [v.key for v in variants] == ["cpu", "gpu"]
    assert variants[0].download is not None
    # GPU 完整包应用内一键安装：7z 压缩包 + 保留目录结构解压
    assert variants[1].asset is not None
    assert variants[1].asset.asset.endswith(".7z")
    assert variants[1].asset.extract == "tree"
    # CPU/GPU 检测名单互不重叠
    assert not set(variants[0].executables) & set(variants[1].executables)


def test_program_variants_faster_whisper_mac_empty():
    from videocaptioner.core.download import program_variants

    assert program_variants("faster-whisper", platform="darwin") == ()


def test_variant_detect(tmp_path, monkeypatch):
    from videocaptioner.core.download import program_variants

    monkeypatch.setattr("shutil.which", lambda _n: None)
    cpu = program_variants("faster-whisper", platform="win32")[0]
    assert not cpu.detect(extra_dirs=(tmp_path,)).installed
    (tmp_path / "whisper-faster.exe").write_bytes(b"x")
    assert cpu.detect(extra_dirs=(tmp_path,)).installed
