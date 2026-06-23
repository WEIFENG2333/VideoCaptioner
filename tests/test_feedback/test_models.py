"""反馈本地校验：限制对齐后端契约。"""

import pytest

from videocaptioner.core.feedback.models import (
    MAX_FILE_BYTES,
    FeedbackAttachment,
    FeedbackReport,
    FeedbackValidationError,
)


def _png(size: int = 10) -> FeedbackAttachment:
    return FeedbackAttachment(filename="s.png", data=b"x" * size, mime="image/png")


def test_valid_report_passes():
    FeedbackReport(category="bug", message="导出报错").validate()


def test_empty_message_rejected():
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="   ").validate()
    assert e.value.code == "message_required"


def test_message_too_long():
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="x" * 5001).validate()
    assert e.value.code == "message_too_long"


def test_bad_category():
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="nope", message="hi").validate()
    assert e.value.code == "category_invalid"


def test_contact_too_long_counts_bytes():
    # 200 字节上限：用多字节中文确保按字节而非字符判断
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="hi", contact="中" * 80).validate()
    assert e.value.code == "contact_too_long"


def test_too_many_files():
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="hi", attachments=[_png() for _ in range(4)]).validate()
    assert e.value.code == "too_many_files"


def test_bad_file_type():
    bad = FeedbackAttachment(filename="a.gif", data=b"x", mime="image/gif")
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="hi", attachments=[bad]).validate()
    assert e.value.code == "file_type"


def test_file_too_large():
    big = FeedbackAttachment(filename="a.png", data=b"x" * (MAX_FILE_BYTES + 1), mime="image/png")
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="hi", attachments=[big]).validate()
    assert e.value.code == "file_too_large"


def test_total_too_large():
    # 3 张各 5MB = 15MB > 12MB 总上限
    files = [FeedbackAttachment(f"{i}.png", b"x" * MAX_FILE_BYTES, "image/png") for i in range(3)]
    with pytest.raises(FeedbackValidationError) as e:
        FeedbackReport(category="bug", message="hi", attachments=files).validate()
    assert e.value.code == "total_too_large"
