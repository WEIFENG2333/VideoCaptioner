# i18n 工作流与维护指南

VideoCaptioner 的界面国际化是 **key-based gettext**，**只翻 UI（PyQt）；core 与 CLI 不翻译**
（完整架构见 `docs/dev/i18n-plan.md`）。本文是**日常怎么写、改完怎么同步、怎么发现并避免不一致**的操作手册。

## 0. 心智模型（先理解这个，后面都顺）

```
源码:           tr("dubbing.btn.start")          ← 只有 key，没有中文
基准真相源:     resource/i18n/zh_Hans/...po       msgid=key, msgstr=中文   ← 中文住在这里
其它语言:       en / zh_Hant 的 .po               msgstr=译文，从 zh_Hans 翻译而来
运行时:         读 .mo；缺译 → 自动回退 zh_Hans 中文（不显示 key）
```

- **中文文案不在 Python 源码里**，在 `zh_Hans` 的 `.po`。改中文 = 改 `zh_Hans.po`（或它的来源：枚举 `.value` / 数据文件）。
- `en`/`zh_Hant` 是**派生**的；改了中文，它们的旧译文会过时，需要主动同步（见 §3）。
- 三种语言的 key 必须始终一致（CI 保证）。

## 1. 写代码（加/用文案）

```python
from videocaptioner.ui.i18n import tr          # 顶部模块级导入（禁止函数内局部导入）

label.setText(tr("dubbing.btn.start"))         # 静态文案
label.setText(tr("hardsub.toast.done", n=3))   # 命名占位：zh_Hans.po 写 "已提取 {n} 条字幕"
```

- key 命名 `<域>.<组件>.<语义>`（域=页面/模块）；通用词用 `common.*`。
- **不要** `self.tr(...)`，**不要**把中文当 key（`tr("中文")`）——会污染抽取。
- **枚举下拉不手写标签**：`options_from(...)`（`ui/components/settings_controls.py`，内部走 `enum_label`）
  或 `enum_options(EnumCls)`（`ui/common/enum_labels.py`）自动 `tr(enum.<类>.<成员>)`。
  新增需翻译的枚举：把类加进 `enum_labels.py` 的 `TRANSLATABLE_ENUMS`。
- **`tr(变量)` 的 key**（表头/状态等常量）：在常量定义处用 `N_("key")` 包一层，pybabel 才抽得到。例：
  `HEADER_KEYS = (N_("subtitle.col.start"), ...)` 然后 `tr(self.HEADER_KEYS[i])`。
- **动态拼接的 key**（配音 provider/voice/tag、识别语言 `lclang.*`）：由
  `dubbing_options.i18n_base_map()` / `config.source_language_i18n_map()` 注册表注入，无需 N_。

## 2. 翻译端点配置（translate 用）

`scripts/i18n.py translate` 用 OpenAI 兼容接口 + 结构化输出（`beta.parse`）。端点由环境变量配置：

| 变量 | 含义 | 默认 |
|---|---|---|
| `VC_TRANSLATE_API_KEY` | API Key（缺省回退 `OPENAI_API_KEY`）| — |
| `VC_TRANSLATE_BASE_URL` | OpenAI 兼容 base url | `https://api.openai.com/v1` |
| `VC_TRANSLATE_MODEL` | 模型名 | `gpt-5` |
| `VC_TRANSLATE_WORKERS` | 并发批数 | `8` |

示例（任选其一，**key 只走环境变量，绝不写进文件**）：

```bash
# 本地网关（CherryStudio 等，gpt-5.5 官方结构化输出）
VC_TRANSLATE_API_KEY=xxx VC_TRANSLATE_BASE_URL=http://127.0.0.1:8317/v1 \
  VC_TRANSLATE_MODEL=gpt-5.5 VC_TRANSLATE_WORKERS=12 \
  .venv/bin/python scripts/i18n.py translate

# SiliconFlow
VC_TRANSLATE_API_KEY=sk-xxx VC_TRANSLATE_BASE_URL=https://api.siliconflow.cn/v1 \
  VC_TRANSLATE_MODEL=deepseek-ai/DeepSeek-V4-Pro VC_TRANSLATE_WORKERS=12 \
  .venv/bin/python scripts/i18n.py translate
```

`translate` 只翻**空 msgstr**的条目（已译的不动），并发跑、缺失自动重试一次。要重译某条先清空它的 msgstr。

## 3. 改完之后该做什么（按场景，照着做就不会不一致）

> 经验法则：**动了源码的 `tr/N_`、或动了枚举/数据文件 → 跑 `extract`→`update`**；
> **动了中文 → 填 `zh_Hans` → `translate` → `compile`**。最后永远 `check`。

### A. 加了新 UI 文案 / 新 key
```bash
.venv/bin/python scripts/i18n.py extract       # 源码 tr/N_ → .pot（含新 key）
.venv/bin/python scripts/i18n.py update        # .pot → 各 .po（新 key 空 msgstr）
# 填基准中文：编辑 zh_Hans.po 给新 key 写中文；或用 json 批量导入：
.venv/bin/python scripts/i18n.py fill-base /tmp/new-keys.json   # {"dom.key":"中文"}
.venv/bin/python scripts/i18n.py translate     # 翻 en/zh_Hant 的空条
.venv/bin/python scripts/i18n.py compile
```

