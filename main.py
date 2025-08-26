import sys
from PyQt6.QtWidgets import QApplication
from main_window import ImageFilterApp

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ImageFilterApp()
    window.show()
    sys.exit(app.exec())