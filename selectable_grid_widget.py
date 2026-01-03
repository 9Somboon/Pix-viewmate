from PyQt6.QtWidgets import QWidget, QGridLayout
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen
from clickable_image_label import ClickableImageLabel


class SelectableGridWidget(QWidget):
    """A widget that wraps a QGridLayout and provides rubber-band selection."""
    
    selection_changed = pyqtSignal()  # Emitted when selection changes via rubber band
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        
        # Rubber band selection state
        self.rubber_band_origin = None
        self.rubber_band_rect = None
        self.is_selecting = False
        
    def mousePressEvent(self, event):
        """Start rubber band selection on left mouse button press."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if we clicked on empty space (not on an image)
            child_widget = self.childAt(event.pos())
            if child_widget is None or not isinstance(child_widget, ClickableImageLabel):
                self.rubber_band_origin = event.pos()
                self.rubber_band_rect = QRect(self.rubber_band_origin, event.pos())
                self.is_selecting = True
                self.update()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Update rubber band rectangle while dragging."""
        if self.is_selecting and self.rubber_band_origin:
            self.rubber_band_rect = QRect(self.rubber_band_origin, event.pos()).normalized()
            self.update()
            
            # Highlight images that intersect with the rubber band
            self._update_selection_preview()
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Finish rubber band selection and select images within the rectangle."""
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            
            if self.rubber_band_rect:
                # Select all images within the rubber band rectangle
                self._select_images_in_rect(self.rubber_band_rect)
                self.selection_changed.emit()
            
            self.rubber_band_rect = None
            self.update()
        super().mouseReleaseEvent(event)
    
    def paintEvent(self, event):
        """Draw the rubber band rectangle if active."""
        super().paintEvent(event)
        
        if self.is_selecting and self.rubber_band_rect:
            painter = QPainter(self)
            
            # Draw filled rectangle with transparency
            fill_color = QColor(0, 122, 255, 50)  # macOS blue with alpha
            painter.fillRect(self.rubber_band_rect, fill_color)
            
            # Draw border
            pen = QPen(QColor(0, 122, 255), 2)
            painter.setPen(pen)
            painter.drawRect(self.rubber_band_rect)
            
            painter.end()
    
    def _update_selection_preview(self):
        """Update visual preview of which images would be selected."""
        # This is optional - we could show preview highlighting here
        pass
    
    def _select_images_in_rect(self, rect):
        """Select all image labels that intersect with the given rectangle."""
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, ClickableImageLabel):
                    # Get widget geometry in parent coordinates
                    widget_rect = QRect(widget.pos(), widget.size())
                    
                    # Check if widget intersects with selection rectangle
                    if rect.intersects(widget_rect):
                        widget.setSelected(True)
                    # Note: We don't deselect here to allow additive selection
    
    def get_all_image_labels(self):
        """Get all ClickableImageLabel widgets in the grid."""
        labels = []
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, ClickableImageLabel):
                    labels.append(widget)
        return labels
