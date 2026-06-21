# VideoCaptioner 国际化（i18n）架构

> 现状架构文档（已实施）。**只翻 UI（PyQt）；core 与 CLI 不翻译。**
> 日常操作/维护/排错见 [`docs/dev/i18n-workflow.md`](./i18n-workflow.md)。

## 一、总体

UI 国际化用 **key-based gettext**：源码里写稳定 key（`tr("dubbing.btn.start")`），各语言文案存
`.po`、编译成 `.mo`，运行时用 Python 标准库 `gettext` 读取。基准语言 `zh_Hans` 是 key→中文的唯一真相源；
`en`/`zh_Hant` 从它翻译，缺译时运行时回退基准中文（不显示 key）。

- 资源格式 = gettext `.po/.mo`（译者工具/平台通用；core/CLI 翻译零 Qt 依赖）。
- 源串 = key（不是中文）：改中文不丢译文、key 可 grep、可静态校验。
- Qt 侧只保留一件事：启动时装 `qfluentwidgets` 的 `FluentTranslator`，让 qfluent 自带控件随语言走。
- **范围**：只翻 UI。core 异常文案保持中文现状（`worker.error` 直接 `str(exc)`）；CLI help 英文、不接 i18n。

## 二、组成

```
videocaptioner/ui/i18n/
  __init__.py     tr(key, **params) / N_(key) / init / set_language / current_language
  catalog.py      gettext catalog 加载/缓存；非基准语言缺译回退基准中文
videocaptioner/ui/common/enum_labels.py
                  枚举→UI 标签：程序化 enum_key(member)=f"enum.{类名}.{成员名}" + TRANSLATABLE_ENUMS
                  + enum_options()/enum_from_label()/enum_base_map()（不手写 dict）
resource/i18n/
  videocaptioner.pot
  zh_Hans|zh_Hant|en/LC_MESSAGES/videocaptioner.po / .mo
babel.cfg         抽取配置（`[python: **.py]`；关键字 -k tr -k N_ 在 scripts/i18n.py 命令行传）
scripts/i18n.py   工具链：extract / update / fill-base / translate / compile / check / sync
```

- 运行时入口 `ui/main.py`：`FluentTranslator(locale)` + `init_i18n(I18N_PATH, locale.name())`（在构造主窗口前）。
- 配置：`config.py` 的 `Language` 枚举（简体/繁体/English/跟随系统）+ `I18N_PATH`。
- 打包：`pyproject` wheel force-include `resource/i18n`、`VideoCaptioner.spec` data 同步。

## 三、key 与文案约定

- key 命名 `<域>.<组件>.<语义>`（域=页面/模块）；通用词用 `common.*`。
- 静态文案：`tr("dom.key")`。带变量：`tr("dom.key", n=3)`，`.po` 写 `"… {n} …"`。
- **枚举下拉**不手写标签：`options_from(...)`（定义在 `ui/components/settings_controls.py`，内部走
  `enum_label`）或 `enum_options(EnumCls)`（在 `enum_labels.py`）。新增需翻译枚举→加进 `TRANSLATABLE_ENUMS`。
- **`tr(变量)` 的 key**（表头/状态等常量）：定义处用 `N_("key")` 让 pybabel 抽到，渲染处 `tr(那个常量)`。
- **动态拼接 key**（配音 provider/voice/tag、识别语言 `lclang.*`）：由 `dubbing_options.i18n_base_map()`
  / `config.source_language_i18n_map()` 注册表经 `scripts/i18n.py` 的 `_runtime_keys()` 注入 `.pot`。
- **禁止**：`self.tr(...)`、把中文当 key（`tr("中文")`）、函数内局部 import `tr`。

## 四、语言切换

设置 → 个性化 → 界面语言。改后弹确认对话框 → `QProcess.startDetached` 重拉 + `app.quit()` 自动重启，
重启后以新语言构造界面（`setting_interface._show_restart_tip`）。**不做逐页 `retranslate`**（26 个大页面
维护成本高、易遗漏；自动重启 100% 无遗漏，且切语言是低频操作）。`set_language()` 作为公共 API 保留，
未来若要真热切换可在其上补 `QEvent.LanguageChange` 派发。

## 五、工具链与 CI

- 改了文案/key/枚举后跑 `scripts/i18n.py extract→update→fill-base→translate→compile`（细节见 workflow 文档）。
- `translate` 用 OpenAI 兼容端点 + 结构化输出（`beta.parse`）+ 并发，端点由 `VC_TRANSLATE_*` 环境变量配置。
- CI（`.github/workflows/ci.yml`）跑 `scripts/i18n.py check`（源码 key 集==.pot、基准 `zh_Hans` 无空译文）
  + `tests/test_i18n`。改了 `tr/N_` 没同步会被自动拦住。

## 六、已知限制

- **英文文本膨胀**：部分定宽控件（设置左侧导航、窄卡片）的较长英文会省略号截断（优雅降级、不破版）。
  本应用 Chinese-first，英文尽力而为；需要时再针对性放宽对应控件宽度。
- `en/zh_Hant` 为机器翻译（结构化 LLM，占位符/术语已约束保留）；上线前可在 Poedit 人工校对 `.po`。
- 复数（`ngettext`）暂未使用；命名占位 `{name}` 已支持。
