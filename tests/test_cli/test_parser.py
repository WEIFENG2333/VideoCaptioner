"""Tests for CLI argument parsing — verify all commands parse correctly."""

import pytest

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli.commands.process import _resolve_final_output_path
from videocaptioner.cli.main import main


class TestMainParser:
    def test_no_args_tries_gui(self, monkeypatch):
        # No args: tries to launch GUI. Mock GUI import to avoid opening it in tests.
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "videocaptioner.ui.main":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert main([]) == EXIT.DEPENDENCY_MISSING

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
        assert "gui" in out
        assert "subtitle" in out
        assert "synthesize" in out
        assert "process" in out
        assert "download" in out
        assert "config" in out
        assert "doctor" in out

    def test_gui_command_reports_missing_gui_dependencies(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "videocaptioner.ui.main":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert main(["gui"]) == EXIT.DEPENDENCY_MISSING


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


class TestProcessParser:
    def test_dub_options_parse_with_missing_input(self):
        result = main([
            "process",
            "/no/video.mp4",
            "--dub-only",
            "--dub-provider",
            "siliconflow",
            "--dub-preset",
            "siliconflow-cn-female",
            "--tts-model",
            "FunAudioLLM/CosyVoice2-0.5B",
            "--voice",
            "FunAudioLLM/CosyVoice2-0.5B:anna",
        ])
        assert result == EXIT.FILE_NOT_FOUND

    def test_process_dub_final_output_defaults_to_dubbed_captioned(self, tmp_path):
        result = _resolve_final_output_path(None, tmp_path, tmp_path / "talk.mp4", True, False, False)

        assert result.endswith("talk_dubbed_captioned.mp4")

    def test_process_dub_only_uses_user_output_file(self, tmp_path):
        result = _resolve_final_output_path(str(tmp_path / "final.mp4"), tmp_path, tmp_path / "talk.mp4", True, True, False)

        assert result.endswith("final.mp4")

    def test_process_help_hides_advanced_dubbing_options(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["process", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--preset" in out
        assert "--timing" in out
        assert "--audio-mode" in out
        assert "--style-prompt" not in out
        assert "--tts-api-base" not in out


class TestDubParser:
    def test_missing_subtitle(self):
        with pytest.raises(SystemExit) as exc:
            main(["dub"])
        assert exc.value.code == 2

    def test_file_not_found(self):
        assert main(["dub", "/no/sub.srt"]) == EXIT.FILE_NOT_FOUND

    def test_help_hides_provider_details(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["dub", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--preset" in out
        assert "--speak" in out
        assert "--adapt-length" in out
        assert "--style-prompt" not in out
        assert "--tts-model" not in out
        assert "--dub-preset" not in out

    def test_gemini_clone_fails_before_synthesis(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"not real audio")

        result = main([
            "dub",
            str(srt),
            "--preset",
            "gemini-en-friendly",
            "--tts-api-key",
            "test-key",
            "--clone-audio",
            str(ref),
            "--clone-text",
            "Hello",
        ])

        assert result == EXIT.USAGE_ERROR


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

    def test_init_print_template(self, capsys):
        result = main(["config", "init", "--non-interactive", "--print-template", "--profile", "dubbing"])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "[dubbing]" in out
        assert "siliconflow-cn-female" in out
        assert "audio_mode" in out


class TestDoctorParser:
    def test_doctor_json(self, capsys):
        result = main(["doctor", "--json"])
        assert result in {EXIT.SUCCESS, EXIT.DEPENDENCY_MISSING}
        out = capsys.readouterr().out
        assert '"checks"' in out

    def test_doctor_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["doctor", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--json" in out
        assert "--check-api" in out
