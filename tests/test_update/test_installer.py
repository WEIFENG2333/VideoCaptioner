"""更新安装器：helper 脚本生成 / 解压 / 安装根定位 / 自更新可行性 的可测部分。

「替换运行中的自己」无法在单测里安全跑（会动到当前进程目录），只验证脚本内容、
解压结构、以及非 frozen 时的安全退路（不能自更新、apply_update 抛错）。
"""

import zipfile

import pytest

from videocaptioner.core.update import installer


def test_install_root_none_when_not_frozen(monkeypatch):
    monkeypatch.setattr(installer, "is_frozen", lambda: False)
    assert installer.install_root() is None


def test_can_self_update_false_when_not_frozen(monkeypatch):
    monkeypatch.setattr(installer, "is_frozen", lambda: False)
    assert installer.can_self_update() is False


def test_apply_update_raises_when_not_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "install_root", lambda: None)
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"")
    with pytest.raises(RuntimeError):
        installer.apply_update(zip_path)


def test_win_helper_waits_for_pid_then_swaps(tmp_path):
    new_dir = tmp_path / "new" / "VideoCaptioner"
    target = tmp_path / "app" / "VideoCaptioner"
    script = installer._win_helper(new_dir, target, 4321)
    assert "PID eq 4321" in script  # 等本进程退出
    assert f'rmdir /s /q "{target}"' in script
    assert f'move "{new_dir}" "{target}"' in script
    assert "VideoCaptioner.exe" in script  # 重启
    assert "del " in script  # 自删除
    # Inno 安装副本的卸载器要保留：rmdir 前先挪进新目录，move 时带回
    assert "unins000" in script
    assert f'if exist "{target}\\unins000.exe"' in script


def test_unix_helper_mac_clears_quarantine_and_reopens(tmp_path):
    new_app = tmp_path / "new" / "VideoCaptioner.app"
    target = tmp_path / "Applications" / "VideoCaptioner.app"
    script = installer._unix_helper(new_app, target, 99, is_mac=True)
    assert "kill -0 99" in script  # 等本进程退出
    assert f'rm -rf "{target}"' in script
    assert f'mv "{new_app}" "{target}"' in script
    assert "xattr -dr com.apple.quarantine" in script  # 清隔离属性
    assert f'open "{target}"' in script  # 重启


def test_unix_helper_linux_no_quarantine(tmp_path):
    new_dir = tmp_path / "new" / "VideoCaptioner"
    target = tmp_path / "opt" / "VideoCaptioner"
    script = installer._unix_helper(new_dir, target, 7, is_mac=False)
    assert "xattr" not in script
    assert f'"{target}/VideoCaptioner"' in script  # 直接启动可执行文件


def test_extract_finds_named_top_level(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Windows")
    src = tmp_path / "VideoCaptioner.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("VideoCaptioner/VideoCaptioner.exe", "binary")
        zf.writestr("VideoCaptioner/resource/x.txt", "data")
    out = installer._extract(src, tmp_path / "staging")
    assert out.name == "VideoCaptioner"
    assert (out / "VideoCaptioner.exe").exists()


def test_extract_falls_back_to_single_top_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    src = tmp_path / "pkg.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("Renamed.app/Contents/MacOS/x", "binary")
    out = installer._extract(src, tmp_path / "staging")
    assert out.name == "Renamed.app"


def test_download_update_passes_sha256(monkeypatch, tmp_path):
    from videocaptioner.core.update.manifest import UpdateAsset, UpdateInfo

    captured = {}

    def fake_download_file(urls, dest, *, sha256=None, on_progress=None, should_cancel=None):
        captured["urls"] = list(urls)
        captured["sha256"] = sha256
        dest.write_bytes(b"x")
        return dest

    monkeypatch.setattr(installer, "download_file", fake_download_file)
    info = UpdateInfo(
        version="3.0.0",
        notes="",
        mandatory=False,
        asset=UpdateAsset(url="https://github.com/x/y.zip", sha256="deadbeef", size=1, kind="app-zip"),
    )
    out = installer.download_update(info, tmp_path)
    assert out.name == "VideoCaptioner-3.0.0.zip"
    assert captured["sha256"] == "deadbeef"
    assert captured["urls"][-1] == "https://github.com/x/y.zip"  # 直连兜底在末位
