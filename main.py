# coding:utf-8
import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

# 修复中文路径问题
plugin_path = os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path

from PyQt5.QtCore import Qt, QTranslator
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from app.common.config import cfg
from app.view.main_window import MainWindow
from app.config import RESOURCE_PATH

# enable dpi scale
if cfg.get(cfg.dpiScale) == "Auto":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
else:
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))

QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

# create application
app = QApplication(sys.argv)
app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

# 创建一个全局字体
# font = QFont("./app/resource/AlibabaPuHuiTi-Medium.ttf")
# app.setFont(font)
# 加载自定义字体
# font_path = os.path.join(os.path.dirname(__file__), "app/resource/AlibabaPuHuiTi-Medium.ttf")  # 替换为你的字体路径
# font_id = QFontDatabase.addApplicationFont(font_path)
# if font_id == -1:
#     print("字体加载失败")
# else:
#     # 获取字体系列名称
#     font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
#     print(font_family)
#     app.setFont(QFont(font_family, 12))  # 字体大小为 12

# 国际化（多语言）
locale = cfg.get(cfg.language).value

translator = FluentTranslator(locale)
myTranslator = QTranslator()
translations_path = RESOURCE_PATH / "translations" / f"VideoCaptioner_{locale.name()}.qm"
myTranslator.load(str(translations_path))
app.installTranslator(translator)
app.installTranslator(myTranslator)

# create main window
w = MainWindow()
w.show()

if __name__ == '__main__':
    app.exec_()
