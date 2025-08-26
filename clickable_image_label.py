import sys
from PyQt6.QtWidgets import QLabel, QApplication, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen


class ClickableImageLabel(QLabel):
    clicked = pyqtSignal(str)  # Signal to emit when clicked, passing the image path
    
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.selected = False
        self.setStyleSheet("border: 2px solid transparent;")  # Default border
        
    def setPixmap(self, pixmap):
        # Store original pixmap for redrawing with highlight
        self.original_pixmap = pixmap
        self.update_pixmap()
    
    def updatePixmapWithSize(self, size):
        # Update the pixmap with a new size
        if self.image_path:
            pixmap = QPixmap(self.image_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.setPixmap(pixmap)
                self.setFixedSize(size, size)
        
    def update_pixmap(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            if self.selected:
                # Create a highlighted version of the pixmap
                pixmap = self.original_pixmap.copy()
                painter = QPainter(pixmap)
                pen = QPen(QColor(0, 120, 215), 4)  # Blue border for selection
                painter.setPen(pen)
                painter.drawRect(2, 2, pixmap.width() - 4, pixmap.height() - 4)
                painter.end()
                super().setPixmap(pixmap)
            else:
                super().setPixmap(self.original_pixmap)
                
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected = not self.selected
            self.update_pixmap()
            self.setStyleSheet("border: 2px solid #0078D7;" if self.selected else "border: 2px solid transparent;")
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)
        
    def setSelected(self, selected):
        self.selected = selected
        self.update_pixmap()
        self.setStyleSheet("border: 2px solid #0078D7;" if self.selected else "border: 2px solid transparent;")


if __name__ == "__main__":
    # For testing the ClickableImageLabel class
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout()
    
    # Create a test label
    label = ClickableImageLabel("test_path")
    pixmap = QPixmap(200, 200)
    pixmap.fill(QColor(200, 200, 200))
    label.setPixmap(pixmap)
    label.setFixedSize(200, 200)
    
    layout.addWidget(label)
    window.setLayout(layout)
    window.show()
    
    sys.exit(app.exec())