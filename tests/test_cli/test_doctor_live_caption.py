"""doctor 的实时字幕检测契约。

锁住：① voxgate 找得到 → ok；② 找不到 → warn + 修复提示（实时字幕可选，不让 doctor
整体失败）；③ 配置的二进制路径透传给 finder；④ fun-asr 按是否有百炼 Key 给 ok/warn；
⑤ 该检测确实被接进 run_diagnostics。voxgate 走 ``voxgate transcribe`` 子进程 stdio，
不再有本地服务/探活，故无 server_url 分支。
"""

import videocaptioner.core.realtime.backends.voxgate as voxgate_backend
from videocaptioner.cli.commands import doctor


def test_voxgate_found_is_ok(monkeypatch):
    monkeypatch.setattr(voxgate_backend, "find_voxgate_binary", lambda configured="": "/usr/bin/voxgate")
    checks = doctor._check_live_caption({})
    assert len(checks) == 1
    assert checks[0].name == "live_caption.voxgate"
    assert checks[0].status == "ok"
    assert "/usr/bin/voxgate" in checks[0].message


def test_voxgate_missing_is_warn_not_error(monkeypatch):
    monkeypatch.setattr(voxgate_backend, "find_voxgate_binary", lambda configured="": None)
    checks = doctor._check_live_caption({})
    assert checks[0].name == "live_caption.voxgate"
    # 可选功能：缺失只 warn，不应让 doctor 整体退出码失败
    assert checks[0].status == "warn"
    assert checks[0].fix  # 给出修复指引（指定路径 / 放到 PATH）


def test_configured_binary_path_is_passed_through(monkeypatch):
    seen = {}

    def fake_find(configured=""):
        seen["configured"] = configured
        return configured or None

    monkeypatch.setattr(voxgate_backend, "find_voxgate_binary", fake_find)
    doctor._check_live_caption({"live_caption": {"voxgate_binary": "/opt/vox/voxgate"}})
    assert seen["configured"] == "/opt/vox/voxgate"


def test_fun_asr_with_key_is_ok():
    checks = doctor._check_live_caption(
        {"live_caption": {"provider": "fun-asr", "api_key": "sk-xxx"}}
    )
    assert checks[0].name == "live_caption.funasr"
    assert checks[0].status == "ok"


def test_fun_asr_without_key_is_warn():
    checks = doctor._check_live_caption({"live_caption": {"provider": "fun-asr"}})
    assert checks[0].name == "live_caption.funasr"
    assert checks[0].status == "warn"
    assert checks[0].fix


def test_wired_into_run_diagnostics(monkeypatch):
    monkeypatch.setattr(voxgate_backend, "find_voxgate_binary", lambda configured="": "/usr/bin/voxgate")
    names = [c.name for c in doctor.run_diagnostics({})]
    assert any(n.startswith("live_caption") for n in names)
