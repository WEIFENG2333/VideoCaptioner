"""最近日志采集 + 脱敏。"""

from videocaptioner.core.feedback import logs as logs_mod
from videocaptioner.core.feedback.logs import collect_recent_logs, scrub_log_text


def test_scrub_redacts_secrets():
    raw = (
        'INFO request headers: Authorization: Bearer sk-abcDEF123456789\n'
        'DEBUG {"api_key": "sk-proj-zzzz9999", "model": "gpt-4o"}\n'
        'WARN url=https://user:p4ssw0rd@host.example.com/v1\n'
        'INFO api_base=https://api.openai.com/v1\n'
        '  API Base: https://api.siliconflow.cn/v1\n'
        'DEBUG {"base_url": "https://api.private.example/v1"}\n'
        'ERROR ...:generateContent?key=AIzaSyD_realsecret_abcdefghijklmnop123\n'
        'INFO google configured with AIzaSyD-EXAMPLErealkeyshapevalue1234567\n'
    )
    out = scrub_log_text(raw)
    assert "sk-abcDEF123456789" not in out
    assert "sk-proj-zzzz9999" not in out
    assert "p4ssw0rd" not in out
    assert "Bearer ***" in out
    assert "***" in out
    # base URL（含 provider/自建主机）一律打码
    assert "api.siliconflow.cn" not in out
    assert "api.openai.com" not in out
    assert "api.private.example" not in out
    # query ?key= 与裸 AIza Google key 打码
    assert "AIzaSyD_realsecret_abcdefghijklmnop123" not in out
    assert "AIzaSyD-EXAMPLErealkeyshapevalue1234567" not in out
    # 非敏感内容保留
    assert "gpt-4o" in out
    assert "host.example.com" in out  # url 凭据行只抹账密，保留主机


def test_collect_recent_logs_returns_scrubbed_tail(monkeypatch, tmp_path):
    log = tmp_path / "app.log"
    log.write_text("line1 Bearer sk-shouldberedacted0001\nline2 normal\n", encoding="utf-8")
    monkeypatch.setattr(logs_mod, "_LOG_FILE", log)
    items = collect_recent_logs()
    assert len(items) == 1
    att = items[0]
    assert att.filename == "recent.log" and att.mime == "text/plain"
    text = att.data.decode("utf-8")
    assert "sk-shouldberedacted0001" not in text
    assert "line2 normal" in text


def test_collect_recent_logs_tail_only(monkeypatch, tmp_path):
    log = tmp_path / "app.log"
    big = "\n".join(f"line-{i}" for i in range(200000))  # 远超 256KB
    log.write_text(big, encoding="utf-8")
    monkeypatch.setattr(logs_mod, "_LOG_FILE", log)
    att = collect_recent_logs()[0]
    assert len(att.data) <= logs_mod._MAX_TAIL_BYTES
    assert att.data.decode("utf-8").rstrip().endswith("line-199999")  # 取的是尾部


def test_collect_recent_logs_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(logs_mod, "_LOG_FILE", tmp_path / "nope.log")
    assert collect_recent_logs() == []
