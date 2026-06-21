#!/usr/bin/env python3
"""VideoCaptioner UI 国际化工具链（key-based gettext）。

源串是 key（``tr("dubbing.btn.start")``），基准语言 zh_Hans 的 msgstr 存中文，
是 key→中文 的唯一真相源；en / zh_Hant 从它翻译。运行时只用标准库 gettext 读 .mo。

子命令：
    extract              扫描源码 tr()/N_() → resource/i18n/videocaptioner.pot
    update               .pot → 各语言 .po（缺则 init，存则 merge 保留已译）
    fill-base <map.json> 用 {key: 中文} 填 zh_Hans.po 的空 msgstr（初次批量导入）
    translate [lang...]  用 LLM 把 zh_Hans 中文译进 en/zh_Hant 的空 msgstr（需 OPENAI_API_KEY）
    compile              各语言 .po → .mo
    check                CI 门禁：源码 key 集 == .pot；zh_Hans 无空 msgstr
    sync <map.json>      extract→update→fill-base→translate→compile 全流程

用法：
    python scripts/i18n.py extract
    python scripts/i18n.py sync /tmp/i18n-base.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from babel.messages.pofile import read_po, write_po
from openai import OpenAI
from pydantic import BaseModel

from videocaptioner.ui.common.config import source_language_i18n_map
from videocaptioner.ui.common.dubbing_options import i18n_base_map as dubbing_i18n_map
from videocaptioner.ui.common.enum_labels import enum_base_map

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "resource" / "i18n"
POT = I18N_DIR / "videocaptioner.pot"
BABEL_CFG = ROOT / "babel.cfg"
DOMAIN = "videocaptioner"
BASE = "zh_Hans"
LANGS = ["zh_Hans", "zh_Hant", "en"]
# LLM 目标语言名（zh_Hans 是基准，不在此）。
TARGET_NAME = {"en": "English", "zh_Hant": "Traditional Chinese (Hong Kong)"}

PRESERVE_TERMS = [
    "ASR", "LLM", "TTS", "FFmpeg", "Whisper", "OpenAI", "GPU", "CPU",
    "VAD", "OCR", "API", "Key", "URL", "SRT", "ASS", "Edge", "Gemini",
    "SiliconFlow", "CosyVoice", "voxgate", "Fun-ASR", "RapidOCR",
]


class _TransItem(BaseModel):
    index: int
    translation: str


class _TransBatch(BaseModel):
    items: list[_TransItem]


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _runtime_keys() -> dict[str, str]:
    """运行时动态拼接、pybabel 抽不到的 key→基准中文（枚举标签 + 配音 + 识别语言）。"""
    keys = dict(enum_base_map())
    keys.update(dubbing_i18n_map())
    keys.update(source_language_i18n_map())
    return keys


def _po_path(lang: str) -> Path:
    return I18N_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.po"


def _pybabel(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "babel.messages.frontend", *args], check=True, cwd=ROOT)


# ---------------------------------------------------------------- extract / update / compile
def extract(out: Path = POT) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _pybabel(
        "extract", "-F", str(BABEL_CFG), "-k", "tr", "-k", "N_",
        "--no-location", "--sort-output", "--omit-header",
        "-o", str(out), "videocaptioner",
    )
    # 动态拼接 key（枚举/配音/识别语言）pybabel 抽不到 → 在此补进 .pot。
    with out.open("rb") as f:
        cat = read_po(f)
    have = {m.id for m in cat if m.id}
    added = 0
    for key in _runtime_keys():
        if key not in have:
            cat.add(key)
            added += 1
    with out.open("wb") as f:
        write_po(f, cat, omit_header=True, sort_output=True)
    print(f"✓ extract → {_rel(out)}（+{added} 运行时 key）")


def update() -> None:
    for lang in LANGS:
        po = _po_path(lang)
        po.parent.mkdir(parents=True, exist_ok=True)
        if po.exists():
            _pybabel(
                "update", "-i", str(POT), "-o", str(po), "-l", lang,
                "--no-fuzzy-matching", "--ignore-obsolete",
            )
        else:
            _pybabel("init", "-i", str(POT), "-o", str(po), "-l", lang)
        print(f"✓ update → {_rel(po)}")


def compile_() -> None:
    for lang in LANGS:
        po = _po_path(lang)
        if not po.exists():
            print(f"⚠ skip compile (no po): {lang}")
            continue
        _pybabel("compile", "-i", str(po), "-o", str(po.with_suffix(".mo")), "-l", lang)
        print(f"✓ compile → {_rel(po.with_suffix('.mo'))}")


# ---------------------------------------------------------------- fill-base
def fill_base(mapping_path: Path) -> None:
    mapping = dict(_runtime_keys())  # 运行时动态 key（枚举/配音/语言）基准中文自动并入
    mapping.update(json.loads(Path(mapping_path).read_text(encoding="utf-8")))
    po = _po_path(BASE)
    with po.open("rb") as f:
        catalog = read_po(f)
    filled = missing = 0
    for msg in catalog:
        if not msg.id:
            continue
        zh = mapping.get(msg.id)
        if zh is None:
            missing += 1
            continue
        if msg.string != zh:
            msg.string = zh
            filled += 1
    extra = [k for k in mapping if k not in {m.id for m in catalog if m.id}]
    with po.open("wb") as f:
        write_po(f, catalog, sort_output=True)
    print(f"✓ fill-base: 写入 {filled} 条；.pot 中无中文映射 {missing} 条；映射里多余 {len(extra)} 条")
    if extra:
        print("  多余 key（不在源码里）:", ", ".join(extra[:20]) + (" …" if len(extra) > 20 else ""))


# ---------------------------------------------------------------- translate (LLM)
# 翻译端点由环境变量配置（默认 OpenAI；用 SiliconFlow 等兼容端点时覆盖三者）：
#   VC_TRANSLATE_API_KEY（缺省回退 OPENAI_API_KEY） / VC_TRANSLATE_BASE_URL / VC_TRANSLATE_MODEL
#   VC_TRANSLATE_WORKERS（并发批数，默认 8）
def translate(langs: list[str]) -> None:
    base_map = _base_map()
    for lang in langs:
        name = TARGET_NAME.get(lang)
        if not name:
            print(f"⚠ 跳过 {lang}（非 LLM 目标）")
            continue
        po = _po_path(lang)
        with po.open("rb") as f:
            catalog = read_po(f)
        todo = [(m.id, base_map.get(m.id, m.id)) for m in catalog if m.id and not m.string]
        if not todo:
            print(f"✓ {lang}: 无空译文")
            continue
        print(f"… {lang}: 翻译 {len(todo)} 条")
        result = _llm_translate([t[1] for t in todo], name)
        by_id = {tid: text for (tid, _), text in zip(todo, result) if text}
        for m in catalog:
            if m.id in by_id:
                m.string = by_id[m.id]
        with po.open("wb") as f:
            write_po(f, catalog, sort_output=True)
        miss = len(todo) - len(by_id)
        print(f"✓ {lang}: 写入 {len(by_id)} 条" + (f"（{miss} 条未译）" if miss else "") + f" → {_rel(po)}")


def _base_map() -> dict[str, str]:
    with _po_path(BASE).open("rb") as f:
        catalog = read_po(f)
    return {m.id: m.string for m in catalog if m.id and m.string}


def _translate_client() -> tuple[OpenAI, str]:
    key = os.environ.get("VC_TRANSLATE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("translate 需要 VC_TRANSLATE_API_KEY（或 OPENAI_API_KEY）")
    base = os.environ.get("VC_TRANSLATE_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("VC_TRANSLATE_MODEL", "gpt-5")
    return OpenAI(api_key=key, base_url=base), model


def _translate_batch(
    client: OpenAI, model: str, target_name: str, indexed: list[tuple[int, str]]
) -> dict[int, str]:
    """一批 (全局 index, 中文) → {index: 译文}，用结构化输出保证 1:1。"""
    numbered = "\n".join(f"{i}: {t}" for i, t in indexed)
    comp = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"You are a professional software UI translator. Translate each "
                f"Chinese source string to {target_name}, concise and natural for UI.",
            },
            {
                "role": "user",
                "content": (
                    f"Translate these UI strings from Chinese to {target_name}. Return one item per "
                    "input line with its SAME index. Keep placeholders like {name}/{count} EXACTLY. "
                    f"Do NOT translate these terms: {', '.join(PRESERVE_TERMS)}.\n\n{numbered}"
                ),
            },
        ],
        response_format=_TransBatch,
        temperature=0.3,
    )
    parsed = comp.choices[0].message.parsed
    return {it.index: it.translation for it in (parsed.items if parsed else [])}


def _llm_translate(texts: list[str], target_name: str, batch: int = 20) -> list[str]:
    client, model = _translate_client()
    workers = int(os.environ.get("VC_TRANSLATE_WORKERS", "8"))
    out: list[str] = [""] * len(texts)
    batches = [list(enumerate(texts))[i : i + batch] for i in range(0, len(texts), batch)]
    total = len(batches)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_translate_batch, client, model, target_name, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                for i, text in fut.result().items():
                    if 0 <= i < len(out):
                        out[i] = text
            except Exception as exc:  # noqa: BLE001 — 单批失败不应中断整体，缺失项后续重试
                print(f"  ⚠ batch 失败: {type(exc).__name__}: {str(exc)[:120]}")
            done += 1
            print(f"  {done}/{total} 批完成", flush=True)
    # 缺失项（解析丢条/批失败）串行重试一次
    missing = [i for i, v in enumerate(out) if not v]
    if missing:
        print(f"  重试 {len(missing)} 条缺失…")
        try:
            for i, text in _translate_batch(
                client, model, target_name, [(i, texts[i]) for i in missing]
            ).items():
                if 0 <= i < len(out):
                    out[i] = text
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ 重试失败: {type(exc).__name__}: {str(exc)[:120]}")
    return out


# ---------------------------------------------------------------- check (CI)
def check() -> int:
    with tempfile.NamedTemporaryFile(suffix=".pot", delete=False) as tmp:
        fresh = Path(tmp.name)
    extract(fresh)
    src_keys = _pot_keys(fresh)
    committed = _pot_keys(POT) if POT.exists() else set()
    fresh.unlink(missing_ok=True)

    rc = 0
    if src_keys != committed:
        only_src = sorted(src_keys - committed)
        only_pot = sorted(committed - src_keys)
        print("✗ 源码 key 集与提交的 .pot 不一致（需 i18n.py extract+update）")
        if only_src:
            print(f"  源码新增未抽取: {len(only_src)}：", ", ".join(only_src[:15]))
        if only_pot:
            print(f"  .pot 残留已删: {len(only_pot)}：", ", ".join(only_pot[:15]))
        rc = 1
    else:
        print(f"✓ key 集一致（{len(src_keys)} 条）")

    base = _po_path(BASE)
    if base.exists():
        with base.open("rb") as f:
            cat = read_po(f)
        empty = [m.id for m in cat if m.id and not m.string]
        if empty:
            print(f"✗ 基准 {BASE} 有 {len(empty)} 条空译文：", ", ".join(empty[:15]))
            rc = 1
        else:
            print(f"✓ 基准 {BASE} 无空译文")
    else:
        print(f"✗ 缺基准 po: {base}")
        rc = 1
    return rc


def _pot_keys(pot: Path) -> set[str]:
    with pot.open("rb") as f:
        cat = read_po(f)
    return {m.id for m in cat if m.id}


# ---------------------------------------------------------------- main
def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "extract":
        extract()
    elif cmd == "update":
        update()
    elif cmd == "compile":
        compile_()
    elif cmd == "fill-base":
        fill_base(Path(sys.argv[2]))
    elif cmd == "translate":
        translate(sys.argv[2:] or list(TARGET_NAME))
    elif cmd == "check":
        return check()
    elif cmd == "sync":
        extract()
        update()
        fill_base(Path(sys.argv[2]))
        translate(list(TARGET_NAME))
        compile_()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
