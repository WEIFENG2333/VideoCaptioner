from videocaptioner.core.dubbing.subtitle_parser import split_speaker


def test_split_speaker_bracket_format():
    speaker, text = split_speaker("[Alice] Hello there")

    assert speaker == "Alice"
    assert text == "Hello there"


def test_split_speaker_chinese_bracket_format():
    speaker, text = split_speaker("【小明】你好，今天开始测试。")

    assert speaker == "小明"
    assert text == "你好，今天开始测试。"


def test_split_speaker_colon_format():
    speaker, text = split_speaker("Bob: This is a line.")

    assert speaker == "Bob"
    assert text == "This is a line."


def test_split_speaker_default():
    speaker, text = split_speaker("No explicit speaker")

    assert speaker == "default"
    assert text == "No explicit speaker"
