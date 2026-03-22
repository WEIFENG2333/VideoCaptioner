"""subtitle command — optimize and/or translate subtitle files."""

import os
from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import get

# BCP 47 → TargetLanguage.value (Chinese label) mapping for internal use
_LANG_MAP = {
    "zh-Hans": "简体中文", "zh-Hant": "繁体中文",
    "en": "英语", "en-US": "英语(美国)", "en-GB": "英语(英国)",
    "ja": "日本語", "ko": "韩语", "yue": "粤语",
    "th": "泰语", "vi": "越南语", "id": "印尼语", "ms": "马来语", "tl": "菲律宾语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "es-419": "西班牙语(拉丁美洲)",
    "ru": "俄语", "pt": "葡萄牙语", "pt-BR": "葡萄牙语(巴西)", "pt-PT": "葡萄牙语(葡萄牙)",
    "it": "意大利语", "nl": "荷兰语", "pl": "波兰语", "tr": "土耳其语",
    "el": "希腊语", "cs": "捷克语", "sv": "瑞典语", "da": "丹麦语",
    "fi": "芬兰语", "nb": "挪威语", "hu": "匈牙利语", "ro": "罗马尼亚语",
    "bg": "保加利亚语", "uk": "乌克兰语", "ar": "阿拉伯语",
    "he": "希伯来语", "fa": "波斯语",
}


def _resolve_target_language(code: str):
    """Resolve a BCP 47 code to a TargetLanguage enum value."""
    from videocaptioner.core.translate.types import TargetLanguage

    label = _LANG_MAP.get(code)
    if label:
        for lang in TargetLanguage:
            if lang.value == label:
                return lang

    # Fallback: try direct match against enum values
    for lang in TargetLanguage:
        if lang.value == code or lang.name.lower() == code.lower():
            return lang

    output.error(f"Unknown target language: {code}")
    output.hint(f"Supported codes: {', '.join(_LANG_MAP.keys())}")
    return None


