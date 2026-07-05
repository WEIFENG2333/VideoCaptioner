"""
voxgate 子进程 stdio 后端：PCM 写入 ``voxgate transcribe`` 的 stdin，从 stdout 读原生
protocol 报文（``-f protocol``，每行一条 ASR send/recv JSON，详见 docs/dev/voxgate-protocol.md）。
无服务、无端口、无 WebSocket。
"""

from __future__ import annotations

import collections
import json
import queue
import subprocess
import sys
import threading
import time
from typing import Deque, Optional

from videocaptioner import config
from videocaptioner.core.realtime.backends.base import (
    LiveCaptionError,
    LiveTranscriber,
    OnError,
    OnSegment,
    OnState,
    TranscriberState,
)
from videocaptioner.core.realtime.events import TranscriptSegment
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_voxgate_backend")

_EXE = ".exe" if sys.platform.startswith("win") else ""
_BINARY_NAME = f"voxgate{_EXE}"

_OK_CODE = 20000000  # status_code 成功值


def find_voxgate_binary(configured: str = "") -> Optional[str]:
    """发现 voxgate 可执行文件（配置路径 → 自带 bin → 用户 bin → PATH）。"""
    return config.find_binary(_BINARY_NAME, configured)


def _no_window_kwargs() -> dict:
    """Windows 下不要弹出控制台窗口。"""
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


