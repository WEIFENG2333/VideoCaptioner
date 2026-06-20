"""output_paths 是全项目文件命名的唯一事实源，这里把语法钉死。

任何想改输出命名的人都必须先改这份测试——这正是设计意图。
"""


import pytest

from videocaptioner.core.application import output_paths as op
from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.translate.types import TargetLanguage


class TestProductPath:
    def test_subtitle_product_uses_dotted_language_tag(self, tmp_path):
        src = tmp_path / "video.mp4"
        assert op.product_path(src, "zh-Hans", ext=".srt") == tmp_path / "video.zh-Hans.srt"

    def test_optimized_subtitle(self, tmp_path):
        src = tmp_path / "video.srt"
        assert op.product_path(src, op.TAG_OPTIMIZED, ext=".srt") == tmp_path / "video.optimized.srt"

    def test_subtitled_video_keeps_source_suffix(self, tmp_path):
        src = tmp_path / "video.mkv"
        assert op.product_path(src, op.TAG_SUBTITLED) == tmp_path / "video.subtitled.mkv"

    def test_dubbed_audio_and_video_share_one_tag(self, tmp_path):
        src = tmp_path / "video.mp4"
        assert op.product_path(src, op.TAG_DUBBED) == tmp_path / "video.dubbed.mp4"
        assert op.product_path(src, op.TAG_DUBBED, ext=".wav") == tmp_path / "video.dubbed.wav"

    def test_tags_compose_in_processing_order(self, tmp_path):
        src = tmp_path / "video.mp4"
        assert (
            op.product_path(src, op.TAG_DUBBED, op.TAG_SUBTITLED)
            == tmp_path / "video.dubbed.subtitled.mp4"
        )

    def test_existing_tags_are_stripped_before_appending(self, tmp_path):
        translated = tmp_path / "video.zh-Hans.srt"
        assert op.product_path(translated, "en", ext=".srt") == tmp_path / "video.en.srt"
        dubbed_from_subtitle = tmp_path / "video.zh-Hans.srt"
        assert (
            op.product_path(dubbed_from_subtitle, op.TAG_DUBBED, ext=".wav")
            == tmp_path / "video.dubbed.wav"
        )

    def test_dots_in_real_names_are_not_tags(self, tmp_path):
        src = tmp_path / "my.holiday.video.mp4"
        assert (
            op.product_path(src, op.TAG_SUBTITLED)
            == tmp_path / "my.holiday.video.subtitled.mp4"
        )

    def test_directory_override(self, tmp_path):
        src = tmp_path / "a" / "video.mp4"
        out = tmp_path / "b"
        assert op.product_path(src, op.TAG_SUBTITLED, directory=out) == out / "video.subtitled.mp4"

    def test_unknown_tag_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            op.product_path(tmp_path / "video.mp4", "captioned")


class TestLanguageTag:
    def test_common_codes(self):
        assert op.language_tag(TargetLanguage.SIMPLIFIED_CHINESE) == "zh-Hans"
        assert op.language_tag(TargetLanguage.ENGLISH) == "en"
        assert op.language_tag(TargetLanguage.JAPANESE) == "ja"

    def test_every_target_language_has_a_tag(self):
        # 新增 TargetLanguage 成员时必须同步补 BING_LANG_MAP，否则文件名无码可用。
        for language in TargetLanguage:
            tag = op.language_tag(language)
            assert tag and "/" not in tag and "\\" not in tag


class TestUniquePath:
    def test_free_path_returned_as_is(self, tmp_path):
        target = tmp_path / "video.dubbed.mp4"
        assert op.unique_path(target) == target

    def test_increments_like_os_convention(self, tmp_path):
        target = tmp_path / "video.dubbed.mp4"
        target.write_bytes(b"")
        assert op.unique_path(target) == tmp_path / "video.dubbed (2).mp4"
        (tmp_path / "video.dubbed (2).mp4").write_bytes(b"")
        assert op.unique_path(target) == tmp_path / "video.dubbed (3).mp4"


class TestTaskDir:
    def test_layout_and_uniqueness(self, tmp_path):
        first = op.new_task_dir(tmp_path, "/somewhere/视频 demo.mp4", op.TASK_TRANSCRIBE)
        assert first.is_dir()
        assert first.parent == tmp_path / "transcribe"  # 按功能归类到 {work_dir}/{task_type}/
        assert first.name.endswith("-视频 demo")
        second = op.new_task_dir(tmp_path, "/somewhere/视频 demo.mp4", op.TASK_TRANSCRIBE)
        assert second != first and second.is_dir()

    def test_task_type_routes_to_subdir(self, tmp_path):
        for tt in (op.TASK_TRANSCRIBE, op.TASK_SYNTHESIS, op.TASK_BATCH, op.TASK_DUBBING):
            assert op.new_task_dir(tmp_path, "v.mp4", tt).parent == tmp_path / tt

    def test_unknown_task_type_rejected(self, tmp_path):
        import pytest
        with pytest.raises(ValueError):
            op.new_task_dir(tmp_path, "v.mp4", "bogus")

    def test_hostile_stem_sanitized(self, tmp_path):
        created = op.new_task_dir(tmp_path, 'a/b<>:"|?*.mp4', op.TASK_TRANSCRIBE)
        assert created.is_dir()

    def test_cleanup_removes_only_task_dirs(self, tmp_path):
        task = op.new_task_dir(tmp_path, "video.mp4", op.TASK_BATCH)
        (task / "transcript.srt").write_text("1", encoding="utf-8")
        op.cleanup_task_dir(task, keep=True)
        assert task.exists()
        op.cleanup_task_dir(task, keep=False)
        assert not task.exists()

    def test_cleanup_refuses_non_task_dirs(self, tmp_path):
        # 父目录名不是已知 task_type → 绝不删（防 rmtree 误删到用户目录）
        outsider = tmp_path / "precious"
        outsider.mkdir()
        op.cleanup_task_dir(outsider, keep=False)
        assert outsider.exists()
        nested = tmp_path / "notatype" / "20260101-000000-x"
        nested.mkdir(parents=True)
        op.cleanup_task_dir(nested, keep=False)
        assert nested.exists()

    def test_cleanup_tolerates_none_and_missing(self, tmp_path):
        op.cleanup_task_dir(None, keep=False)
        op.cleanup_task_dir(tmp_path / "transcribe" / "gone", keep=False)


class TestHelpers:
    def test_layout_copy_names(self):
        assert op.layout_copy_name(SubtitleLayoutEnum.TRANSLATE_ON_TOP) == "layout-target-above.srt"
        assert op.layout_copy_name(SubtitleLayoutEnum.ONLY_ORIGINAL) == "layout-source-only.srt"

    def test_downloads_dir_created(self, tmp_path):
        target = op.downloads_dir(tmp_path)
        assert target == tmp_path / "downloads" and target.is_dir()

    def test_strip_tags_only_touches_known_vocabulary(self):
        assert op.strip_tags("video.zh-Hans") == "video"
        assert op.strip_tags("video.dubbed.subtitled") == "video"
        assert op.strip_tags("my.holiday.video") == "my.holiday.video"
