"""字幕优化的忠实度校验与逐行重试的单元测试（无需 LLM）。

覆盖 optimize.py 的两处关键行为：
1. `_line_is_valid` 区分"忠实删减"（口语填充词/口吃，应放行）与"改写/幻觉"
   （引入大量原文没有的新内容，应拦截）。
2. `agent_loop` 只对未通过的行发起反馈重试，已通过的行锁定不再重发。
"""

import pytest

from videocaptioner.core.optimize.optimize import SubtitleOptimizer


@pytest.fixture
def optimizer():
    opt = SubtitleOptimizer(thread_num=1, batch_num=5, model="mock", custom_prompt="")
    yield opt
    opt.stop()


class TestLineIsValid:
    def test_minor_edit_passes(self, optimizer):
        ok, _ = optimizer._line_is_valid(
            "we came up with this thing called tool calling",
            "We came up with this thing called tool calling.",
        )
        assert ok

    def test_filler_removal_passes(self, optimizer):
        # 大量删除填充词/口吃：字符相似度低，但优化结果⊆原文 → 放行
        ok, _ = optimizer._line_is_valid(
            "From a so, it's like, I mean, it's like they're separate developers, right?",
            "They're separate developers, right?",
        )
        assert ok

    def test_stutter_dedup_passes(self, optimizer):
        ok, _ = optimizer._line_is_valid(
            "How many people would say that your regular workflow uses more than, "
            "well, let's say how many people would say your regular workflow uses "
            "more than one cloud at a time?",
            "How many people would say that your regular workflow uses more than "
            "one cloud at a time?",
        )
        assert ok

    def test_sentence_head_deletion_passes(self, optimizer):
        # 句首删词 + 句中删填充词：字符级会碎片化误判为"新增"，词级应放行
        ok, _ = optimizer._line_is_valid(
            "So, and for me at least, having an agent with a persistent name and a "
            "persistent memory, it kind of manages its own like scratch files within "
            "its own branch of the work tree.",
            "And for me at least, having an agent with a persistent name and a "
            "persistent memory, it manages its own scratch files within its own "
            "branch of the work tree.",
        )
        assert ok

    def test_rewrite_with_new_content_fails(self, optimizer):
        # 引入大量原文没有的新内容（改写/幻觉）→ 拦截
        ok, reason = optimizer._line_is_valid(
            "the model could go get the output and make a decision",
            "人工智能系统会自动获取结果并做出复杂的综合判断和推理分析",
        )
        assert not ok
        assert "new content" in reason

    def test_translation_fails(self, optimizer):
        # 违反"不要翻译"约束：整行换成另一种语言 → 拦截
        ok, _ = optimizer._line_is_valid(
            "Hey, how's everyone doing today?",
            "嘿，大家今天怎么样？",
        )
        assert not ok

    def test_empty_optimization_fails(self, optimizer):
        ok, _ = optimizer._line_is_valid("having a good conference so far", "")
        assert not ok


class TestAgentLoopPerLineRetry:
    def test_retries_only_failed_lines(self, optimizer, monkeypatch):
        chunk = {
            "1": "we came up with this thing called tool calling",
            "2": "so, and for me, it's like, having an agent, right",
            "3": "the model could go get the output and make a decision",
        }
        calls = []

        def fake_request(pending, retry=False):
            calls.append(dict(pending))
            if not retry:
                return {
                    "1": "We came up with this thing called tool calling.",
                    "2": "For me, having an agent, right?",  # 删减，放行
                    "3": "人工智能会自动完成所有复杂任务并进行推理",  # 幻觉，拦截
                }
            # 重试请求只应包含未通过的行
            return {
                key: "The model could get the output and make a decision."
                for key in pending
            }

        monkeypatch.setattr(optimizer, "_request_optimization", fake_request)

        result = optimizer.agent_loop(chunk)

        assert len(result) == 3
        # 第一次收到全部 3 行；重试只收到失败的第 3 行
        assert set(calls[0].keys()) == {"1", "2", "3"}
        assert set(calls[1].keys()) == {"3"}

    def test_no_retry_when_all_valid(self, optimizer, monkeypatch):
        chunk = {
            "1": "hello world this is a fine sentence",
            "2": "another perfectly good line right here",
        }
        calls = []

        def fake_request(pending, retry=False):
            _ = retry
            calls.append(dict(pending))
            return dict(pending)  # 原样回显 → 相似度 1.0 → 全部通过

        monkeypatch.setattr(optimizer, "_request_optimization", fake_request)

        result = optimizer.agent_loop(chunk)

        assert len(calls) == 1  # 无重试
        assert len(result) == 2
