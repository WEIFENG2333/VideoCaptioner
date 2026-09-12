"""VoxgateBackend 原生 protocol 解析契约（离线，直接喂 _dispatch）。

锁住新协议（实测取证 docs/dev/voxgate-protocol.md）：每条 result 自带 index（句号）= 稳定
seg_id；text 是该句从头累积的全文；**定稿信号是 is_vad_finished（真·停顿）**，is_force_finished
是同句 twopass 二次冲刷、其后同 index 仍生长，绝不据它定稿；VAD 收尾帧带的 text:"" 空占位跳过；
末句没等到自己的 VAD 交装配器 close() 兜底。
"""

from videocaptioner.core.realtime.backends.voxgate import VoxgateBackend


def _msg(results, **kw):
    return {"direction": "recv", "status_code": 20000000,
            "result_json": {"results": results}, **kw}


def _r(text, index, start, end, interim=True, vad=False, force=False):
    d = {"index": index, "start_time": start, "end_time": end,
         "text": text, "is_interim": interim}
    if vad:
        d["is_vad_finished"] = True
    if force:
        d["is_force_finished"] = True
    return d


def _backend():
    segs = []
    be = VoxgateBackend(binary="x")  # 构造不 spawn，仅 start() 才起子进程
    be.on_segment = segs.append
    return be, segs


def _finals(segs):
    return [s for s in segs if s.is_final]


def test_index_is_seg_id_and_vad_finalizes():
    be, segs = _backend()
    be._dispatch(_msg([_r("你好", 0, 1.88, 3.2)]))                              # 生长（活动）
    be._dispatch(_msg([_r("你好今天天气", 0, 1.88, 5.1, interim=False, vad=True)]))  # 真停顿定稿
    f = _finals(segs)
    assert f and f[-1].seg_id == "voxgate#0" and f[-1].text == "你好今天天气"
    assert f[-1].start_time == 1.88 and f[-1].end_time == 5.1


def test_force_finished_does_not_finalize():
    # is_force_finished（twopass 冲刷）其后同 index 继续长出英文 → 绝不能据它提前定稿。
    be, segs = _backend()
    be._dispatch(_msg([_r("你好今天的天气", 0, 1.88, 8.34)]))                       # 生长
    be._dispatch(_msg([_r("你好今天的天气非常的不错", 0, 1.88, 10.26,
                          interim=False, force=True)]))                          # 二次冲刷（非定稿）
    assert _finals(segs) == []                                                   # 还没真停顿
    be._dispatch(_msg([_r("你好今天的天气非常的不错。i think the weather is nice。",
                          0, 1.88, 14.69, interim=False, vad=True)]))            # 真 VAD 定稿
    f = _finals(segs)
    assert len(f) == 1 and f[-1].seg_id == "voxgate#0"
    assert f[-1].text.endswith("nice。")


def test_second_index_distinct_seg():
    be, segs = _backend()
    be._dispatch(_msg([_r("第一句。", 0, 1.88, 14.69, interim=False, vad=True)]))
    be._dispatch(_msg([_r("还有一点", 1, 19.76, 21.1)]))
    be._dispatch(_msg([_r("还有一点就是这样。", 1, 19.76, 31.26, interim=False, vad=True)]))
    assert {s.seg_id for s in _finals(segs)} == {"voxgate#0", "voxgate#1"}


def test_vad_frame_empty_placeholder_skipped():
    # VAD 收尾帧除了本句还会多带一条 text:"" 的下一句占位 → 跳过空文本，不多出一段。
    be, segs = _backend()
    be._dispatch(_msg([
        _r("整句。", 1, 19.76, 31.26, interim=False, vad=True),
        _r("", 1, -0.001, -0.001, interim=False),
    ]))
    f = _finals(segs)
    assert len(f) == 1 and f[-1].text == "整句。"


def test_growing_interim_upserts_same_seg():
    be, segs = _backend()
    be._dispatch(_msg([_r("我", 0, 1.88, 2.0)]))
    be._dispatch(_msg([_r("我觉得今天", 0, 1.88, 3.0)]))
    assert all(s.seg_id == "voxgate#0" for s in segs)
    assert not any(s.is_final for s in segs)
    assert segs[-1].text == "我觉得今天"


def test_error_status_forwards():
    errs = []
    be = VoxgateBackend(binary="x")
    be.on_error = errs.append
    be._dispatch({"direction": "recv", "status_code": 45000001, "status_message": "bad key"})
    assert errs and "45000001" in errs[0]


def test_heartbeat_and_send_ignored():
    be, segs = _backend()
    be._dispatch({"direction": "recv", "status_code": 20000000, "result_json": {"results": None}})
    be._dispatch({"direction": "send", "method_name": "StartTask"})
    assert segs == []


def test_rolling_reset_splits_continuous_speech():
    # 连续语音（看视频/会议）：豆包同 index、无 VAD，到上限把 text 截短重来（骤降到很短）。
    # 须当句边界切句，否则整场被覆盖成最后残段（真实 118s 会话曾只剩 1 句）。
    be, segs = _backend()
    long_text = "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸"  # 20 字
    be._dispatch(_msg([_r("一二三四五六七八", 0, 0, 5)]))
    be._dispatch(_msg([_r(long_text, 0, 0, 6)]))            # 同句生长到 20 字
    be._dispatch(_msg([_r("完全重来了", 0, 6, 9)]))          # 5 字，腰斩(5*2<20)=滚动重置
    f = _finals(segs)
    assert any(s.text == long_text for s in f)              # 重置处定稿上一段（不丢）
    assert len({s.seg_id for s in segs}) >= 2
    assert any(s.text == "完全重来了" for s in segs)         # 新句不覆盖旧句


def test_twopass_rewrite_does_not_false_split():
    # twopass 改写（去口水词/补标点）前缀大体不变、长度相近 → 不得误判成重置而切句。
    be, segs = _backend()
    be._dispatch(_msg([_r("今天天气不错呃", 0, 0, 5)]))
    be._dispatch(_msg([_r("今天天气不错。", 0, 0, 5, force=True)]))  # 同长度小改写
    be._dispatch(_msg([_r("今天天气不错，挺好。", 0, 0, 6, vad=True)]))
    assert {s.seg_id for s in segs} == {"voxgate#0"}  # 始终同一句
    f = _finals(segs)
    assert f and f[-1].text == "今天天气不错，挺好。"


def test_twopass_shorter_rewrite_no_false_split():
    # twopass 改写让文本「略变短 + 前半句改写」（whose fault→who spots），长度不腰斩 →
    # 绝不能误判成滚动重置切句（线上「开头 3 句重复」真因，实测 dump 45→43→…）。
    be, segs = _backend()
    be._dispatch(_msg([_r("Okay. Well, whose fault is that? Yours. What?", 0, 0, 5)]))   # 45
    be._dispatch(_msg([_r("Okay. Well, who spots? Is that yours? What?", 0, 0, 5)]))    # 43 略短+前缀改
    be._dispatch(_msg([_r("Okay. Well, whose fault is that? Yours. What? Let me.", 0, 0, 6)]))  # 续长
    assert {s.seg_id for s in segs} == {"voxgate#0"}  # 始终同一句，不切
    assert _finals(segs) == []  # 无 vad/边界，全程在途（末句交 close 兜底）
