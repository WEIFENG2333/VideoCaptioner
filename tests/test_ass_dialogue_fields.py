import pytest

from videocaptioner.core.subtitle import ass_utils


@pytest.mark.parametrize("text", ["中文样式", "0", "hello, world", ""])
def test_wrapping_only_changes_dialogue_text(tmp_path, monkeypatch, text):
    source = tmp_path / "input.ass"
    destination = tmp_path / "output.ass"
    prefix = "Dialogue: 0,0:00:00.00,0:00:01.00,中文样式,中文样式,0,0,0,,"
    source.write_text("[Events]\n" + prefix + text + "\n", encoding="utf-8")
    wrapped = "wrapped" if text else ""
    monkeypatch.setattr(ass_utils, "wrap_ass_text", lambda *args: wrapped)

    ass_utils.auto_wrap_ass_file(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "[Events]\n" + prefix + wrapped + "\n"
