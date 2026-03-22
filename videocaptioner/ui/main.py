"""GUI entry point — launchable via `videocaptioner` (no args) or `python -m videocaptioner.ui.main`."""

import os
import platform
import sys


def main():
    import traceback

    from PyQt5.QtCore import Qt, QTranslator
    from PyQt5.QtWidgets import QApplication

    from videocaptioner.config import TRANSLATIONS_PATH
    from videocaptioner.core.utils.cache import disable_cache, enable_cache
    from videocaptioner.core.utils.logger import setup_logger

    # Suppress qfluentwidgets ad
    with open(os.devnull, "w") as _devnull:
        sys.stdout, _stdout = _devnull, sys.stdout
        from qfluentwidgets import FluentTranslator
        sys.stdout = _stdout

    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.view.main_window import MainWindow

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

    # i18n
    locale = cfg.get(cfg.language).value
    app.installTranslator(FluentTranslator(locale))
    my_translator = QTranslator()
    my_translator.load(str(TRANSLATIONS_PATH / f"VideoCaptioner_{locale.name()}.qm"))
    app.installTranslator(my_translator)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
