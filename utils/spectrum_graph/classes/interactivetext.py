import logging
import pyqtgraph as pg
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QCursor
import re

logger = logging.getLogger(__name__)


class InteractiveTextItem(pg.TextItem):
    def __init__(self, text, color, peak_coord, leader_line, viewer, **kwargs):
        super().__init__(text, color=color, **kwargs)
        self.peak_coord = peak_coord
        self.leader_line = leader_line
        self.viewer = viewer
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self.leader_line is not None:
                newPos = value
                self.leader_line.setData(
                    x=[self.peak_coord[0], newPos.x()],
                    y=[self.peak_coord[1], newPos.y()],
                )
        return super().itemChange(change, value)


class EnhancedInteractiveTextItem(pg.TextItem):
    """Enhanced interactive text item with movable straight leader line.

    Left-click + drag   → move this label only (or all selected labels together).
    Shift + left-click  → toggle this label into/out of the viewer''s multi-selection
                          set (highlighted in blue).  Dragging any label in the
                          selection moves ALL selected labels by the same delta.
    """

    _SELECTED_BG = "rgba(77,171,247,0.30)"
    _SELECTED_BORDER = "#4dabf7"

    def __init__(
        self, text, color, peak_coord, leader_line, viewer, fragment_data=None, **kwargs
    ):
        super().__init__(text, color=color, **kwargs)
        self.peak_coord = peak_coord
        self.leader_line = leader_line
        self.viewer = viewer
        self.fragment_data = fragment_data or {}

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self.is_dragging = False
        self._drag_start_pos: QPointF | None = None

        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            viewbox.sigRangeChanged.connect(self._on_view_transform)
        except Exception as e:
            logger.warning("Could not connect to view transform: %s", e)

    # ------------------------------------------------------------------
    # Multi-selection helpers
    # ------------------------------------------------------------------

    def _selection_set(self) -> set:
        """Return (and lazily create) the viewer-level selected-labels set."""
        if self.viewer is not None:
            if not hasattr(self.viewer, "_selected_annotation_items"):
                self.viewer._selected_annotation_items = set()
            return self.viewer._selected_annotation_items
        return set()

    def _is_in_selection(self) -> bool:
        return self in self._selection_set()

    def _apply_selection_style(self, selected: bool) -> None:
        """Draw/remove a blue background to indicate multi-selection membership."""
        try:
            if selected:
                # Store the current rendered HTML so we can restore it
                self._original_html_sel = self.toHtml() if hasattr(self, "toHtml") else ""
                font_size = (
                    getattr(self.viewer, "annotation_font_size", 14)
                    if self.viewer
                    else 14
                )
                plain = self.toPlainText()
                super().setHtml(
                    f'<span style="background-color:{self._SELECTED_BG};'
                    f'border:1px solid {self._SELECTED_BORDER};'
                    f'font-size:{font_size}px;">{plain}</span>'
                )
            else:
                # Prefer the stored snapshot; fall back to the annotation HTML
                # that was set when the item was created (_html_annotation), and
                # ultimately to the plain text.  The `if original:` guard was
                # wrong because an empty string is falsy.
                original = getattr(self, "_original_html_sel", None)
                if original is not None and original != "":
                    super().setHtml(original)
                elif hasattr(self, "_html_annotation") and self._html_annotation:
                    super().setHtml(self._html_annotation)
                else:
                    # Last resort: re-render as plain text with the correct colour
                    super().setText(self.toPlainText())
                self._original_html_sel = None
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setHtml(self, html):
        """Override setHtml to ensure proper formatting."""
        if html and isinstance(html, str):
            super().setHtml(html)
        else:
            super().setText(str(html) if html else "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_view_transform(self):
        """Update leader line when view transforms (zoom/pan)."""
        if not self.is_dragging:
            try:
                current_pos = self.pos()
                self._update_leader_line_simple(current_pos.x(), current_pos.y())
            except Exception:
                pass

    def itemChange(self, change, value):
        """Constrain position, update leader line, and batch-move selected labels."""
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
            and self.is_dragging
        ):
            new_pos = value

            # Constrain to visible graph bounds
            try:
                viewbox = self.viewer.spectrumplot.getViewBox()
                view_range = viewbox.viewRange()
                x_min, x_max = view_range[0]
                y_min, y_max = view_range[1]
                margin_x = (x_max - x_min) * 0.02
                margin_y = (y_max - y_min) * 0.02
                clamped_x = max(x_min + margin_x, min(new_pos.x(), x_max - margin_x))
                clamped_y = max(y_min + margin_y, min(new_pos.y(), y_max - margin_y))
                new_pos = QPointF(clamped_x, clamped_y)
                value = new_pos
            except Exception:
                pass

            self._update_leader_line_simple(new_pos.x(), new_pos.y())

            # Batch-move all other selected labels by the same delta
            sel = self._selection_set()
            if (
                len(sel) > 1
                and self._is_in_selection()
                and not getattr(self.viewer, "_batch_moving", False)
                and self._drag_start_pos is not None
            ):
                delta = QPointF(
                    new_pos.x() - self._drag_start_pos.x(),
                    new_pos.y() - self._drag_start_pos.y(),
                )
                if self.viewer is not None:
                    self.viewer._batch_moving = True
                try:
                    for other in sel:
                        if (
                            other is not self
                            and isinstance(other, EnhancedInteractiveTextItem)
                            and other._drag_start_pos is not None
                        ):
                            target = QPointF(
                                other._drag_start_pos.x() + delta.x(),
                                other._drag_start_pos.y() + delta.y(),
                            )
                            other.setPos(target)
                            other._update_leader_line_simple(target.x(), target.y())
                finally:
                    if self.viewer is not None:
                        self.viewer._batch_moving = False

        return super().itemChange(change, value)

    def _update_leader_line_simple(self, label_x, label_y):
        """Update the straight leader line from the peak top to the text label."""
        peak_mz, peak_intensity = self.peak_coord
        font_size = getattr(self.viewer, "annotation_font_size", 14)
        rotation_angle = self.rotation()
        text_width = self._estimate_text_width()

        if abs(rotation_angle - 90) < 5:
            if label_y < peak_intensity:
                connection_x = label_x + (font_size * 0.5)
                connection_y = label_y + (font_size * 0.3)
            else:
                connection_x = label_x + (font_size * 0.5)
                connection_y = label_y - (font_size * 0.3)
        elif abs(rotation_angle + 90) < 5:
            if label_y < peak_intensity:
                connection_x = label_x - (font_size * 0.5)
                connection_y = label_y + (font_size * 0.3)
            else:
                connection_x = label_x - (font_size * 0.5)
                connection_y = label_y - (font_size * 0.3)
        else:
            text_height = self._estimate_text_height()
            connection_x = max(label_x, min(peak_mz, label_x + text_width))
            if peak_intensity < label_y:
                connection_y = label_y - (text_height / 2.0)
            else:
                connection_y = label_y + (text_height / 2.0)

        if self.leader_line is not None:
            self.leader_line.setData(
                x=[peak_mz, connection_x], y=[peak_intensity, connection_y]
            )

    def _estimate_text_width(self):
        """Estimate text width based on actual rendered bounds or character count."""
        try:
            scene_rect = self.sceneBoundingRect()
            viewbox = self.viewer.spectrumplot.getViewBox()
            top_left = viewbox.mapSceneToView(scene_rect.topLeft())
            bottom_right = viewbox.mapSceneToView(scene_rect.bottomRight())
            actual_width = abs(bottom_right.x() - top_left.x())
            if actual_width > 0:
                return actual_width
        except Exception:
            pass

        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            view_rect = viewbox.viewRect()
            scene_rect = viewbox.sceneBoundingRect()
            zoom_factor = (
                view_rect.width() / scene_rect.width()
                if scene_rect.width() > 0
                else 1.0
            )
        except Exception:
            zoom_factor = 1.0

        font_size = getattr(self.viewer, "annotation_font_size", 14)
        char_width = font_size * 0.6 * zoom_factor
        try:
            text_content = self.toPlainText() if hasattr(self, "toPlainText") else ""
            if not text_content:
                html_text = self.toHtml() if hasattr(self, "toHtml") else ""
                if html_text:
                    text_content = re.sub("<[^<]+?>", "", html_text)
            char_count = len(text_content) if text_content else 3
            return char_count * char_width
        except Exception:
            return 3 * char_width

    def _estimate_text_height(self):
        """Estimate text height in data coordinates using rendered bounding rect."""
        try:
            scene_rect = self.sceneBoundingRect()
            viewbox = self.viewer.spectrumplot.getViewBox()
            top_left = viewbox.mapSceneToView(scene_rect.topLeft())
            bottom_right = viewbox.mapSceneToView(scene_rect.bottomRight())
            actual_height = abs(top_left.y() - bottom_right.y())
            if actual_height > 0:
                return actual_height
        except Exception:
            pass

        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            view_rect = viewbox.viewRect()
            scene_rect = viewbox.sceneBoundingRect()
            y_zoom = (
                view_rect.height() / scene_rect.height()
                if scene_rect.height() > 0
                else 1.0
            )
        except Exception:
            y_zoom = 1.0
        font_size = getattr(self.viewer, "annotation_font_size", 14)
        return font_size * y_zoom

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Shift/Ctrl+click toggles multi-selection; plain left-click starts a drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & (
                Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
            ):
                sel = self._selection_set()
                if self in sel:
                    sel.discard(self)
                    self._apply_selection_style(False)
                else:
                    sel.add(self)
                    self._apply_selection_style(True)
                event.accept()
                return

            self.is_dragging = True
            self._drag_start_pos = self.pos()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

            # Snapshot start positions for all co-selected labels
            for item in self._selection_set():
                if isinstance(item, EnhancedInteractiveTextItem):
                    item._drag_start_pos = item.pos()

            if self.viewer and hasattr(self.viewer, "annotation_dragging"):
                self.viewer.annotation_dragging = True
                if hasattr(self.viewer, "persistent_tooltip"):
                    self.viewer.persistent_tooltip.hide_tooltip()
                if hasattr(self.viewer, "_clear_current_peak"):
                    self.viewer._clear_current_peak()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Only propagate movement when we explicitly started a drag.

        Without this guard, Qt's ItemIsMovable flag causes the item to move
        on ANY mouse-press/move sequence — even Shift/Ctrl clicks that are
        meant only for selection toggling.
        """
        if self.is_dragging:
            super().mouseMoveEvent(event)
        # Intentionally do NOT call super() when not dragging so Qt's built-in
        # ItemIsMovable mechanism cannot accidentally move this item.

    def mouseReleaseEvent(self, event):
        """Stop dragging and re-enable peak highlighting."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self._drag_start_pos = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

            if self.viewer and hasattr(self.viewer, "annotation_dragging"):
                self.viewer.annotation_dragging = False

            current_pos = self.pos()
            self._update_leader_line_simple(current_pos.x(), current_pos.y())

            # Clear drag snapshots on all selected items
            for item in self._selection_set():
                if isinstance(item, EnhancedInteractiveTextItem):
                    item._drag_start_pos = None

        super().mouseReleaseEvent(event)

    def hoverEnterEvent(self, event):
        """Highlight on hover; suppress if label is already selected."""
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

        if self.viewer and self.fragment_data:
            fragment_sequence = self.fragment_data.get("fragment_sequence")
            if fragment_sequence and hasattr(self.viewer, "highlight_peptide_sequence"):
                self.viewer.highlight_peptide_sequence(fragment_sequence)
            base_type = self.fragment_data.get("base_type")
            position = self.fragment_data.get("position")
            if base_type and position and hasattr(self.viewer, "highlight_fragment_line"):
                self.viewer.highlight_fragment_line(position, base_type)

        if not self._is_in_selection():
            self._apply_hover_style(True)

        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Reset highlighting on leave; keep selection style if still selected."""
        if not self.is_dragging:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            if self.viewer:
                if hasattr(self.viewer, "reset_peptide_highlighting"):
                    self.viewer.reset_peptide_highlighting()
                if hasattr(self.viewer, "reset_fragment_line_highlighting"):
                    self.viewer.reset_fragment_line_highlighting()

        if not self._is_in_selection():
            self._apply_hover_style(False)

        super().hoverLeaveEvent(event)

    def _apply_hover_style(self, is_hovered):
        """Apply or remove yellow hover highlight on the text annotation."""
        try:
            if is_hovered:
                if not getattr(self, "_original_html", None):
                    self._original_html = self.toHtml() if hasattr(self, "toHtml") else ""
                font_size = (
                    getattr(self.viewer, "annotation_font_size", 14)
                    if self.viewer
                    else 14
                )
                super().setHtml(
                    f'<span style="font-weight:bold;background-color:rgba(255,255,0,0.3);'
                    f'font-size:{font_size + 2}px;">{self.toPlainText()}</span>'
                )
            else:
                if getattr(self, "_original_html", None):
                    super().setHtml(self._original_html)
                    self._original_html = None
        except Exception:
            pass
