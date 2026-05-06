import sys
import os


def load_env_file(filepath):
    if not os.path.exists(filepath):
        return

    with open(filepath, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if value and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            os.environ[key] = value


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    load_env_file(os.path.join(os.getcwd(), ".env"))
    
    from ui_main import MainWindow
    
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Keyframe Pro Lite")
    
    dark_palette = """
    QMainWindow, QWidget {
        background-color: #1a1a1a;
        color: #e0e0e0;
        font-family: 'Segoe UI', sans-serif;
    }
    QMenuBar {
        background-color: #222;
        color: #e0e0e0;
        border-bottom: 1px solid #333;
    }
    QMenuBar::item:selected {
        background-color: #00a8ff;
        border-radius: 3px;
    }
    QMenu {
        background-color: #252525;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 4px;
    }
    QMenu::item {
        padding: 5px 20px;
        border-radius: 3px;
    }
    QMenu::item:selected {
        background-color: #00a8ff;
    }
    QStatusBar {
        background-color: #1e1e1e;
        color: #888;
        border-top: 1px solid #333;
        font-size: 11px;
    }
    QToolBar {
        background-color: #222;
        border: none;
        border-bottom: 1px solid #333;
        padding: 2px 4px;
        spacing: 3px;
    }
    QPushButton {
        background-color: #2d2d2d;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 4px 10px;
    }
    QPushButton:hover {
        background-color: #3a3a3a;
        border-color: #00a8ff;
    }
    QPushButton:pressed {
        background-color: #00a8ff;
        color: #fff;
    }
    QPushButton:checked {
        background-color: #005a8c;
        border-color: #00a8ff;
    }
    QListWidget {
        background-color: #1e1e1e;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 4px;
        outline: none;
    }
    QListWidget::item {
        padding: 4px 6px;
        border-radius: 3px;
    }
    QListWidget::item:hover {
        background-color: #2a2a2a;
    }
    QListWidget::item:selected {
        background-color: #00a8ff;
        color: #fff;
    }
    QLabel {
        color: #ccc;
    }
    QComboBox {
        background-color: #2d2d2d;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 3px 6px;
    }
    QComboBox:hover {
        border-color: #00a8ff;
    }
    QComboBox QAbstractItemView {
        background-color: #252525;
        color: #e0e0e0;
        selection-background-color: #00a8ff;
        border: 1px solid #333;
    }
    QSpinBox, QDoubleSpinBox {
        background-color: #2d2d2d;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 2px 4px;
    }
    QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: #00a8ff;
    }
    QLineEdit {
        background-color: #2d2d2d;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 3px 6px;
    }
    QLineEdit:focus {
        border-color: #00a8ff;
    }
    QCheckBox {
        color: #e0e0e0;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 14px; height: 14px;
        border: 1px solid #555;
        border-radius: 3px;
        background-color: #2d2d2d;
    }
    QCheckBox::indicator:checked {
        background-color: #00a8ff;
        border-color: #00a8ff;
    }
    QSlider::groove:horizontal {
        border: none;
        height: 4px;
        background: #3a3a3a;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #00a8ff;
        border: none;
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }
    QSlider::handle:horizontal:hover {
        background: #33bbff;
    }
    QProgressBar {
        border: 1px solid #333;
        border-radius: 4px;
        background-color: #2d2d2d;
        text-align: center;
        color: #ccc;
        height: 18px;
    }
    QProgressBar::chunk {
        background-color: #00a8ff;
        border-radius: 3px;
    }
    QSplitter::handle {
        background-color: #333;
    }
    QSplitter::handle:vertical {
        height: 4px;
    }
    QSplitter::handle:horizontal {
        width: 4px;
    }
    QScrollBar:horizontal {
        background: #1a1a1a;
        height: 8px;
        border: none;
    }
    QScrollBar::handle:horizontal {
        background: #444;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #555;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }
    QScrollBar:vertical {
        background: #1a1a1a;
        width: 8px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background: #444;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #555;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QGroupBox {
        border: 1px solid #333;
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 12px;
        color: #aaa;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }
    QToolTip {
        background-color: #333;
        color: #eee;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px;
    }
    QDialog {
        background-color: #1e1e1e;
    }
    """
    app.setStyleSheet(dark_palette)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
