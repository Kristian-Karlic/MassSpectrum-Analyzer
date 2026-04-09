from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainter, QColor
import pyqtgraph as pg


class PlotDimmer(pg.GraphicsObject):
    """Semi-transparent overlay to dim the plot during loading"""
    
    def __init__(self, plot_item, parent=None):
        super().__init__(parent)
        self.plot_item = plot_item
        self.dimmer_color = QColor(255, 255, 255, 120)  # Light dimming effect
        
    def boundingRect(self):
        """REQUIRED: Return the bounding rectangle covering the entire plot"""
        if self.plot_item:
            try:
                return self.plot_item.getViewBox().viewRect()
            except Exception:
                return QRectF(0, 0, 1000, 800)
        return QRectF(0, 0, 1000, 800)
    
    def paint(self, painter, option, widget):
        """REQUIRED: Paint the dimming overlay"""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.boundingRect(), self.dimmer_color)