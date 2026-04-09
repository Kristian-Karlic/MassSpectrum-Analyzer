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
                    y=[self.peak_coord[1], newPos.y()]
                )
        return super().itemChange(change, value)
    
    
class EnhancedInteractiveTextItem(pg.TextItem):
    """Enhanced interactive text item with movable straight leader line"""
    
    def __init__(self, text, color, peak_coord, leader_line, viewer, fragment_data=None, **kwargs):
        super().__init__(text, color=color, **kwargs)
        self.peak_coord = peak_coord
        self.leader_line = leader_line
        self.viewer = viewer
        
        # Store fragment data for hover highlighting
        # fragment_data should contain: fragment_sequence, base_type, ion_number, position
        self.fragment_data = fragment_data or {}
        
        # Enable dragging
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        
        # Enable hover events
        self.setAcceptHoverEvents(True)
        
        # Track dragging state
        self.is_dragging = False
        
        # Connect to view transform changes to update leader line on zoom/pan
        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            viewbox.sigRangeChanged.connect(self._on_view_transform)
        except Exception as e:
            logger.warning("Could not connect to view transform: %s", e)

    def setHtml(self, html):
        """Override setHtml to ensure proper formatting"""
        if html and isinstance(html, str):
            super().setHtml(html)
        else:
            # Fallback to plain text if HTML is invalid
            super().setText(str(html) if html else "")

    def _on_view_transform(self):
        """Update leader line when view transforms (zoom/pan)"""
        if not self.is_dragging:
            try:
                current_pos = self.pos()
                self._update_leader_line_simple(current_pos.x(), current_pos.y())
            except Exception as e:
                pass  # Silently ignore errors during rapid transforms
    
    def itemChange(self, change, value):
        """Handle item position changes to update leader line and constrain to view bounds"""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.is_dragging:
            new_pos = value
            
            # Constrain position to within the visible graph bounds
            try:
                viewbox = self.viewer.spectrumplot.getViewBox()
                view_range = viewbox.viewRange()
                x_min, x_max = view_range[0]
                y_min, y_max = view_range[1]
                
                # Add small margin to keep label fully visible
                margin_x = (x_max - x_min) * 0.02
                margin_y = (y_max - y_min) * 0.02
                
                # Clamp position within bounds
                clamped_x = max(x_min + margin_x, min(new_pos.x(), x_max - margin_x))
                clamped_y = max(y_min + margin_y, min(new_pos.y(), y_max - margin_y))
                
                # Create new clamped position
                new_pos = QPointF(clamped_x, clamped_y)
                value = new_pos
            except Exception as e:
                pass  # If we can't get view bounds, allow unrestricted movement
            
            self._update_leader_line_simple(new_pos.x(), new_pos.y())
        
        return super().itemChange(change, value)

    def _update_leader_line_simple(self, label_x, label_y):
        """
        Update simple straight line from peak top to text label.
        Handles rotation properly - attaches from top for high-intensity labels, bottom for normal.
        """
        peak_mz, peak_intensity = self.peak_coord
        
        # Get font size for positioning calculations
        font_size = getattr(self.viewer, 'annotation_font_size', 14)
        
        # Get rotation angle
        rotation_angle = self.rotation()
        
        # Calculate text dimensions
        text_width = self._estimate_text_width()
        
        # Adjust connection point based on rotation
        if abs(rotation_angle - 90) < 5:  # 90-degree rotation (vertical text)
            # Check if label is at high intensity (side placement) or above peak
            # High intensity labels (>90) are placed to the side, so attach from top
            # Lower intensity labels are above the peak, so attach from bottom
            if label_y < peak_intensity:  # Label is to the side (high intensity peak)
                # Connect to top of rotated text - much closer
                connection_x = label_x + (font_size * 0.5)  # Offset to right edge
                connection_y = label_y + (font_size * 0.3)  # Just above label position
            else:  # Label is above peak (normal intensity)
                # Connect to bottom of rotated text
                connection_x = label_x + (font_size * 0.5)  # Offset to right edge
                connection_y = label_y - (font_size * 0.3)  # Just below label position
        elif abs(rotation_angle + 90) < 5:  # -90-degree rotation
            if label_y < peak_intensity:
                connection_x = label_x - (font_size * 0.5)
                connection_y = label_y + (font_size * 0.3)
            else:
                connection_x = label_x - (font_size * 0.5)
                connection_y = label_y - (font_size * 0.3)
        else:  # No rotation or other angles (horizontal text)
            # Connection point at the nearest border of the text bounding box
            text_height = self._estimate_text_height()
            connection_x = max(label_x, min(peak_mz, label_x + text_width))
            if peak_intensity < label_y:
                connection_y = label_y - (text_height / 2.0)  # Bottom border
            else:
                connection_y = label_y + (text_height / 2.0)  # Top border
        
        # Update the single leader line from peak top to text
        if self.leader_line is not None:
            self.leader_line.setData(
                x=[peak_mz, connection_x],
                y=[peak_intensity, connection_y]
            )
    
    def _estimate_text_width(self):
        """Estimate text width based on actual rendered bounds or character count"""
        try:
            # Try to get actual rendered text bounds
            scene_rect = self.sceneBoundingRect()
            viewbox = self.viewer.spectrumplot.getViewBox()
            top_left = viewbox.mapSceneToView(scene_rect.topLeft())
            bottom_right = viewbox.mapSceneToView(scene_rect.bottomRight())
            actual_width = abs(bottom_right.x() - top_left.x())
            
            if actual_width > 0:
                return actual_width
        except Exception:
            pass
        
        # Fallback: estimate based on font size and character count
        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            view_rect = viewbox.viewRect()
            scene_rect = viewbox.sceneBoundingRect()
            zoom_factor = view_rect.width() / scene_rect.width() if scene_rect.width() > 0 else 1.0
        except Exception:
            zoom_factor = 1.0
        
        font_size = getattr(self.viewer, 'annotation_font_size', 14)
        char_width = font_size * 0.6 * zoom_factor
        
        # Get text content
        try:
            text_content = self.toPlainText() if hasattr(self, 'toPlainText') else ""
            if not text_content:
                html_text = self.toHtml() if hasattr(self, 'toHtml') else ""
                if html_text:
                    text_content = re.sub('<[^<]+?>', '', html_text)
            
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

        # Fallback: estimate from font size and y-axis zoom
        try:
            viewbox = self.viewer.spectrumplot.getViewBox()
            view_rect = viewbox.viewRect()
            scene_rect = viewbox.sceneBoundingRect()
            y_zoom = view_rect.height() / scene_rect.height() if scene_rect.height() > 0 else 1.0
        except Exception:
            y_zoom = 1.0
        font_size = getattr(self.viewer, 'annotation_font_size', 14)
        return font_size * y_zoom

    def mousePressEvent(self, event):
        """Handle mouse press to start dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            # Notify viewer to disable peak highlighting during drag
            if self.viewer and hasattr(self.viewer, 'annotation_dragging'):
                self.viewer.annotation_dragging = True
                # Also hide any current tooltip and clear peak highlighting
                if hasattr(self.viewer, 'persistent_tooltip'):
                    self.viewer.persistent_tooltip.hide_tooltip()
                if hasattr(self.viewer, '_clear_current_peak'):
                    self.viewer._clear_current_peak()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move during dragging"""
        if self.is_dragging:
            # Let itemChange handle the updates automatically
            pass
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to stop dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            
            # Re-enable peak highlighting on the viewer
            if self.viewer and hasattr(self.viewer, 'annotation_dragging'):
                self.viewer.annotation_dragging = False
            
            # Final update using the actual item position
            current_pos = self.pos()
            self._update_leader_line_simple(current_pos.x(), current_pos.y())
        
        super().mouseReleaseEvent(event)

    def hoverEnterEvent(self, event):
        """Change cursor when hovering over text and highlight peptide/fragment"""
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        
        # Trigger peptide sequence and fragment line highlighting
        if self.viewer and self.fragment_data:
            fragment_sequence = self.fragment_data.get('fragment_sequence')
            if fragment_sequence and hasattr(self.viewer, 'highlight_peptide_sequence'):
                self.viewer.highlight_peptide_sequence(fragment_sequence)
            
            # Highlight the corresponding fragment line on the peptide display
            base_type = self.fragment_data.get('base_type')
            position = self.fragment_data.get('position')
            if base_type and position and hasattr(self.viewer, 'highlight_fragment_line'):
                self.viewer.highlight_fragment_line(position, base_type)
        
        # Bold and highlight the text annotation itself
        self._apply_hover_style(True)
        
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Reset cursor when leaving text and reset highlighting"""
        if not self.is_dragging:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            
            # Reset peptide and fragment line highlighting
            if self.viewer:
                if hasattr(self.viewer, 'reset_peptide_highlighting'):
                    self.viewer.reset_peptide_highlighting()
                if hasattr(self.viewer, 'reset_fragment_line_highlighting'):
                    self.viewer.reset_fragment_line_highlighting()
        
        # Reset text annotation style
        self._apply_hover_style(False)
        
        super().hoverLeaveEvent(event)

    def _apply_hover_style(self, is_hovered):
        """Apply or remove hover styling (bold and highlight) on the text annotation"""
        try:
            # Get current HTML content
            current_html = self.toHtml() if hasattr(self, 'toHtml') else ""
            
            if is_hovered:
                # Store original HTML for restoration
                if not hasattr(self, '_original_html') or not self._original_html:
                    self._original_html = current_html
                
                # Apply bold and background highlight style
                # Wrap in a span with bold weight and yellow background
                font_size = getattr(self.viewer, 'annotation_font_size', 14) if self.viewer else 14
                highlighted_html = f'<span style="font-weight:bold; background-color:rgba(255,255,0,0.3); font-size:{font_size + 2}px;">{self.toPlainText()}</span>'
                super().setHtml(highlighted_html)
            else:
                # Restore original HTML
                if hasattr(self, '_original_html') and self._original_html:
                    super().setHtml(self._original_html)
                    self._original_html = None
        except Exception as e:
            pass  # Silently handle any styling errors