def run(args: Namespace, config: dict) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        output.error(f"Input file not found: {input_path}")
        return EXIT.FILE_NOT_FOUND

    need_optimize = get(config, "subtitle.optimize", True)
    need_translate = get(config, "subtitle.translate", False)
    need_split = get(config, "subtitle.split", True)

    # If user explicitly specified translator or target language, enable translation
    explicitly_wants_translate = getattr(args, "translator", None) or getattr(args, "target_language", None)
    explicitly_no_translate = getattr(args, "no_translate", False)
    if explicitly_wants_translate and explicitly_no_translate:
        output.warn("--no-translate conflicts with --translator/--target-language; translation will be skipped")
    elif explicitly_wants_translate:
        need_translate = True
    translator_service = get(config, "translate.service", "llm")

    # Validate AFTER resolving the actual need_translate / need_optimize state
    needs_llm = need_optimize or (need_translate and translator_service == "llm")
    if needs_llm:
        from videocaptioner.cli.validators import validate_llm
        if not validate_llm(config):
            return EXIT.USAGE_ERROR
    target_lang_code = get(config, "translate.target_language", "zh-Hans")
    need_reflect = get(config, "translate.reflect", False)
    thread_num = get(config, "subtitle.thread_num", 4)
    batch_size = get(config, "subtitle.batch_size", 10)
    max_cjk = get(config, "subtitle.max_word_count_cjk", 18)
    max_english = get(config, "subtitle.max_word_count_english", 12)
    out_fmt = get(config, "output.format", "srt")
    layout_str = get(config, "synthesize.layout", "target-above")
    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)

    # Build output path
    if args.output:
        out = Path(args.output)
        if out.is_dir() or str(args.output).endswith("/"):
            out.mkdir(parents=True, exist_ok=True)
            suffix = f"_{target_lang_code}" if need_translate else "_optimized"
            output_path = str(out / f"{input_path.stem}{suffix}.{out_fmt}")
        else:
            output_path = args.output
            if out_fmt != "srt":
                ext = out.suffix.lstrip(".")
                if ext and ext != out_fmt:
                    output.warn(f"--format {out_fmt} ignored; output format determined by -o extension (.{ext})")
    else:
        suffix = f"_{target_lang_code}" if need_translate else "_optimized"
        output_path = str(input_path.with_stem(input_path.stem + suffix).with_suffix(f".{out_fmt}"))

    # Setup LLM environment
    llm_api_key = get(config, "llm.api_key", "")
    llm_api_base = get(config, "llm.api_base", "")
    llm_model = get(config, "llm.model", "")
    if llm_api_key:
        os.environ["OPENAI_API_KEY"] = llm_api_key
    if llm_api_base:
        os.environ["OPENAI_BASE_URL"] = llm_api_base

    # Load custom prompt
    custom_prompt = getattr(args, "prompt", None) or ""
    prompt_file = getattr(args, "prompt_file", None)
    if prompt_file:
        custom_prompt = Path(prompt_file).read_text(encoding="utf-8")

    if quiet:
        import logging
        logging.getLogger().setLevel(logging.WARNING)

    if verbose:
        output.info(f"Optimize: {need_optimize}, Translate: {need_translate}")
        if need_translate:
            output.info(f"Translator: {translator_service}, Target: {target_lang_code}")
        if needs_llm and llm_model:
            output.info(f"LLM: {llm_model} @ {llm_api_base}")

    # Load subtitle data
    from videocaptioner.core.asr.asr_data import ASRData
    asr_data = ASRData.from_subtitle_file(str(input_path))

    if len(asr_data.segments) == 0:
        output.warn(f"Input file contains 0 subtitle segments: {input_path}")

    progress = None if quiet else output.ProgressLine("Processing subtitles").start()

    def callback(result):
        if progress:
            # Approximate progress from callback data
            progress.update(50, "Processing...")

    try:
        # 1. Split (if word-level timestamps available)
        if need_split and asr_data.is_word_timestamp():
            if progress:
                progress.update(5, "Splitting subtitles...")
            from videocaptioner.core.split.split import SubtitleSplitter
            splitter = SubtitleSplitter(
                thread_num=thread_num,
                model=llm_model,
                max_word_count_cjk=max_cjk,
                max_word_count_english=max_english,
            )
            asr_data = splitter.split_subtitle(asr_data)

        # 2. Optimize
        if need_optimize:
            if progress:
                progress.update(20, "Optimizing subtitles...")
            from videocaptioner.core.optimize.optimize import SubtitleOptimizer
            optimizer = SubtitleOptimizer(
                thread_num=thread_num,
                batch_num=batch_size,
                model=llm_model,
                custom_prompt=custom_prompt,
                update_callback=callback,
            )
            asr_data = optimizer.optimize_subtitle(asr_data)
            asr_data.remove_punctuation()

        # 3. Translate
        if need_translate:
            if progress:
                progress.update(60, f"Translating to {target_lang_code}...")

            target_language = _resolve_target_language(target_lang_code)
            if not target_language:
                if progress:
                    progress.finish()  # Clean spinner without duplicate error
                return EXIT.USAGE_ERROR

            from videocaptioner.core.translate.factory import TranslatorFactory
            from videocaptioner.core.translate.types import TranslatorType

            type_map = {"llm": TranslatorType.OPENAI, "bing": TranslatorType.BING, "google": TranslatorType.GOOGLE}
            translator = TranslatorFactory.create_translator(
                translator_type=type_map.get(translator_service, TranslatorType.OPENAI),
                thread_num=thread_num,
                batch_num=batch_size,
                target_language=target_language,
                model=llm_model,
                custom_prompt=custom_prompt,
                is_reflect=need_reflect,
                update_callback=callback,
            )
            asr_data = translator.translate_subtitle(asr_data)
            asr_data.remove_punctuation()

        # 4. Save
        from videocaptioner.core.entities import SubtitleLayoutEnum
        layout_map = {
            "target-above": SubtitleLayoutEnum.TRANSLATE_ON_TOP,
            "source-above": SubtitleLayoutEnum.ORIGINAL_ON_TOP,
            "target-only": SubtitleLayoutEnum.ONLY_TRANSLATE,
            "source-only": SubtitleLayoutEnum.ONLY_ORIGINAL,
        }
        layout = layout_map.get(layout_str, SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        asr_data.save(save_path=output_path, layout=layout)

        if progress:
            progress.finish(f"Done -> {output_path} ({len(asr_data.segments)} segments)")
        if quiet:
            print(output_path)
        return EXIT.SUCCESS

    except Exception as e:
        if progress:
            progress.fail(str(e))
        else:
            output.error(str(e))
        if verbose:
            import traceback
            traceback.print_exc()
        return EXIT.RUNTIME_ERROR
