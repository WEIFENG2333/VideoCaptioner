"""GUI entry point — launchable via `videocaptioner` (no args) or `python -m videocaptioner.ui.main`."""

import os
import platform
import sys


def _install_app_font(app):
    """加载内置霞鹜文楷并设为全局 UI 字体（Windows 缺省字体没有中文字形，会回退宋体）。

    qfluent 控件走自己的 getFont 字族表，需一并替换。
    """
    import qfluentwidgets
    from PyQt5.QtGui import QFont, QFontDatabase
    from qfluentwidgets.common import font as fluent_font

    from videocaptioner.config import FONTS_PATH

    families = []
    font_id = QFontDatabase.addApplicationFont(str(FONTS_PATH / "LXGWWenKai-Regular.ttf"))
    if font_id != -1:
        families = list(QFontDatabase.applicationFontFamilies(font_id))
    families += [
        "Segoe UI",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Helvetica Neue",
        "Arial",
    ]

    font = app.font()
    font.setFamilies(families)
    app.setFont(font)

    def get_font(fontSize=14, weight=QFont.Normal):
        font = QFont()
        font.setFamilies(families)
        font.setPixelSize(fontSize)
        font.setWeight(weight)
        return font

    fluent_font.getFont = get_font
    qfluentwidgets.getFont = get_font


def _suppress_subprocess_console_windows():
    """GUI 进程的所有子进程统一不弹控制台窗口（Windows）。

    打包版主程序无控制台，任何缺 CREATE_NO_WINDOW 的子进程调用（含 pydub、
    yt-dlp 等三方库内部）都会闪黑框；在入口统一注入，覆盖全部调用点。
    """
    if os.name != "nt":
        return
    import subprocess

    original_init = subprocess.Popen.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched_init


def main():
    import traceback

    _suppress_qt_font_alias_warning()
    _suppress_subprocess_console_windows()

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from videocaptioner.config import I18N_PATH
    from videocaptioner.core.utils.cache import disable_cache, enable_cache
    from videocaptioner.core.utils.logger import setup_logger
    from videocaptioner.ui.i18n import init as init_i18n

    # Suppress qfluentwidgets ad
    with open(os.devnull, "w") as _devnull:
        sys.stdout, _stdout = _devnull, sys.stdout
        from qfluentwidgets import FluentTranslator, Theme, setTheme, setThemeColor
        sys.stdout = _stdout

    from videocaptioner.ui.common.config import ThemeMode, cfg

    def _to_qfluent_theme(theme: ThemeMode) -> Theme:
        if theme == ThemeMode.LIGHT:
            return Theme.LIGHT
        if theme == ThemeMode.AUTO:
            return Theme.AUTO
        return Theme.DARK

    # Qt platform plugin path
    lib_folder = "Lib" if platform.system() == "Windows" else "lib"
    plugin_path = os.path.join(
        sys.prefix, lib_folder, "site-packages", "PyQt5", "Qt5", "plugins"
    )
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path

    # Logger + global exception hook
    logger = setup_logger("VideoCaptioner")

    def exception_hook(exctype, value, tb):
        logger.error("".join(traceback.format_exception(exctype, value, tb)))
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook

    # Cache
    if cfg.get(cfg.cache_enabled):
        enable_cache()
    else:
        disable_cache()

    # 一次性把旧 APPDATA 的实时字幕历史迁入工作目录（仅真实启动时，避免 widget 构造/测试误触发）。
    from videocaptioner.core.realtime.recording.history import default_root, migrate_legacy_root

    migrate_legacy_root(default_root(cfg.get(cfg.work_dir)))

    # DPI scaling
    if cfg.get(cfg.dpiScale) == "Auto":
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough  # type: ignore
        )
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # type: ignore
    else:
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)  # type: ignore

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)  # type: ignore
    _install_app_font(app)
    setTheme(_to_qfluent_theme(cfg.themeMode.value))
    setThemeColor(cfg.themeColor.value)

    # i18n：UI 走 key-based gettext（core/CLI 不翻译）；FluentTranslator 负责 qfluent 自带控件。
    # 必须在 import 页面模块之前装载语言——模块级常量若含 tr()/N_() key 求值发生在 import 时。
    locale = cfg.get(cfg.language).value
    app.installTranslator(FluentTranslator(locale))
    init_i18n(I18N_PATH, locale.name())

    from videocaptioner.ui.view.main_window import MainWindow

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


def _suppress_qt_font_alias_warning():
    rule = "qt.qpa.fonts=false;qt.qpa.fonts.warning=false"
    current = os.environ.get("QT_LOGGING_RULES", "").strip()
    if not current:
        os.environ["QT_LOGGING_RULES"] = rule
    elif rule not in current:
        separator = "\n" if "\n" in current else ";"
        os.environ["QT_LOGGING_RULES"] = f"{current}{separator}{rule}"


if __name__ == "__main__":
    main()