### B. 改了某个 key 的**中文**（key 不变）
中文在 `zh_Hans.po`，直接改它的 `msgstr`。要让 en/zh_Hant 跟进（否则它们仍是旧译文）：
```bash
# 编辑 zh_Hans.po 改中文；再清空 en/zh_Hant 中该 key 的 msgstr（置为 msgstr ""）
.venv/bin/python scripts/i18n.py translate     # 只补空的 → 重译这几条
.venv/bin/python scripts/i18n.py compile
```
（不清空就不会重译——`translate` 只填空条。）

### C. **重命名 key / 改了控件名导致 key 变**（你最担心的「名称改了怎么同步」）
改源码后 key 集变化，`extract`+`update` 会自动处理：
```bash
.venv/bin/python scripts/i18n.py extract
.venv/bin/python scripts/i18n.py update        # 旧 key 被标 #~ obsolete，新 key 为空
```
- **新 key** 当作场景 A 处理（填中文+翻译）。
- **旧 key** 变成 `.po` 顶部的 `#~` obsolete 注释，不影响运行；可留着（下次 lupdate 风格清理）或手动删。
- **CI 会拦住忘记同步的情况**：`scripts/i18n.py check` 比对「源码抽出的 key 集 == 提交的 .pot」，
  改了源码没重跑 extract → key 集不一致 → CI 失败并列出差异。这就是「自动发现不一致」。

### D. 删了页面 / 删了文案
源码没了 `tr`，`extract` 后那些 key 不再出现 → `update` 把它们标 obsolete。跑 `extract`+`update`+`check` 即可。

### E. 加了枚举成员 / 新配音 provider / voice / 新识别语言 code
这些是 §1 的注册表/数据，中文来自 `.value`/数据字段，`extract` 会经 `_runtime_keys()` 自动带上 key，
`fill-base` 自动派生中文：
```bash
.venv/bin/python scripts/i18n.py extract
.venv/bin/python scripts/i18n.py update
.venv/bin/python scripts/i18n.py fill-base /tmp/empty.json   # 传 {}，枚举/数据中文自动并入
.venv/bin/python scripts/i18n.py translate
.venv/bin/python scripts/i18n.py compile
```

### F. 加一门新语言（例如日语 ja）
在 `scripts/i18n.py` 的 `LANGS` 加 `"ja"`、`TARGET_NAME` 加 `"ja": "Japanese"`；catalog 的 `_normalize`
按需加映射。然后 `update`→`translate ja`→`compile`。无需改任何页面代码。

### 一把梭
```bash
.venv/bin/python scripts/i18n.py sync /tmp/new-keys.json
# = extract → update → fill-base(json，并自动并入枚举/数据中文) → translate(en/zh_Hant) → compile
```

## 4. 怎么发现不一致（排错对照表）

| 症状 | 原因 | 处理 |
|---|---|---|
| 界面显示 `dom.xxx` 这样的 key | 该 key 在 .mo 里没有（没 fill/没 compile，或 key 拼错） | 跑 §3.A；确认 `zh_Hans.po` 有该 key 且非空，`compile` |
| 英文界面显示中文 | 该 key 的 en 未译（回退中文，正常降级） | 跑 `translate` 补 en |
| CI `i18n check` 失败：key 集不一致 | 改了源码 `tr/N_` 没重跑 extract/update | 跑 `extract`+`update`，提交 .pot/.po |
| CI `i18n check` 失败：zh_Hans 有空译文 | 新 key 没填中文 | 填 `zh_Hans.po` 或 `fill-base` |
| 下拉项不翻译 | 枚举没进 `TRANSLATABLE_ENUMS`，或代码用了 `[x.value for x in Enum]` | 加进注册表；下拉改 `options_from`/`enum_options` |
| 启动报未使用导入 / `tr` 未定义 | 加了 `tr/N_` 没在文件顶部 import | 顶部 `from videocaptioner.ui.i18n import tr`（或 `N_`） |

**本地自查**（提交前必跑）：
```bash
.venv/bin/python scripts/i18n.py check        # 源码 key 集==.pot；zh_Hans 无空译文
.venv/bin/python -m pytest tests/test_i18n -q
```
CI（`.github/workflows/ci.yml`）会自动跑 `check` + `tests/test_i18n`，PR 漏同步会被拦住。

## 5. 防不一致铁律

1. **改了 `tr/N_`/枚举/数据文件，必跑 `extract`+`update`**，并把 `resource/i18n/**`（.pot/.po/.mo）一起提交。
2. `.po` 和 `.mo` 都提交（pip/源码安装没有 CI 也要能用）；改了 `.po` 必 `compile` 重生成 `.mo`。
3. **基准 `zh_Hans` 不能有空译文**（CI 拦）；它是唯一中文真相源。
4. key 只在源码（`tr("...")`/`N_("...")`）；中文只在 `.po`。两者别混。
5. 提交前跑 `scripts/i18n.py check`。

## 6. 已知限制

- **英文文本膨胀**：部分定宽控件（设置左侧导航、窄卡片）的较长英文会省略号截断（优雅降级，不破版）。
  本应用 Chinese-first，英文为尽力而为；需要时再针对性放宽对应控件宽度。
- **en/zh_Hant 译文是机器翻译**（结构化 LLM），术语/占位符已约束保留；上线前可在 Poedit 人工校对 `.po`。
