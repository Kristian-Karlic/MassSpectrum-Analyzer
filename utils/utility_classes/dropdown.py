from PyQt6.QtCore import pyqtSignal, QEvent, QCoreApplication, QPoint
from PyQt6.QtGui import QKeyEvent

from PyQt6.QtWidgets import (QWidget, QHBoxLayout,QLineEdit,  QSizePolicy, QToolButton, QListWidget, QListWidgetItem, QApplication
)
from PyQt6.QtCore import Qt
import logging

logger = logging.getLogger(__name__)

class SearchableDropdown(QWidget):
    """A small widget: QLineEdit + popup QListWidget that supports typing to filter and clicking to select.
    Popup closes when user clicks anywhere outside it (including other GUI widgets or the down-arrow button).
    """
    item_selected = pyqtSignal(object)  # emits the item data (any python object)

    def __init__(self, placeholder: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.line = QLineEdit()
        self.line.setPlaceholderText(placeholder)
        self.line.setClearButtonEnabled(True)
        self.button = QToolButton()
        self.button.setArrowType(Qt.ArrowType.DownArrow)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.line)
        layout.addWidget(self.button)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Popup list
        self.popup = QListWidget()
        # Make it a popup window but avoid stealing focus from the line edit
        self.popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Show popup without activating window so the line edit keeps keyboard focus
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.popup.setUniformItemSizes(True)
        self.popup.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._items = []  # list of tuples (display_text, data)

        # Ensure popup doesn't steal keys: install event filter
        self.popup.installEventFilter(self)

        # Install app-level event filter so clicks outside close the popup
        self._app = QApplication.instance()
        if self._app:
            self._app.installEventFilter(self)

        # Connections
        self.line.textChanged.connect(self._on_text_changed)
        self.button.clicked.connect(self._toggle_popup)
        self.popup.itemClicked.connect(self._on_item_clicked)
        self.line.returnPressed.connect(self._on_return_pressed)
        self._last_filter = ""

    def eventFilter(self, obj, event):
        # Forward key presses from popup back to the line edit so typing continues
        if obj is self.popup and event.type() == QEvent.Type.KeyPress:
            text = event.text()
            forwarding_keys = {
                Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
                Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Tab,
                Qt.Key.Key_Return, Qt.Key.Key_Enter
            }
            if text or event.key() in forwarding_keys:
                evt = QKeyEvent(event.type(), event.key(), event.modifiers(), event.text())
                QCoreApplication.postEvent(self.line, evt)
                return True

        # Global app mouse press -> close popup if click outside this widget and popup
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.popup.isVisible():
                # Global mouse position as QPoint
                try:
                    global_pos = event.globalPosition().toPoint()
                except Exception:
                    # Fallback for older PyQt versions
                    global_pos = QPoint(int(event.globalX()), int(event.globalY()))

                # If click inside popup, let popup handle it
                if self.popup.geometry().contains(global_pos):
                    return False
                # If click inside this widget (line or button), let widget handle it
                if self.geometry().contains(self.mapFromGlobal(global_pos)):
                    return False
                # Otherwise, user clicked elsewhere -> hide popup but do not eat the event
                self.popup.hide()
                # keep line focused so user can continue typing after closing
                self.line.setFocus()
                return False

        return super().eventFilter(obj, event)

    def set_items(self, items):
        """items: list of (display_text, data) - FIXED to work with existing structure"""
        try:
            self._items = list(items)  # Store items correctly
            self._refresh_popup(full=True)
            logger.debug(f"SearchableDropdown updated with {len(items)} items")
        except Exception as e:
            logger.error(f"Failed to set SearchableDropdown items: {e}")

    def clear_items(self):
        """Clear all items from the dropdown - FIXED to work with existing structure"""
        try:
            self._items.clear()  # Clear the correct attribute
            self.popup.clear()   # Clear the popup
            logger.debug("SearchableDropdown cleared")
        except Exception as e:
            logger.error(f"Failed to clear SearchableDropdown items: {e}")

    def clear(self):
        self.line.clear()
        self._items = []
        self.popup.clear()

    def _refresh_popup(self, full=False):
        """(re)populate popup. If full=True repopulate from _items; otherwise keep existing items and filter"""
        self.popup.clear()
        for text, data in self._items:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, data)
            self.popup.addItem(it)
        # Prevent auto-selection of the first item
        self.popup.setCurrentRow(-1)
        self.popup.clearSelection()

    def _on_text_changed(self, text):
        text_lower = text.lower().strip()
        self._last_filter = text_lower
        # filter items by hiding non-matching items
        if not text_lower:
            self._refresh_popup(full=True)
        else:
            self.popup.clear()
            for display, data in self._items:
                if text_lower in display.lower():
                    it = QListWidgetItem(display)
                    it.setData(Qt.ItemDataRole.UserRole, data)
                    self.popup.addItem(it)
            # Prevent auto-selection after filtering
            self.popup.setCurrentRow(-1)
            self.popup.clearSelection()

        # Show popup if there are any matches (do NOT steal focus)
        if self.popup.count() > 0:
            self.showPopup()
            # Ensure the line edit keeps focus so the user can continue typing
            self.line.setFocus()
            # Keep cursor at end
            self.line.setCursorPosition(len(self.line.text()))
        else:
            self.popup.hide()
            self.line.setFocus()

    def _toggle_popup(self):
        """Toggle popup visibility when button clicked"""
        if self.popup.isVisible():
            self.popup.hide()
            self.line.setFocus()
        else:
            # If popup empty but items exist, populate all
            if self.popup.count() == 0 and self._items:
                self._refresh_popup(full=True)
            if self.popup.count() == 0:
                return
            self.showPopup()
            # focus line for typing
            self.line.setFocus()
            self.line.setCursorPosition(len(self.line.text()))

    def showPopup(self):
        if self.popup.count() == 0 and self._items:
            # populate all if empty
            self._refresh_popup(full=True)
        if self.popup.count() == 0:
            return
        # position popup under the widget
        p = self.mapToGlobal(self.rect().bottomLeft())
        p.setY(p.y() + 1)
        self.popup.setMinimumWidth(self.width())
        self.popup.move(p)
        self.popup.show()
        self.popup.raise_()
        # Keep the line edit focused so typing continues
        self.line.setFocus()
        self.line.setCursorPosition(len(self.line.text()))
        # Ensure no item is pre-selected
        self.popup.setCurrentRow(-1)
        self.popup.clearSelection()

    def _on_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        self.popup.hide()
        # keep the line edit clear and focused so user can continue typing after selection
        self.line.clear()
        self.line.setFocus()
        self.item_selected.emit(data)

    def _on_return_pressed(self):
        # If user presses Enter and popup has exactly one item, select it
        if self.popup.count() == 1:
            item = self.popup.item(0)
            self._on_item_clicked(item)