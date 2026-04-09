from PyQt6.QtWidgets import (QLabel, QApplication
)
from PyQt6.QtGui import QCursor
from PyQt6.QtCore import Qt, QTimer, QPoint, QEvent

from ..config.constants import PlotConstants

class PersistentTooltip(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setTextFormat(Qt.TextFormat.RichText)  # Enable HTML rendering
        self.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 240);
                border: 1px solid #333333;
                padding: 5px;
                border-radius: 3px;
                font-family: {PlotConstants.DEFAULT_FONT_FAMILY};
                font-size: 14pt;
                color: black;
            }}
        """)
        self.hide()
        self.setMinimumSize(200, 50)
    
        # Timer for cursor following
        self.follow_timer = QTimer()
        self.follow_timer.timeout.connect(self.follow_cursor)
        self.follow_timer.setInterval(PlotConstants.TOOLTIP_FOLLOW_INTERVAL_MS)  # Update every 50ms

        if parent:
            parent.installEventFilter(self)
        
        # Monitor application focus changes
        app = QApplication.instance()
        if app:
            app.focusChanged.connect(self._on_focus_changed)
        

    def eventFilter(self, obj, event):
        """Monitor parent widget events"""
        
        # Hide tooltip on various events that indicate user interaction elsewhere
        if event.type() in [
            QEvent.Type.WindowDeactivate,
            QEvent.Type.FocusOut,
            QEvent.Type.Leave,
            QEvent.Type.ApplicationDeactivate,
            QEvent.Type.WindowStateChange
        ]:
            self.hide_tooltip()
        
        return super().eventFilter(obj, event)
    def _on_focus_changed(self, old_widget, new_widget):
        """Hide tooltip when focus changes to a different widget"""
        # If focus moved to a different widget that's not part of our tooltip system
        if new_widget and not self.isAncestorOf(new_widget) and new_widget != self.parent():
            self.hide_tooltip()

    def show_tooltip(self, text, position):
        """Show tooltip at specified position with enhanced focus handling"""
        if not text or not text.strip():
            self.hide_tooltip()
            return
        
        # Check if application has focus before showing tooltip
        app = QApplication.instance()
        if app and not app.activeWindow():
            return
        self.setText(text.replace('\n', '<br>'))
        self.adjustSize()
        
        if position is None:
            position = QCursor.pos()
        
        # Offset slightly to avoid cursor overlap
        offset_position = position + QPoint(PlotConstants.TOOLTIP_OFFSET_X, PlotConstants.TOOLTIP_OFFSET_Y)
        self.move(offset_position)
        self.show()
        
        # Start following the cursor
        self.follow_timer.start()
        
    def hide_tooltip(self):
        """Hide the tooltip and stop the follow timer"""
        self.follow_timer.stop()
        self.hide()
        
    def follow_cursor(self):
        """Update tooltip position to follow cursor"""
        if self.isVisible():
            cursor_pos = QCursor.pos()
            offset_position = cursor_pos + QPoint(PlotConstants.TOOLTIP_OFFSET_X, PlotConstants.TOOLTIP_OFFSET_Y)
            self.move(offset_position)