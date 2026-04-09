# amino_acid_text_item.py
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer

from utils.style.style import EditorConstants
from ..config.constants import PlotConstants


class AminoAcidTextItem(pg.TextItem):
    """Custom text item for amino acids that handles hover and right-click"""

    def __init__(self, text, position, parent_widget, **kwargs):
        super().__init__(text, **kwargs)
        self.position = position
        self.parent_widget = parent_widget
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self._hover_emphasized = False
        self._temp_emphasized = False  # For right-click context menu
        self.is_hovered = False
        # Don't store original_color - always get it dynamically from theme
        self.hover_color = 'blue'
        self.char = text if text else None
        self.setAcceptHoverEvents(True)

    def apply_hover_emphasis(self, scale: float = 1.25):
        """Apply hover emphasis when mouse enters (separate from temporary emphasis)"""
        if getattr(self, "_hover_emphasized", False):
            return
        if getattr(self, "_temp_emphasized", False):
            return  # Don't override temporary emphasis

        char = getattr(self, "char", "")
        if not char:
            char = ""

        font_size = self.parent_widget._calculate_font_size(PlotConstants.PEPTIDE_FONT_SIZE, scale)
        color = self.hover_color if hasattr(self, "hover_color") else "blue"

        super().setHtml(f'<span style="font-weight:bold; color:{color}; font-size:{font_size}px;">{char}</span>')
        self._hover_emphasized = True

    def remove_hover_emphasis(self):
        """Remove hover emphasis when mouse leaves (separate from temporary emphasis)"""
        if not getattr(self, "_hover_emphasized", False):
            return
        if getattr(self, "_temp_emphasized", False):
            return  # Don't remove if we have temporary emphasis

        # Directly restore with theme-aware color instead of using cached HTML
        self._restore_normal_formatting()
        self._hover_emphasized = False

    def apply_temporary_emphasis(self, scale: float = 1.35):
        """Apply temporary emphasis for right-click context menu (stays until menu closes)"""
        if getattr(self, "_temp_emphasized", False):
            return

        char = getattr(self, "char", "")
        if not char:
            char = ""

        font_size = self.parent_widget._calculate_font_size(PlotConstants.PEPTIDE_FONT_SIZE, scale)
        color = self.hover_color if hasattr(self, "hover_color") else "blue"

        super().setHtml(f'<span style="font-weight:bold; color:{color}; font-size:{font_size}px;">{char}</span>')
        self._temp_emphasized = True

        # Remove hover emphasis since we now have temporary emphasis
        self._hover_emphasized = False

    def remove_temporary_emphasis(self):
        """Remove temporary emphasis after context menu closes"""
        if not getattr(self, "_temp_emphasized", False):
            return

        # Directly restore with theme-aware color
        self._restore_normal_formatting()
        self._temp_emphasized = False

        # If mouse is still hovering, reapply hover emphasis
        if self.is_hovered:
            QTimer.singleShot(10, lambda: self.apply_hover_emphasis(scale=1.25))

    def _restore_normal_formatting(self):
        """Helper to restore normal formatting with theme-aware color"""
        char = getattr(self, "char", "")
        font_size = self.parent_widget._calculate_font_size(PlotConstants.PEPTIDE_FONT_SIZE)
        # Always get the CURRENT theme color, not the stored original
        color = EditorConstants.TEXT_COLOR()
        super().setHtml(f'<span style="font-weight:bold; color:{color}; font-size:{font_size}px;">{char}</span>')

    def hoverEnterEvent(self, event):
        """Handle mouse enter - apply hover emphasis"""
        self.is_hovered = True
        if not self.parent_widget or self not in getattr(self.parent_widget, 'highlight_items', []):
            # Always use the proper emphasis method
            self.apply_hover_emphasis(scale=1.25)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Handle mouse leave - remove hover emphasis"""
        self.is_hovered = False
        if not self.parent_widget or self not in getattr(self.parent_widget, 'highlight_items', []):
            # Always use the proper formatting restoration method
            self.remove_hover_emphasis()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Handle right-click for context menu only when hovering over letter"""
        if event.button() == Qt.MouseButton.RightButton and self.is_hovered:
            self.parent_widget.show_amino_acid_context_menu(self.position, event)
            event.accept()
        else:
            super().mousePressEvent(event)
