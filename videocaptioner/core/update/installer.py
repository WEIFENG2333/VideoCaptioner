"""下载更新包并在退出后替换+重启（onedir 运行中无法原地覆盖自身，故走 helper 脚本）。

- 下载：复用 core/download/downloader（镜像兜底 + 续传 + sha256 校验 + 进度 + 取消）。
- 应用：解压到临时目录 → 写平台 helper（等本进程退出 → 换掉安装目录 → 重启）→ 由调用方退出应用。
  Windows：替换 onedir 目录（VideoCaptioner/）；macOS：替换 .app 包并清 quarantine。

纯逻辑 + 子进程，无 PyQt 依赖（UI 通过 ui/thread/update_thread.py 接入）。
真正的「替换运行中的自己」无法在单测里安全跑；helper 脚本生成与安装根定位是可测的。
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from videocaptioner.core.download.downloader import download_file
from videocaptioner.core.update.client import UpdateInfo
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("update_installer")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path | None:
    """运行中的安装位置（可替换的根）：

    - macOS .app：返回 .app 包目录（…/VideoCaptioner.app）。
    - Windows / Linux onedir：返回可执行文件所在目录（…/VideoCaptioner/）。
    - 开发态（非 frozen）：返回 None（不能自更新）。
    """
    if not is_frozen():
        return None
    exe = Path(sys.executable).resolve()
    if platform.system() == "Darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        return None
    return exe.parent


def can_self_update() -> bool:
    """frozen + 能定位安装根 + 该位置可写（不可写需提权，MVP 视为不可自更新）。"""
    root = install_root()
    return bool(root and os.access(root.parent, os.W_OK))


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    *,
    on_progress=None,
    should_cancel=None,
) -> Path:
    """下载更新资产到 dest_dir，sha256 校验通过后返回 zip 路径。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"VideoCaptioner-{info.version}.zip"
    return download_file(
        info.urls,
        dest,
        sha256=info.sha256 or None,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )


def _extract(zip_path: Path, into: Path) -> Path:
    """解压更新包，返回顶层产物路径（Windows: VideoCaptioner/；macOS: VideoCaptioner.app/）。"""
    into.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        # 与打包侧 ditto 对应：保留 .app 的符号链接/可执行位/代码签名。zipfile 会把软链拍平、
        # 丢可执行位，解压出的 .app 无法启动 —— 这是 macOS 更新换装必须用 ditto 的原因。
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(into)], check=True)
    else:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(into)
    want = "VideoCaptioner.app" if platform.system() == "Darwin" else "VideoCaptioner"
    cand = into / want
    if cand.exists():
        return cand
    # 兜底：取唯一顶层目录
    tops = [p for p in into.iterdir() if p.is_dir()]
    if len(tops) == 1:
        return tops[0]
    raise FileNotFoundError(f"更新包结构异常，未找到 {want} 于 {into}")


def _win_helper(new_dir: Path, target: Path, pid: int) -> str:
    exe = target / "VideoCaptioner.exe"
    # Inno Setup 安装的副本带卸载器 unins000.exe/.dat；rmdir 会连它一起删，导致更新后
    # 「卸载」入口失效。换装前把卸载器挪进新目录，move 时一并带回（便携版没有，if exist 跳过）。
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f':wait\r\n'
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'if exist "{target}\\unins000.exe" move /y "{target}\\unins000.*" "{new_dir}\\" >nul\r\n'
        f'rmdir /s /q "{target}"\r\n'
        f'move "{new_dir}" "{target}" >nul\r\n'
        f'start "" "{exe}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )


def _unix_helper(new_app: Path, target: Path, pid: int, *, is_mac: bool) -> str:
    relaunch = f'open "{target}"' if is_mac else f'"{target}/VideoCaptioner" &'
    quarantine = f'xattr -dr com.apple.quarantine "{target}" 2>/dev/null || true\n' if is_mac else ""
    return (
        "#!/bin/bash\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
        f'rm -rf "{target}"\n'
        f'mv "{new_app}" "{target}"\n'
        f"{quarantine}"
        f"{relaunch}\n"
        'rm -- "$0"\n'
    )


def apply_update(zip_path: Path, *, staging_dir: Path | None = None) -> None:
    """解压更新包并启动 helper（等本进程退出后替换安装目录并重启）。

    调用方必须在本函数返回后立即退出应用（QApplication.quit / sys.exit），
    否则 helper 会一直等待本进程结束。不能自更新（非 frozen / 不可写）时抛 RuntimeError。
    """
    target = install_root()
    if target is None:
        raise RuntimeError("非打包运行，无法自更新")
    staging = staging_dir or (zip_path.parent / "staging")
    if staging.exists():
        _rmtree(staging)
    new_artifact = _extract(zip_path, staging)
    pid = os.getpid()
    system = platform.system()

    if system == "Windows":
        helper = staging / "apply_update.cmd"
        helper.write_text(_win_helper(new_artifact, target, pid), encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", "start", "", "/min", str(helper)],
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
    else:
        helper = staging / "apply_update.sh"
        helper.write_text(_unix_helper(new_artifact, target, pid, is_mac=system == "Darwin"), encoding="utf-8")
        helper.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(helper)], start_new_session=True, close_fds=True)
    logger.info("update helper launched: %s → %s", new_artifact, target)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
