

from PyQt6.QtWidgets import (
    QLayout, QWidget, QSizePolicy,
    QMenuBar, QMenu, QSpinBox, QLabel, QHBoxLayout
)
from PyQt6.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QAction, QFontMetrics, QCursor
from typing import Dict, Callable, Optional
from utils.style.style import EditorConstants


def get_main_window(widget, stop_attr='extracted_spectral_data'):
    """Walk parent chain to find the main application window.

    Args:
        widget: Starting QWidget to walk up from.
        stop_attr: Attribute name to look for on the parent (e.g. 'extracted_spectral_data',
                   'mass_spec_viewer'). The first parent that has this attribute is returned.

    Returns:
        The parent widget with the specified attribute, or None.
    """
    parent = widget.parent()
    while parent:
        if hasattr(parent, stop_attr):
            return parent
        parent = parent.parent()
    return None


class FlowLayout(QLayout):
    """Layout that arranges items left-to-right, wrapping to the next row."""

    def __init__(self, parent=None, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            item_size = item.sizeHint()
            next_x = x + item_size.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and row_height > 0:
                x = effective.x()
                y = y + row_height + self._v_spacing
                next_x = x + item_size.width() + self._h_spacing
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            row_height = max(row_height, item_size.height())

        return y + row_height - rect.y() + m.bottom()


class IonTile(QWidget):
    """Clickable tile widget with QCheckBox-compatible API."""

    stateChanged = pyqtSignal(int)

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._checked = False
        self._hovered = False
        self._text = text
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._label = QLabel(text, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(0)
        layout.addWidget(self._label)

        self._update_style()

    # --- QCheckBox-compatible API ---

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self._update_style()
            if not self.signalsBlocked():
                self.stateChanged.emit(
                    Qt.CheckState.Checked.value if checked else Qt.CheckState.Unchecked.value
                )

    def checkState(self) -> Qt.CheckState:
        return Qt.CheckState.Checked if self._checked else Qt.CheckState.Unchecked

    def setCheckState(self, state: Qt.CheckState):
        self.setChecked(state == Qt.CheckState.Checked)

    def text(self) -> str:
        return self._text

    def setText(self, text: str):
        self._text = text
        self._label.setText(text)
        self.updateGeometry()

    # --- Visual ---

    def _update_style(self):
        if self._checked:
            if self._hovered:
                bg = EditorConstants.TILE_SELECTED_HOVER()
            else:
                bg = EditorConstants.TILE_SELECTED_BG()
            border = EditorConstants.TILE_SELECTED_BORDER()
        else:
            if self._hovered:
                bg = EditorConstants.TILE_UNSELECTED_HOVER()
            else:
                bg = EditorConstants.TILE_UNSELECTED_BG()
            border = EditorConstants.TILE_UNSELECTED_BORDER()

        text_color = EditorConstants.TEXT_COLOR()
        font_str = EditorConstants.get_font_string()
        self.setStyleSheet(f"""
            IonTile {{
                background-color: {bg};
                border: 1.5px solid {border};
                border-radius: 4px;
            }}
        """)
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                background: transparent;
                {font_str}
                font-size: {EditorConstants.CHECKBOX_FONT_SIZE()}px;
            }}
        """)

    # --- Events ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._update_style()
        super().leaveEvent(event)

    # --- Sizing ---

    def sizeHint(self):
        fm = QFontMetrics(self._label.font())
        text_width = fm.horizontalAdvance(self._label.text())
        m = self.layout().contentsMargins()
        # Account for HTML text being wider than plain metric
        if '<' in self._label.text():
            text_width = self._label.sizeHint().width()
        width = max(36, text_width + m.left() + m.right() + 4)
        height = max(28, fm.height() + m.top() + m.bottom() + 4)
        return QSize(width, height)


class WidgetFactory:
    """Utility class for creating common PyQt6 widgets with consistent styling"""
    
    @staticmethod
    def create_labeled_spinbox(label_text, min_value, max_value, default_value, parent, 
                              spinbox_width=None, max_total_width=None):
        """Create a labeled spinbox that fits within container constraints with proper sizing"""
        layout = QHBoxLayout()
        layout.setSpacing(8)  
        
        # Create label with constrained width
        label = QLabel(label_text)
        label.setWordWrap(True)  
        if max_total_width:
            label_width = min(120, max_total_width // 2) 
            label.setMaximumWidth(label_width)
        
        # CONTROL LABEL TEXT SIZE HERE:
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 12px;  /* Change label text size */
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
        """)
        
        # Set minimum height for label to match spinbox
        label.setMinimumHeight(EditorConstants.EDITOR_MIN_HEIGHT())
        layout.addWidget(label)
        
        # Create spinbox with better sizing
        spinbox = QSpinBox(parent)
        spinbox.setMinimum(min_value)
        spinbox.setMaximum(max_value)
        spinbox.setValue(default_value)
        
        # CONTROL SPINBOX SIZE HERE:
        spinbox.setMinimumHeight(32)  # Change spinbox height
        
        if spinbox_width:
            spinbox.setMinimumWidth(min(50, spinbox_width))
            spinbox.setMaximumWidth(spinbox_width)
        elif max_total_width:
            remaining_width = max_total_width - (label.maximumWidth() + 20)
            spinbox.setMaximumWidth(max(100, remaining_width))  # Change minimum width
            spinbox.setMinimumWidth(100)  # Change minimum width
        else:
            spinbox.setMinimumWidth(100)  # Change default width

        # CONTROL SPINBOX TEXT SIZE HERE:
        custom_style = f"""
            QSpinBox {{
                font-size: 14px;  /* Change spinbox text size */
                min-height: 32px;  /* Change spinbox height */
                {EditorConstants.get_spinbox_style()}
            }}
        """
        spinbox.setStyleSheet(custom_style)
        
        layout.addWidget(spinbox)
        layout.addStretch()
        
        return layout, spinbox
    
    @staticmethod
    def create_checkbox_grid(
            parent,
            parent_layout: QLayout,
            labels: list[str],
            columns: int = 6,
            max_width: int = None,
            label_formatter: Optional[Callable[[str], str]] = None
        ) -> Dict[str, "IonTile"]:
        """
        Creates a flow layout of IonTile widgets that fits within the container width.
        Optionally formats the visible label text (e.g., add chemical subscripts).
        Returns a dict keyed by the original (raw) label.
        """
        grid_widget = QWidget()
        grid_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if max_width:
            grid_widget.setMaximumWidth(max_width)

        flow = FlowLayout(grid_widget, h_spacing=6, v_spacing=6)
        flow.setContentsMargins(5, 5, 5, 5)

        tiles: Dict[str, IonTile] = {}

        for raw_label in labels:
            display_label = label_formatter(raw_label) if label_formatter else raw_label

            tile = IonTile(display_label, parent=grid_widget)
            tile.setToolTip(raw_label)
            tile.setProperty('raw_label', raw_label)

            tiles[raw_label] = tile
            flow.addWidget(tile)

        parent_layout.addWidget(grid_widget)
        return tiles
    
    @staticmethod
    def create_menu_action(
            parent,
            menu: QMenuBar | QMenu,
            text: str,
            tooltip: str,
            callback: Callable) -> QAction:
        """
        Creates a QAction with given text, tooltip, and callback,
        and adds it to the specified menu.
        
        Args:
            parent: Parent widget for the QAction
            menu: QMenuBar or QMenu to add the action to
            text: Text to display for the action
            tooltip: Tooltip text for the action
            callback: Function to call when action is triggered
            
        Returns:
            QAction: The created menu action
        """
        action = QAction(text, parent)
        action.setToolTip(tooltip)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action
                
