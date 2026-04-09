import json
import logging

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont, QCursor, QColor
from PyQt6.QtWidgets import QApplication

from ..config.constants import PlotConstants
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class MouseInteractionMixin:
    """Mouse event handling, peak interaction, and measurement for MassSpecViewer."""

    def _setup_event_handlers(self):
        """Setup event handlers for mouse interactions"""
        # For interactive mode events, override spectrumplot's scene
        self.scene = self.spectrumplot.scene()
        self.original_mouse_press = self.scene.mousePressEvent
        self.original_mouse_move = self.scene.mouseMoveEvent
        self.scene.mousePressEvent = self.mouse_press
        self.scene.mouseMoveEvent = self.mouse_move

        #  Handle focus events to hide tooltips when app loses focus
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle application-wide events to hide tooltips when focus is lost"""

        # Hide tooltip when window loses focus or when mouse leaves the application
        if event.type() in [QEvent.Type.WindowDeactivate, QEvent.Type.FocusOut,
                            QEvent.Type.Leave, QEvent.Type.ApplicationDeactivate]:
            if hasattr(self, 'persistent_tooltip'):
                self.persistent_tooltip.hide_tooltip()
            # Also clear any current peak highlighting
            self._clear_current_peak()

        return super().eventFilter(obj, event)

    def leaveEvent(self, event):
        """Hide tooltip when mouse leaves the widget"""
        if hasattr(self, 'persistent_tooltip'):
            self.persistent_tooltip.hide_tooltip()
        self._clear_current_peak()
        super().leaveEvent(event)

    def _find_closest_peak(self, pos, threshold_x=None):
        """Find closest peak within threshold"""
        if threshold_x is None:
            threshold_x = self.get_adaptive_threshold_pixel_based(self.view, pixel_threshold=10)

        found_peak = None
        found_data = None
        min_distance = float('inf')

        for line_item, data in self.peak_lines:
            if not line_item.isVisible():
                continue

            distance_x = abs(pos.x() - data['mz'])

            if distance_x < threshold_x and 0 <= pos.y() <= data['intensity'] + 1:
                if distance_x < min_distance:
                    found_peak = line_item
                    found_data = data
                    min_distance = distance_x

        return found_peak, found_data

    def _create_tooltip_text(self, data, additional_data=None, include_error=False):
        """Unified tooltip creation logic"""
        tooltip_text = f"m/z: {data['mz']:.4f}\nIntensity: {data['intensity']:.1f}"

        if data.get('annotation'):
            tooltip_text += f"\nIon: {data['annotation']}"

        if additional_data:
            if additional_data.get('Fragment Sequence'):
                tooltip_text += f"\nSequence: {additional_data['Fragment Sequence']}"
            if include_error and additional_data.get('error_ppm') not in (None, ''):
                tooltip_text += f"\nError (ppm): {additional_data['error_ppm']:.2f}"
            # Show alternative ion matches within ppm tolerance
            alt_matches_raw = additional_data.get('Alternative Matches', '')
            if alt_matches_raw:
                try:
                    alt_list = json.loads(alt_matches_raw) if isinstance(alt_matches_raw, str) else alt_matches_raw
                    if alt_list:
                        tooltip_text += "\n--- Other possible matches ---"
                        for alt in alt_list:
                            tooltip_text += f"\n  {alt['label']} ({alt['ppm']:.2f} ppm)"
                except (json.JSONDecodeError, TypeError):
                    pass

        return tooltip_text

    def _get_additional_peak_data(self, mz):
        """Get additional data for a peak from the DataFrame"""
        additional_data = {}
        if not self.df.empty:
            matched_row = self.df[abs(self.df['m/z'] - mz) < 0.0001]
            if not matched_row.empty:
                additional_data['Fragment Sequence'] = matched_row.iloc[0].get('Fragment Sequence', '')
                additional_data['error_ppm'] = matched_row.iloc[0].get('error_ppm', '')
                additional_data['Alternative Matches'] = matched_row.iloc[0].get('Alternative Matches', '')
        return additional_data

    def _disable_other_modes(self, active_mode):
        """Centralized mode management"""
        if active_mode == 'measure':
            self.interactive_mode = False
        elif active_mode == 'interactive':
            self.peak_measure_mode = False

        # Clear any active selections/highlighting
        self._clear_current_peak()

    def toggle_peak_measure_mode(self, toggled):
        """Toggle peak difference measurement mode on/off"""
        self.peak_measure_mode = toggled
        if toggled:
            self._disable_other_modes('measure')
            self.first_peak_selected = None
            # Update menu text
            self.measure_action.setText("Exit Peak Measurement Mode")
        else:
            self.interactive_mode = True
            self.cancel_peak_selection()
            # Update menu text
            self.measure_action.setText("Peak Measurement Mode")

    def handle_error_plot_hover(self, pos):
        """Handle hovering over the error plot with improved detection"""
        # Use the same adaptive threshold system as spectrum plot
        threshold_x = self.get_adaptive_threshold_pixel_based(self.view, pixel_threshold=15)

        # For Y-axis, convert pixel threshold to PPM units
        error_viewbox = self.errorbarplot.getViewBox()
        error_view_rect = error_viewbox.viewRect()
        error_scene_rect = error_viewbox.sceneBoundingRect()

        if error_scene_rect.height() > 0:
            ppm_per_pixel = error_view_rect.height() / error_scene_rect.height()
            threshold_y = 15 * ppm_per_pixel  # 15 pixels converted to PPM units
        else:
            threshold_y = 2.0  # Fallback threshold in PPM

        found_point = self._find_closest_error_point(pos, threshold_x, threshold_y)

        if found_point:
            self.highlight_linked_peak(found_point['mz'], from_error_plot=True)

            # Get fragment sequence for peptide highlighting
            additional_data = self._get_additional_peak_data(found_point['mz'])
            if additional_data.get('Fragment Sequence'):
                self.highlight_peptide_sequence(additional_data['Fragment Sequence'])

            tooltip_text = self._create_error_tooltip(found_point)
            cursor_pos = QCursor.pos()
            self.persistent_tooltip.show_tooltip(tooltip_text, cursor_pos)
        else:
            self.reset_linked_highlighting()
            self.reset_peptide_highlighting()
            self.persistent_tooltip.hide_tooltip()

    def _find_closest_error_point(self, pos, threshold_x, threshold_y):
        """Find closest error plot point - SIMPLIFIED"""
        found_point = None
        min_distance = float('inf')

        for error_data in self.error_scatter_items:
            if not error_data['scatter_item'].isVisible():
                continue

            distance_x = abs(pos.x() - error_data['mz'])
            distance_y = abs(pos.y() - error_data['error'])

            if distance_x < threshold_x and distance_y < threshold_y:
                # Simple Euclidean distance
                total_distance = (distance_x**2 + distance_y**2)**0.5

                if total_distance < min_distance:
                    found_point = error_data
                    min_distance = total_distance

        return found_point

    def _create_error_tooltip(self, error_data):
        """Create tooltip for error plot points"""
        tooltip_text = f"m/z: {error_data['mz']:.4f}\nIntensity: {error_data['intensity']:.1f}\nError (ppm): {error_data['error']:.2f}"
        if error_data.get('annotation'):
            tooltip_text += f"\nIon: {error_data['annotation']}"
        return tooltip_text

    def highlight_linked_peak(self, target_mz, from_error_plot=False):
        """Highlight corresponding peaks in both plots based on m/z"""
        tolerance = PlotConstants.MZ_TOLERANCE

        # Reset previous highlighting
        self.reset_linked_highlighting()

        # Highlight in spectrum plot
        for line_item, data in self.peak_lines:
            if abs(data['mz'] - target_mz) < tolerance:
                if hasattr(line_item, 'original_pen'):
                    highlight_pen = pg.mkPen(PlotConstants.LINKED_HIGHLIGHT_COLOR,
                                           width=PlotConstants.LINKED_HIGHLIGHT_WIDTH)
                    line_item.setPen(highlight_pen)
                    self.current_peak_line = line_item
                break

        # Highlight in error plot
        for error_data in self.error_scatter_items:
            if abs(error_data['mz'] - target_mz) < tolerance:
                error_data['scatter_item'].setBrush(PlotConstants.LINKED_HIGHLIGHT_COLOR)
                error_data['scatter_item'].setSize(PlotConstants.ERROR_SCATTER_HIGHLIGHT_SIZE)
                self.current_error_point = error_data
                break

    def reset_linked_highlighting(self):
        """Reset highlighting in both plots"""
        # Reset spectrum highlighting
        if self.current_peak_line is not None:
            if hasattr(self.current_peak_line, 'original_pen'):
                self.current_peak_line.setPen(self.current_peak_line.original_pen)
            self.current_peak_line = None

        # Reset error plot highlighting
        if self.current_error_point is not None:
            self.current_error_point['scatter_item'].setBrush(self.current_error_point['original_brush'])
            self.current_error_point['scatter_item'].setSize(PlotConstants.ERROR_SCATTER_SIZE)
            self.current_error_point = None

    def get_adaptive_threshold_pixel_based(self, view, pixel_threshold=None):
        """Convert pixel threshold to data coordinates"""
        if pixel_threshold is None:
            pixel_threshold = PlotConstants.MOUSE_THRESHOLD_PIXELS

        view_rect = view.viewRect()
        scene_rect = view.sceneBoundingRect()

        if scene_rect.width() > 0:
            data_per_pixel = view_rect.width() / scene_rect.width()
            return pixel_threshold * data_per_pixel
        return 0.5  # Fallback

    def highlight_peak_line(self, line_item, color=None, width=None):
        """Highlight a peak by changing its pen."""
        if color is None:
            color = PlotConstants.HIGHLIGHT_COLOR
        if width is None:
            width = PlotConstants.HIGHLIGHT_WIDTH
        line_item.setPen(pg.mkPen(color, width=width))

    def reset_peak_line(self, line_item):
        """Reset a peak's pen to its original style."""
        if hasattr(line_item, 'original_pen'):
            line_item.setPen(line_item.original_pen)
        else:
            line_item.setPen(pg.mkPen(line_item.opts['pen'].color(), width=3))

    def add_peak_measurement(self, peak1, peak2):
        """Add a measurement line between two peaks and display the difference."""
        # Ensure peak1 has lower m/z than peak2
        if peak1['mz'] > peak2['mz']:
            peak1, peak2 = peak2, peak1

        # Calculate difference
        diff = peak2['mz'] - peak1['mz']

        # Use the lower intensity for the line
        line_y = min(peak1['intensity'], peak2['intensity'])

        # Create line between peaks (at the lower apex) with theme-aware color
        line = pg.PlotDataItem(
            x=[peak1['mz'], peak2['mz']],
            y=[line_y, line_y],  # Horizontal line at lower peak height
            pen=pg.mkPen(EditorConstants.TEXT_COLOR(), width=2, style=Qt.PenStyle.DashLine)
        )

        # Add difference label with theme-aware color
        text = pg.TextItem(
            text=f"Δm/z: {diff:.4f}",
            color=EditorConstants.TEXT_COLOR(),
            anchor=(0.5, 1.0)
        )
        text.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, self.annotation_font_size, QFont.Weight.Bold))

        # Position text above the line
        mid_x = (peak1['mz'] + peak2['mz']) / 2
        text.setPos(mid_x, line_y + 1)

        # Add items to plot and store references
        self.spectrumplot.addItem(line)
        self.spectrumplot.addItem(text)
        self.peak_measurements.append((line, text))

        return line, text

    def clear_peak_measurements(self):
        """Remove all peak measurement lines and labels."""
        for line, text in self.peak_measurements:
            self.spectrumplot.removeItem(line)
            self.spectrumplot.removeItem(text)
        self.peak_measurements = []
        self.first_peak_selected = None

    def cancel_peak_selection(self):
        """Cancel current peak selection and reset highlighting."""
        if self.first_peak_selected is not None and self.first_peak_line is not None:
            self.reset_peak_line(self.first_peak_line)
            self.first_peak_selected = None
            self.first_peak_line = None

    def mouse_press(self, event):
        """Handle mouse press events with improved peak detection"""
        # Handle right click to show context menu
        if event.button() == Qt.MouseButton.RightButton and self.interactive_mode:
            pos = self.view.mapSceneToView(event.scenePos())
            found_peak, found_data = self._find_closest_peak(pos)

            if found_peak is not None and found_data is not None:
                self.current_peak_data = found_data
                self.current_peak_line = found_peak
                logger.debug(f"Right-click on peak at m/z {found_data['mz']:.4f}, is_matched: {found_data.get('is_matched', False)}")
                self.show_peak_context_menu(event)
                event.accept()
                return
            else:
                print("[DEBUG] Right-click not on any peak")
        # Handle peak measurement mode
        if self.peak_measure_mode:
            pos = self.view.mapSceneToView(event.scenePos())
            # Use adaptive threshold instead of fixed threshold
            threshold_x = self.get_adaptive_threshold_pixel_based(self.view, pixel_threshold=10)

            # Find the closest peak
            closest_peak = None
            closest_line = None
            min_distance = float('inf')

            for line_item, data in self.peak_lines:
                distance = abs(pos.x() - data['mz'])
                if distance < threshold_x and distance < min_distance:
                    if 0 <= pos.y() <= data['intensity'] + 5:
                        closest_peak = data
                        closest_line = line_item
                        min_distance = distance

            if closest_peak:
                if self.first_peak_selected is None:
                    # First peak selection
                    self.first_peak_selected = closest_peak
                    # Store the line item for first peak to reset later
                    self.first_peak_line = closest_line
                    # Highlight the selected peak in RED
                    self.highlight_peak_line(closest_line, color='red', width=PlotConstants.PEAK_MEASURE_HIGHLIGHT_WIDTH)
                else:
                    # Second peak selection - add measurement
                    if closest_peak != self.first_peak_selected:
                        self.add_peak_measurement(self.first_peak_selected, closest_peak)
                        # Reset highlighting on both peaks
                        self.reset_peak_line(closest_line)
                        self.reset_peak_line(self.first_peak_line)
                        self.first_peak_selected = None  # Reset for next measurement
                        self.first_peak_line = None
                event.accept()
                return
        self.original_mouse_press(event)
        event.accept()

    def mouse_move(self, event):
        """Simplified unified mouse move handler"""
        # Skip peak highlighting/tooltips while dragging annotation text
        if self.annotation_dragging:
            self.original_mouse_move(event)
            return

        spectrum_rect = self.spectrumplot.sceneBoundingRect()
        error_rect = self.errorbarplot.sceneBoundingRect()
        event_pos = event.scenePos()

        if error_rect.contains(event_pos):
            error_viewbox = self.errorbarplot.getViewBox()
            if hasattr(error_viewbox, 'mouseMoveEvent'):
                error_viewbox.mouseMoveEvent(event)
        elif spectrum_rect.contains(event_pos):
            pos = self.view.mapSceneToView(event_pos)
            self._handle_spectrum_mouse_move(pos, event)
        else:
            self.original_mouse_move(event)

    def _handle_spectrum_mouse_move(self, pos, event):
        """Unified spectrum mouse move handling"""
        found_peak, found_data = self._find_closest_peak(pos)

        if found_peak:
            self._update_current_peak(found_peak, found_data)

            if self.interactive_mode:
                if self.linked_highlighting:
                    self.highlight_linked_peak(found_data['mz'])

                additional_data = self._get_additional_peak_data(found_data['mz'])
                if found_data.get("is_matched") and additional_data.get('Fragment Sequence'):
                    self.highlight_peptide_sequence(additional_data['Fragment Sequence'])

            tooltip_text = self._create_tooltip_text(
                found_data,
                self._get_additional_peak_data(found_data['mz']) if self.interactive_mode else None,
                include_error=self.interactive_mode
            )

            if self.peak_measure_mode and self.first_peak_selected:
                diff = abs(found_data['mz'] - self.first_peak_selected['mz'])
                tooltip_text += f"\nΔm/z from selection: {diff:.4f}"

            self.persistent_tooltip.show_tooltip(tooltip_text, event.screenPos())
            event.accept()
        else:
            self._clear_current_peak()
            self.original_mouse_move(event)

    def _update_current_peak(self, found_peak, found_data):
        """Update current peak highlighting"""
        self.current_peak_data = found_data
        if self.current_peak_line is not None and self.current_peak_line != found_peak:
            self.reset_peak_line(self.current_peak_line)
        if self.current_peak_line != found_peak:
            self.current_peak_line = found_peak
            self.highlight_peak_line(found_peak)

    def _clear_current_peak(self):
        """Clear current peak highlighting and tooltips"""
        self.current_peak_data = None
        if self.current_peak_line is not None:
            self.reset_peak_line(self.current_peak_line)
            self.current_peak_line = None
            self.reset_linked_highlighting()
            self.reset_peptide_highlighting()
            self.persistent_tooltip.hide_tooltip()
