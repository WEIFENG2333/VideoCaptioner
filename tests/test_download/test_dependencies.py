"""运行依赖注册表与安装（ffmpeg / voxgate）。

锁住：① 镜像梯子结构（ghproxy 优先 + GitHub 直连兜底）+ 固定 tag URL；② 平台归一；
③ ffmpeg 在主仓库 latest、voxgate 在自己仓库固定版；④ 压缩包安装取出可执行 + 随附动态库
（Windows voxgate 的 dll）、扁平落地、兼容嵌套目录、跳过文档；⑤ 裸二进制安装 + 可执行位；
⑥ 平台无件抛 DependencyUnsupported。
"""

import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from videocaptioner.core.download import dependencies as deps


def test_gh_urls_latest_and_pinned():
    latest = deps._gh_urls("WEIFENG2333/VideoCaptioner", "latest", "ffmpeg-macos-arm64.zip")
    assert latest[-1] == (
        "https://github.com/WEIFENG2333/VideoCaptioner/releases/latest/download/ffmpeg-macos-arm64.zip"
    )
    assert len(latest) > 1  # 镜像在前、直连兜底（不锁定具体镜像域名，镜像生态更迭快）
    assert all(u.endswith(latest[-1]) for u in latest[:-1])
    pinned = deps._gh_urls("WEIFENG2333/voxgate", "v0.2.10", "voxgate_darwin_arm64.tar.gz")
    assert pinned[-1] == (
        "https://github.com/WEIFENG2333/voxgate/releases/download/v0.2.10/voxgate_darwin_arm64.tar.gz"
    )


def test_current_platform_shape():
    os_key, arch = deps.current_platform()
    assert os_key in {"macos", "windows", "linux"}
    assert arch in {"arm64", "x64"}


def test_registry_has_ffmpeg_and_voxgate():
    keys = {spec.key for spec in deps.iter_dependencies()}
    assert {"ffmpeg", "voxgate"} <= keys
    assert deps.dependency_for("ffmpeg").optional is False
    assert deps.dependency_for("voxgate").optional is True
    for spec in deps.iter_dependencies():
        for plat in ("macos-arm64", "windows-x64", "linux-x64", "linux-arm64", "macos-x64"):
            assert plat in spec.assets


def test_ffmpeg_asset_main_repo_latest():
    ff = deps.dependency_for("ffmpeg").asset_for("windows", "x64")
    assert ff.asset == "ffmpeg-windows-x64.zip"
    assert ff.archive is True
    assert ff.executables == ("ffmpeg.exe", "ffprobe.exe")
    assert ff.repo == "WEIFENG2333/VideoCaptioner" and ff.tag == "ffmpeg-bin"


def test_voxgate_asset_own_repo_pinned():
    # voxgate 走自己的仓库、固定版、Go 命名 + 压缩包
    vox_mac = deps.dependency_for("voxgate").asset_for("macos", "arm64")
    assert vox_mac.asset == "voxgate_darwin_arm64.tar.gz"
    assert vox_mac.archive is True
    assert vox_mac.executables == ("voxgate",)
    assert vox_mac.repo == "WEIFENG2333/voxgate"
    assert vox_mac.tag.startswith("v")
    vox_win = deps.dependency_for("voxgate").asset_for("windows", "x64")
    assert vox_win.asset == "voxgate_windows_amd64.zip"
    assert vox_win.executables == ("voxgate.exe",)


def test_voxgate_detection_uses_finder(monkeypatch):
    import videocaptioner.core.realtime.backends.voxgate as vb

    monkeypatch.setattr(vb, "find_voxgate_binary", lambda configured="": "/x/voxgate")
    assert deps.is_installed(deps.dependency_for("voxgate")) is True
    monkeypatch.setattr(vb, "find_voxgate_binary", lambda configured="": None)
    assert deps.is_installed(deps.dependency_for("voxgate")) is False


def _synthetic_spec(asset: deps.DependencyAsset) -> deps.DependencySpec:
    os_key, arch = deps.current_platform()
    return deps.DependencySpec(
        key="x", display_name="X", description="", optional=True,
        assets={f"{os_key}-{arch}": asset},
    )


def test_install_raw_binary(tmp_path, monkeypatch):
    spec = _synthetic_spec(deps.DependencyAsset(asset="tool-bin", executables=("mytool",)))

    def fake_download(urls, dest, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"#!/bin/sh\necho hi\n")
        return Path(dest)

    monkeypatch.setattr(deps, "download_file", fake_download)
    result = deps.install_dependency(spec, bin_dir=tmp_path)
    assert result == tmp_path / "mytool"
    assert result.is_file()
    if os.name != "nt":
        assert os.access(result, os.X_OK)


def test_install_archive_extracts_ffmpeg(tmp_path, monkeypatch):
    spec = deps.dependency_for("ffmpeg")
    asset = deps.asset_for(spec)
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for exe in asset.executables:
            zf.writestr(f"ffmpeg-build/bin/{exe}", b"BINARY")  # 嵌套目录
        zf.writestr("ffmpeg-build/README.txt", b"docs")

    def fake_download(urls, dest, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(archive.read_bytes())
        return Path(dest)

    monkeypatch.setattr(deps, "download_file", fake_download)
    main = deps.install_dependency(spec, bin_dir=tmp_path)
    assert main == tmp_path / asset.executables[0]
    for exe in asset.executables:
        assert (tmp_path / exe).read_bytes() == b"BINARY"
    assert not (tmp_path / "README.txt").exists()  # 文档不落地


def test_windows_voxgate_extracts_bundled_dlls(tmp_path):
    # voxgate Windows 包随附 libogg/libopus.dll，必须一起取出，否则跑不起来
    archive = tmp_path / "voxgate_windows_amd64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("voxgate_windows_amd64/voxgate.exe", b"EXE")
        zf.writestr("voxgate_windows_amd64/libogg.dll", b"OGG")
        zf.writestr("voxgate_windows_amd64/libopus.dll", b"OPUS")
        zf.writestr("voxgate_windows_amd64/LICENSE", b"license")
        zf.writestr("voxgate_windows_amd64/README.md", b"readme")
    out = tmp_path / "out"
    placed = deps._extract_runtime_files(archive, ("voxgate.exe",), out)
    names = {p.name for p in placed}
    assert names == {"voxgate.exe", "libogg.dll", "libopus.dll"}  # 取 exe + dll，丢文档
    assert not (out / "LICENSE").exists()


def test_extract_from_tar(tmp_path):
    archive = tmp_path / "src.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        data = tmp_path / "voxgate"
        data.write_bytes(b"X")
        tf.add(data, arcname="voxgate_darwin_arm64/voxgate")  # 嵌套
    placed = deps._extract_runtime_files(archive, ("voxgate",), tmp_path / "out")
    assert [p.name for p in placed] == ["voxgate"]
    assert placed[0].read_bytes() == b"X"


def test_install_unsupported_platform_raises(tmp_path, monkeypatch):
    spec = deps.dependency_for("voxgate")
    monkeypatch.setattr(deps, "asset_for", lambda s: None)
    with pytest.raises(deps.DependencyUnsupported):
        deps.install_dependency(spec, bin_dir=tmp_path)
