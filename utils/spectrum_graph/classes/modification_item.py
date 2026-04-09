# modification_item.py
import logging

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush

from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class ModificationItem(pg.GraphicsObject):
    """Improved draggable modification item with better scaling control"""

    modificationMoved = pyqtSignal(int, int, float)  # old_pos, new_pos, mass
    modificationRemoved = pyqtSignal(int, float)     # position, mass

    def __init__(self, position: int, mass: float, name: str, color: QColor, parent_widget):
        super().__init__()
        self.position = position
        self.mass = mass
        self.name = name
        self.parent_widget = parent_widget
        self.dragging = False
        self.drag_offset = pg.QtCore.QPointF(0, 0)

        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)  # Changed to True
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        # Dynamic sizing based on letter spacing instead of fixed size
        self.height_ratio = 15  # Height as fraction of letter spacing (increased from 8)
        self.width_ratio = 0.8   # Width as fraction of letter spacing
        self.min_height = 45      # Minimum height in pixels (increased from 30)
        self.max_height = 90    # Maximum height in pixels (increased from 60)
        self.min_width = 6       # Minimum width in pixels
        self.max_width = 20      # Maximum width in pixels

        # Color properties
        self.color = color
        self.hover_color = QColor(color.red(), color.green(), color.blue(), 180)  # Lighter version
        self.current_color = self.color

    def get_letter_based_size(self):
        """Calculate size based on current responsive parameters"""
        if not self.parent_widget:
            return 12, 15  # Fallback size (increased height)

        # Get current responsive parameters
        font_size = getattr(self.parent_widget, 'current_font_size', 20)
        letter_spacing = getattr(self.parent_widget, 'letter_spacing', 25)

        # Scale with font size
        font_scale = font_size / 20  # Base font size ratio

        # Calculate size based on both font and spacing
        width = max(6, min(16, letter_spacing * 0.4 * font_scale))
        height = max(20, min(60, font_size * 1.2))  # Increased height multiplier

        return width, height

    def boundingRect(self):
        """Return bounding rectangle based on letter spacing"""
        width, height = self.get_letter_based_size()
        return QRectF(-width/2, -height/2, width, height)

    def paint(self, painter, option, widget):
        """Paint a colored rectangle sized to match letter width"""

        # Skip painting if painter is invalid or widget is None (during SVG export)
        if not painter or not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Get the letter-based size
            width, height = self.get_letter_based_size()

            # Create rectangle
            rect = QRectF(-width/2, -height/2, width, height)

            # Set brush and pen with theme-aware border
            brush = QBrush(self.current_color)
            painter.setBrush(brush)

            # Scale pen width based on size
            pen_width = max(0.5, min(width, height) / 20)
            pen = QPen(pg.mkColor(EditorConstants.TEXT_COLOR()))
            pen.setWidthF(pen_width)
            painter.setPen(pen)

            # Draw rectangle
            painter.drawRect(rect)

        except Exception as e:
            # Silent fail during SVG export
            pass

    def hoverEnterEvent(self, event):
        self.current_color = self.hover_color
        self.update()
        tooltip = f"{self.name}\nMass: +{self.mass:.4f}\nPosition: {self.position}"
        self.setToolTip(tooltip)

    def hoverLeaveEvent(self, event):
        if not self.dragging:
            self.current_color = self.color
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            scene_pos = self.mapToScene(event.pos())
            item_scene_pos = self.scenePos()
            self.drag_offset = scene_pos - item_scene_pos
            self.setZValue(1000)  # Bring to front during drag
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.modificationRemoved.emit(self.position, self.mass)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            scene_pos = self.mapToScene(event.pos())
            target_scene_pos = scene_pos - self.drag_offset

            if self.parent_widget and hasattr(self.parent_widget, 'peptide_plot'):
                view_pos = self.parent_widget.peptide_plot.getViewBox().mapSceneToView(target_scene_pos)
                self.setPos(view_pos.x(), view_pos.y())

            event.accept()

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.setZValue(0)  # Reset z-value

            current_pos = self.pos()
            new_position = self.parent_widget.get_nearest_position(current_pos.x())

            logger.debug(f"Drag ended, moving from position {self.position} to {new_position}")

            if new_position != self.position and new_position > 0:
                old_position = self.position
                self.position = new_position
                self.modificationMoved.emit(old_position, new_position, self.mass)
            else:
                # Snap back to original position
                self.parent_widget.update_modification_display()

            # Reset color after dragging
            self.current_color = self.color
            self.update()

            event.accept()