class VoxgateBackend(LiveTranscriber):
    """``voxgate transcribe`` 子进程 stdio 后端。"""

    def __init__(
        self,
        binary: str,
        language: str = "zh",
        on_segment: Optional[OnSegment] = None,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
    ) -> None:
        super().__init__(on_segment, on_state, on_error)
        if not binary:
            raise LiveCaptionError("未找到 voxgate 转录程序：可到「诊断」页一键下载，或在设置中指定其路径。")
        self._binary = binary
        self._language = language or "zh"
        self._proc: Optional[subprocess.Popen] = None
        # 写 stdin 解耦到独立 sender 线程：feed() 只入队，voxgate 背压只卡 sender，
        # 音频泵继续排空采集队列，不在语音中段丢句。
        self._send_q: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self._send_thread: Optional[threading.Thread] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._err_thread: Optional[threading.Thread] = None
        self._stderr_tail: Deque[str] = collections.deque(maxlen=40)
        self._closed = False   # 进程已关、接收线程应退出
        self._stopping = False  # 收尾中：停止喂音频，但接收线程仍要读到末段
        self._ready = threading.Event()  # 收到首个事件（确认进程活着）
        # 全局句号：见模块 docstring / _consume_results 的句边界判定。
        self._sentence_no = 0
        self._cur_text = ""          # 当前句在途文本（用于重置检测 + 边界补定稿）
        self._cur_start: Optional[float] = None
        self._cur_end: Optional[float] = None
        self._last_index: Optional[int] = None

    # ----- LiveTranscriber -----

    def start(self) -> None:
        self._emit_state(TranscriberState.CONNECTING)
        cmd = [
            self._binary, "transcribe", "-",
            "--input-format", "pcm16", "--stream", "-f", "protocol",
            "-l", self._language,
        ]
        logger.info("启动 voxgate transcribe（stdio）：%s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_no_window_kwargs(),
            )
        except Exception as exc:
            raise LiveCaptionError(f"无法启动 voxgate 子进程：{exc}") from exc

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        self._err_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._err_thread.start()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

        # 短暂等待：进程立刻退出（坏二进制/配置/鉴权）则抛错，否则就绪。不死等首个事件——
        # task.started 可能要等首帧音频，而音频在 start 之后才喂。
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise LiveCaptionError(
                    f"voxgate 启动即退出（code={self._proc.returncode}）：{self._stderr_text()}"
                )
            if self._ready.is_set():
                break
            time.sleep(0.05)
        self._emit_state(TranscriberState.LISTENING)

    def feed(self, pcm16: bytes) -> None:
        # 只入队，写 stdin 由 _send_loop 完成。
        if self._closed or self._stopping or not pcm16:
            return
        self._send_q.put_nowait(pcm16)

    def _send_loop(self) -> None:
        """唯一的 stdin 写入者：从队列取 PCM 写给 voxgate；None 哨兵=排空完毕。"""
        while True:
            pcm = self._send_q.get()
            if pcm is None:  # 收尾哨兵：已入队音频写完
                return
            proc = self._proc
            stdin = proc.stdin if proc is not None else None
            if stdin is None:
                continue
            try:
                stdin.write(pcm)
                stdin.flush()
            except Exception as exc:
                if not self._closed:
                    logger.debug("写入 voxgate stdin 失败：%s", exc)
                return

    def stop(self) -> None:
        if self._closed or self._stopping:
            return
        # 收尾顺序不可乱：停喂 → 排空已入队音频 → 关 stdin(EOF) → 等接收线程读完末段。
        # 提前 terminate 或漏写末段音频都会截断末句。
        self._stopping = True  # feed() 起不再入队
        proc = self._proc
        # 哨兵让 sender 写尽队列后再关 stdin
        self._send_q.put_nowait(None)
        if self._send_thread is not None:
            self._send_thread.join(timeout=3.0)
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()  # EOF：voxgate 冲刷末段后退出
            except Exception:
                pass
            # 等接收线程读到 EOF（含末段 ASR 往返），给足宽限，勿提前 terminate
            if self._recv_thread is not None:
                self._recv_thread.join(timeout=5.0)
            self._closed = True
            if proc.poll() is None:  # 还没退就强制收
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        else:
            self._closed = True
        self._emit_state(TranscriberState.STOPPED)

    # ----- 接收解析 -----

    def _recv_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        out = proc.stdout
        while True:
            try:
                raw = out.readline()  # 逐行 protocol JSON；readline 无迭代器的预读批延迟
            except Exception:
                break
            if not raw:  # EOF：进程结束
                break
            self._ready.set()
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if self.on_raw is not None:  # 调试落盘：把原生 protocol JSON 行原文回调出去（LiveDebugTap）
                try:
                    self.on_raw(line)
                except Exception:
                    pass
            try:
                ev = json.loads(line)
            except Exception:
                continue
            self._dispatch(ev)
        # 非收尾态下进程意外退出（崩溃/被杀/网络断）：上报错误，免得 UI 一直挂在「监听中」
        if not self._stopping and not self._closed:
            code = proc.poll()
            self._emit_error(f"voxgate 进程意外退出（code={code}）：{self._stderr_text()}")

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self._stderr_tail.append(text)

    def _stderr_text(self) -> str:
        return " | ".join(list(self._stderr_tail)[-6:]) or "（无错误输出）"

    def _dispatch(self, ev: dict) -> None:
        # 原生 protocol：每行一条 send/recv 报文。只关心 recv 的 result_json（转录结果）
        # 与 SessionFinished（收尾）。分句由 _consume_results 用 _sentence_no + index变化/滚动重置
        # 判定，绝不直接拿 index 当 seg_id（连续语音会一直复用同一 index，按 index 上屏会全被覆盖）。
        if ev.get("direction") != "recv":
            return
        code = ev.get("status_code")
        if code is not None and code != _OK_CODE:
            self._emit_error(f"voxgate 转录错误（{code}）：{ev.get('status_message') or ''}".strip())
            return
        if ev.get("message_type") == "SessionFinished":
            return  # 末句若没等到自己的 FIN，交装配器 close() 兜底定稿
        rj = ev.get("result_json")
        if isinstance(rj, dict) and rj.get("results"):
            self._consume_results(rj["results"])

    @staticmethod
    def _is_reset(old: str, new: str) -> bool:
        """豆包「滚动重置」检测：连续语音到单句上限会把 text 截短重来（同 index 复用）。
        **只看长度腰斩**（new 不到 old 的一半，如 211→15）。绝不能看「公共前缀变小」：twopass
        改写（whose→who's、补标点）只降一两字却变前缀，据此切会把同句的生长前缀重复定稿成多句。"""
        return bool(old) and len(new) * 2 < len(old)

    def _consume_results(self, results: list) -> None:
        # 句边界 = 豆包 index 变化 OR 文本滚动重置；命中则把在途的上一段定稿、开新句。
        # 否则连续语音（无 VAD、index 不变）会被覆盖成最后残段。
        for r in results:
            if not isinstance(r, dict):
                continue
            text = r.get("text") or ""
            if not text.strip():
                continue  # VAD 收尾帧带的下一句空占位（text:""）
            idx = r.get("index", 0)
            st, et = r.get("start_time"), r.get("end_time")
            is_final = bool(r.get("is_vad_finished"))  # 真·停顿才是天然句边界
            boundary = (
                (self._last_index is not None and idx != self._last_index)
                or self._is_reset(self._cur_text, text)
            )
            if boundary and self._cur_text.strip():
                # 在途上一段还没等到自己的定稿信号 → 在边界处补定稿，再开新句（不丢内容）
                self._emit_segment(TranscriptSegment(
                    f"voxgate#{self._sentence_no}", self._cur_text, is_final=True,
                    start_time=self._cur_start, end_time=self._cur_end))
                self._sentence_no += 1
                self._cur_text = ""
                self._cur_start = self._cur_end = None
            self._last_index = idx
            self._emit_segment(TranscriptSegment(
                f"voxgate#{self._sentence_no}", text, is_final=is_final,
                start_time=st, end_time=et))
            if is_final:  # 自带 VAD 定稿：本句收尾，开新句
                self._sentence_no += 1
                self._cur_text = ""
                self._cur_start = self._cur_end = None
            else:
                self._cur_text = text
                if self._cur_start is None:
                    self._cur_start = st
                self._cur_end = et
