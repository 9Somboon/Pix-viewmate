import sys
from PyQt6.QtWidgets import QLabel, QApplication, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
from thumbnail_cache import load_cached_thumbnail


class ClickableImageLabel(QLabel):
    clicked = pyqtSignal(str, object)  # Signal to emit when clicked, passing image path and modifiers
    
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.selected = False
        # self.setStyleSheet("border: 2px solid transparent;")  # Default border
        
    def setPixmap(self, pixmap):
        # Store original pixmap for redrawing with highlight
        self.original_pixmap = pixmap
        self.update_pixmap()
    
    def updatePixmapWithSize(self, size, fast_mode=False):
        # Update the pixmap with a new size using cached thumbnail
        if self.image_path:
            # Use cached thumbnail loading for better performance
            pixmap = load_cached_thumbnail(self.image_path, size, fast_mode=fast_mode)
            if not pixmap.isNull():
                self.setPixmap(pixmap)
                self.setFixedSize(size, size)
        
    def update_pixmap(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            if self.selected:
                # Create a highlighted version of the pixmap
                pixmap = self.original_pixmap.copy()
                painter = QPainter(pixmap)
                pen = QPen(QColor(0, 122, 255), 3)  # Blue border for selection (macOS blue)
                painter.setPen(pen)
                painter.drawRect(1, 1, pixmap.width() - 2, pixmap.height() - 2)
                painter.end()
                super().setPixmap(pixmap)
            else:
                super().setPixmap(self.original_pixmap)
                
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Get keyboard modifiers
            modifiers = QApplication.keyboardModifiers()
            
            # Don't toggle selection here; let the main window handle it
            # This allows for shift-click range selection
            if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
                # Only toggle if not shift-clicking (normal behavior)
                self.selected = not self.selected
                self.update_pixmap()
            
            # Emit signal with modifiers so main window can handle shift-click
            self.clicked.emit(self.image_path, modifiers)
        super().mousePressEvent(event)
        
    def setSelected(self, selected):
        self.selected = selected
        self.update_pixmap()
        # Use macOS-style blue border for selection
        # self.setStyleSheet("border: 2px solid #007AFF;" if self.selected else "border: 2px solid transparent;")


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