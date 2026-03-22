"""Tests for CLI argument parsing — verify all commands parse correctly."""

import pytest

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli.main import main


class TestMainParser:
    def test_no_args_tries_gui_or_help(self, monkeypatch):
        # No args: tries to launch GUI, falls back to help
        # Mock GUI import to fail so it falls back to CLI help
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "videocaptioner.ui.main":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert main([]) == EXIT.USAGE_ERROR

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert "videocaptioner" in capsys.readouterr().out

    def test_invalid_subcommand(self):
        with pytest.raises(SystemExit) as exc:
            main(["nonexistent"])
        assert exc.value.code == 2

    def test_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "transcribe" in out
        assert "subtitle" in out
        assert "synthesize" in out
        assert "process" in out
        assert "download" in out
        assert "config" in out


class TestTranscribeParser:
    def test_missing_input(self):
        with pytest.raises(SystemExit) as exc:
            main(["transcribe"])
        assert exc.value.code == 2

    def test_invalid_asr(self):
        with pytest.raises(SystemExit) as exc:
            main(["transcribe", "test.mp4", "--asr", "invalid"])
        assert exc.value.code == 2

    def test_file_not_found(self):
        assert main(["transcribe", "/nonexistent/file.mp4"]) == EXIT.FILE_NOT_FOUND

    def test_verbose_quiet_mutually_exclusive(self):
        with pytest.raises(SystemExit) as exc:
            main(["transcribe", "test.mp4", "-v", "-q"])
        assert exc.value.code == 2


class TestSubtitleParser:
    def test_missing_input(self):
        with pytest.raises(SystemExit) as exc:
            main(["subtitle"])
        assert exc.value.code == 2

    def test_file_not_found(self):
        assert main(["subtitle", "/nonexistent/file.srt"]) == EXIT.FILE_NOT_FOUND

    def test_invalid_translator(self):
        with pytest.raises(SystemExit) as exc:
            main(["subtitle", "test.srt", "--translator", "invalid"])
        assert exc.value.code == 2

    def test_invalid_target_language(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        result = main(["subtitle", str(srt), "--translator", "bing", "--target-language", "xyz"])
        assert result == EXIT.USAGE_ERROR

    def test_invalid_format(self):
        with pytest.raises(SystemExit) as exc:
            main(["subtitle", "test.srt", "--format", "vtt"])
        assert exc.value.code == 2


class TestSynthesizeParser:
    def test_missing_subtitle_flag(self):
        with pytest.raises(SystemExit) as exc:
            main(["synthesize", "video.mp4"])
        assert exc.value.code == 2

    def test_file_not_found(self):
        assert main(["synthesize", "/no/video.mp4", "-s", "/no/sub.srt"]) == EXIT.FILE_NOT_FOUND


class TestConfigParser:
    def test_no_action(self):
        assert main(["config"]) == EXIT.USAGE_ERROR

    def test_set_unknown_key(self):
        assert main(["config", "set", "garbage.key", "value"]) == EXIT.GENERAL_ERROR

    def test_set_section_key(self):
        assert main(["config", "set", "subtitle", "bad"]) == EXIT.GENERAL_ERROR

    def test_set_invalid_int(self):
        assert main(["config", "set", "subtitle.thread_num", "abc"]) == EXIT.GENERAL_ERROR

    def test_set_invalid_bool(self):
        assert main(["config", "set", "subtitle.optimize", "maybe"]) == EXIT.GENERAL_ERROR

    def test_get_unknown_key(self):
        assert main(["config", "get", "nonexistent.key"]) == EXIT.GENERAL_ERROR

    def test_show(self, capsys):
        result = main(["config", "show"])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "llm:" in out
        assert "api_key" in out

    def test_path(self, capsys):
        result = main(["config", "path"])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "config.toml" in out
