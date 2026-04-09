from PyQt6.QtWidgets import QWidget, QLabel, QGridLayout, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation
from utils.style.style import EditorConstants
class QToaster(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create and style the notification widget
        self.setupUi()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Position at the bottom of the parent
        if self.parent() is not None:
            self.setMinimumWidth(200)
            self.setMaximumWidth(self.parent().width())
            
    def setupUi(self):
        self.gridLayout = QGridLayout(self)
        self.gridLayout.setContentsMargins(4, 4, 4, 4)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {EditorConstants.WHITE()};
                background-color: {EditorConstants.GRAY_600()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_500(), EditorConstants.BORDER_WIDTH_FOCUS(), EditorConstants.BORDER_RADIUS_LARGE())}
                padding: {EditorConstants.PADDING_LARGE()} {EditorConstants.PADDING_XL()};
                margin: 0px;
                {EditorConstants.get_font_string("bold")}
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
            }}
        """)
        self.gridLayout.addWidget(self.label)

    def show_message(self, message: str, duration: int = 2000):
        """Show a toast message with optional duration"""
        self.label.setText(message)
        
        # Position the toast at the bottom center of the parent
        if self.parent() is not None:
            self.adjustSize()
            pos_x = self.parent().width() // 2 - self.width() // 2
            pos_y = self.parent().height() - self.height() - 50
            self.move(pos_x, pos_y)
        
        self.show()
        
        # Create fade out animation
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        
        self.anim = QPropertyAnimation(self.effect, b"opacity")
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setDuration(500)  # 500ms fade out
        
        QTimer.singleShot(int(duration), self.start_fade_out)
        
    def start_fade_out(self):
        self.anim.start()
        self.anim.finished.connect(self.hide)