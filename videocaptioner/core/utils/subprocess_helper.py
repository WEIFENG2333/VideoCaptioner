"""子进程输出流处理工具模块"""

import queue
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from ..utils.logger import setup_logger

logger = setup_logger("subprocess_helper")


class SynthesisCancelled(Exception):
    """Raised when a video synthesis process is cancelled by the user."""


class StreamReader:
    """通用的子进程输出流Reading器"""

    def __init__(self, process: subprocess.Popen):
        """
        初始化流Reading器

        Args:
            process: 子进程对象
        """
        self.process = process
        self.output_queue = queue.Queue()
        self.threads = []

    def start_reading(self) -> None:
        """启动异步Readingstdout和stderr"""
        # 启动stdoutReading线程
        if self.process.stdout:
            stdout_thread = threading.Thread(
                target=self._read_stream,
                args=(self.process.stdout, "stdout"),
                daemon=True,
            )
            stdout_thread.start()
            self.threads.append(stdout_thread)

        # 启动stderrReading线程
        if self.process.stderr:
            stderr_thread = threading.Thread(
                target=self._read_stream,
                args=(self.process.stderr, "stderr"),
                daemon=True,
            )
            stderr_thread.start()
            self.threads.append(stderr_thread)

    def _read_stream(self, stream, stream_name: str) -> None:
        """Reading流并放入队列"""
        try:
            for line in iter(stream.readline, ""):
                if line:
                    self.output_queue.put((stream_name, line))
        except Exception as e:
            logger.debug(f"Reading {stream_name} ended: {e}")
        finally:
            stream.close()

    def get_output(self, timeout: float = 0.1) -> Optional[Tuple[str, str]]:
        """
        获取输出

        Args:
            timeout: 等待超时时间

        Returns:
            (stream_name, line) 或 None
        """
        try:
            return self.output_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_remaining_output(self) -> list:
        """获取队列中剩余的All输出"""
        output = []
        while not self.output_queue.empty():
            try:
                output.append(self.output_queue.get_nowait())
            except queue.Empty:
                break
        return output

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return self.output_queue.empty()


def stop_process(process: subprocess.Popen, timeout: int = 3) -> None:
    """Stop a child process gracefully, then force-kill it if necessary."""
    if process.poll() is not None:
        return

    try:
        process.terminate()
    except OSError:
        return

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("子进程未在限时内退出，强制结束进程")
        try:
            process.kill()
        except OSError:
            return
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("强制结束子进程超时")


def remove_partial_output(output: str) -> None:
    """Remove a file left behind by a cancelled or failed process."""
    try:
        output_path = Path(output)
        if output_path.exists():
            output_path.unlink()
            logger.info("已删除未完成的输出文件: %s", output)
    except OSError as exc:
        logger.warning("删除未完成的输出文件失败: %s", exc)


def run_process_with_cancellation(
    cmd: list,
    check_cancel_callback: Optional[Callable[[], bool]] = None,
    stdout_handler: Optional[Callable[[str], None]] = None,
    stderr_handler: Optional[Callable[[str], None]] = None,
    poll_interval: float = 0.1,
    **popen_kwargs,
) -> Tuple[int, str]:
    """Run a process while keeping its pipes drained and honoring cancellation.

    Returns:
        A tuple containing the return code and captured stderr text.

    Raises:
        SynthesisCancelled: If ``check_cancel_callback`` requests cancellation.
    """
    default_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    default_kwargs.update(popen_kwargs)

    process = subprocess.Popen(cmd, **default_kwargs)
    reader = StreamReader(process)
    reader.start_reading()
    stderr_lines = []

    def dispatch_output(output: Optional[Tuple[str, str]]) -> None:
        if not output:
            return
        stream_name, line = output
        if stream_name == "stdout" and stdout_handler:
            stdout_handler(line)
        elif stream_name == "stderr":
            stderr_lines.append(line)
            if stderr_handler:
                stderr_handler(line)

    try:
        while process.poll() is None:
            if check_cancel_callback and check_cancel_callback():
                stop_process(process)
                raise SynthesisCancelled("合成已取消")
            dispatch_output(reader.get_output(timeout=poll_interval))

        process.wait()
        for thread in reader.threads:
            thread.join(timeout=1)
        while True:
            output = reader.get_output(timeout=0)
            if output is None:
                break
            dispatch_output(output)

        return process.returncode, "".join(stderr_lines)
    except BaseException:
        if process.poll() is None:
            stop_process(process)
        raise


def run_process_with_stream_reader(
    cmd: list,
    stdout_handler: Optional[Callable[[str], None]] = None,
    stderr_handler: Optional[Callable[[str], None]] = None,
    **popen_kwargs,
) -> subprocess.Popen:
    """
    运行子进程并使用StreamReader处理输出

    Args:
        cmd: Command列表
        stdout_handler: stdout行处理函数
        stderr_handler: stderr行处理函数
        **popen_kwargs: 传递给subprocess.Popen的额外参数

    Returns:
        子进程对象

    Example:
        ```python
        def handle_stdout(line):
            print(f"[stdout] {line.strip()}")

        def handle_stderr(line):
            print(f"[stderr] {line.strip()}")

        process = run_process_with_stream_reader(
            ["ls", "-la"],
            stdout_handler=handle_stdout,
            stderr_handler=handle_stderr
        )
        process.wait()
        ```
    """
    # 设置默认参数
    default_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "bufsize": 1,  # 行缓冲
    }
    default_kwargs.update(popen_kwargs)

    # 启动进程
    process = subprocess.Popen(cmd, **default_kwargs)

    # 创建流Reading器
    reader = StreamReader(process)
    reader.start_reading()

    # 处理输出的线程
    def process_output():
        while True:
            # 检查进程状态
            if process.poll() is not None:
                # 进程已ended，Reading剩余输出
                for stream_name, line in reader.get_remaining_output():
                    if stream_name == "stdout" and stdout_handler:
                        stdout_handler(line)
                    elif stream_name == "stderr" and stderr_handler:
                        stderr_handler(line)
                break

            # Reading输出
            output = reader.get_output()
            if output:
                stream_name, line = output
                if stream_name == "stdout" and stdout_handler:
                    stdout_handler(line)
                elif stream_name == "stderr" and stderr_handler:
                    stderr_handler(line)

    # 如果提供了处理函数，启动处理线程
    if stdout_handler or stderr_handler:
        handler_thread = threading.Thread(target=process_output, daemon=True)
        handler_thread.start()

    return process
