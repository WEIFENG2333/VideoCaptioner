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

    def test_process_final_output_uses_dotted_tag_grammar(self, tmp_path):
        """成品命名统一 {stem}.{tag}.{ext}，tag 按加工顺序组合。"""
        dub_and_sub = _resolve_final_output_path(
            None, tmp_path, tmp_path / "talk.mp4", True, False, False
        )
        assert dub_and_sub.endswith("talk.dubbed.subtitled.mp4")

        dub_only = _resolve_final_output_path(
            None, tmp_path, tmp_path / "talk.mp4", True, True, False
        )
        assert dub_only.endswith("talk.dubbed.mp4")

        subtitle_only = _resolve_final_output_path(
            None, tmp_path, tmp_path / "talk.mp4", False, False, False
        )
        assert subtitle_only.endswith("talk.subtitled.mp4")

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

    def test_edge_clone_fails_before_synthesis_without_api_key(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"not real audio")

        result = main([
            "dub",
            str(srt),
            "--preset",
            "edge-cn-female",
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

    def test_path_prints_active_config_file(self, capsys):
        # 契约：打印当前生效的配置路径（含 VIDEOCAPTIONER_CONFIG_FILE 覆盖，
        # 该 env 在 config_store 导入时固化，测试不假设具体取值）。
        from videocaptioner.core.application.config_store import CONFIG_FILE

        result = main(["config", "path"])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert str(CONFIG_FILE) in out

    def test_init_print_template(self, capsys):
        result = main(["config", "init", "--non-interactive", "--print-template", "--profile", "dubbing"])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "[dubbing]" in out
        assert "edge-cn-female" in out
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


class TestModelsParser:
    def test_models_list(self, capsys, tmp_path):
        result = main(["models", "list", "--models-dir", str(tmp_path)])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "whisper-cpp" in out
        assert "faster-whisper" in out
        assert "large-v3-turbo" in out

    def test_models_list_kind_filter(self, capsys, tmp_path):
        result = main(["models", "list", "--kind", "whisper-cpp", "--models-dir", str(tmp_path)])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "whisper-cpp" in out
        assert "large-v3-turbo" not in out

    def test_models_list_shows_installed(self, capsys, tmp_path):
        (tmp_path / "ggml-tiny.bin").write_bytes(b"x")
        result = main(["models", "list", "--models-dir", str(tmp_path)])
        assert result == EXIT.SUCCESS
        out = capsys.readouterr().out
        assert "✓ installed" in out

    def test_models_download_unknown_model(self, capsys, tmp_path):
        result = main(["models", "download", "whisper-cpp", "nope", "--models-dir", str(tmp_path)])
        assert result == EXIT.USAGE_ERROR

    def test_models_download_already_installed(self, capsys, tmp_path):
        (tmp_path / "ggml-tiny.bin").write_bytes(b"x")
        result = main(["models", "download", "whisper-cpp", "tiny", "--models-dir", str(tmp_path)])
        assert result == EXIT.SUCCESS

    def test_models_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["models", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "download" in out


class TestAsrChoicesDrift:
    """三处 --asr choices 必须与 CLI_ASR_MAPPING 完全一致（防手写清单漂移）。"""

    @staticmethod
    def _asr_choices(command: str, sub_action: str | None = None) -> list[str]:
        import argparse

        from videocaptioner.cli.main import build_parser

        parser = build_parser()
        subs = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        target = subs.choices[command]
        if sub_action is not None:
            inner = next(
                a for a in target._actions if isinstance(a, argparse._SubParsersAction)
            )
            target = inner.choices[sub_action]
        action = next(a for a in target._actions if "--asr" in a.option_strings)
        return list(action.choices)

    def test_all_asr_choices_match_canonical_mapping(self):
        from videocaptioner.core.application.app_config import CLI_ASR_MAPPING

        expected = list(CLI_ASR_MAPPING)
        assert self._asr_choices("transcribe") == expected
        assert self._asr_choices("process") == expected
        assert self._asr_choices("config", "init") == expected

    def test_faster_whisper_selectable_in_transcribe(self):
        assert "faster-whisper" in self._asr_choices("transcribe")

    def test_fun_asr_selectable_in_config_init(self):
        assert "fun-asr" in self._asr_choices("config", "init")
