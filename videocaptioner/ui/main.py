"""GUI entry point — launchable via `videocaptioner` (no args) or `python -m videocaptioner.ui.main`."""

import os
import platform
import sys


def _patch_qfluent_font_fallback():
    if platform.system() != "Darwin":
        return

    import qfluentwidgets
    from PyQt5.QtGui import QFont
    from qfluentwidgets.common import font as fluent_font

    def get_font(fontSize=14, weight=QFont.Normal):
        font = QFont()
        font.setFamilies(["PingFang SC", "Helvetica Neue", "Arial"])
        font.setPixelSize(fontSize)
        font.setWeight(weight)
        return font

    fluent_font.getFont = get_font
    qfluentwidgets.getFont = get_font


def main():
    import traceback

    _suppress_qt_font_alias_warning()

    from PyQt5.QtCore import Qt, QTranslator
    from PyQt5.QtWidgets import QApplication

    from videocaptioner.config import TRANSLATIONS_PATH
    from videocaptioner.core.utils.cache import disable_cache, enable_cache
    from videocaptioner.core.utils.logger import setup_logger

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

    _patch_qfluent_font_fallback()
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)  # type: ignore
    setTheme(_to_qfluent_theme(cfg.themeMode.value))
    setThemeColor(cfg.themeColor.value)

    from videocaptioner.ui.view.main_window import MainWindow

    # i18n
    locale = cfg.get(cfg.language).value
    app.installTranslator(FluentTranslator(locale))
    my_translator = QTranslator()
    my_translator.load(str(TRANSLATIONS_PATH / f"VideoCaptioner_{locale.name()}.qm"))
    app.installTranslator(my_translator)

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
