import re
import logging

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from ..config.constants import PlotConstants, matched_mask
from ..classes.interactivetext import EnhancedInteractiveTextItem
from utils.utility_classes.htmlformating import HTMLFormatter
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class SpectrumPlottingMixin:
    """Spectrum and error plot rendering for MassSpecViewer."""

    def _create_peak_line_item(self, mz, intensity, color, is_matched):
        """Create a peak line item with consistent styling and theme-aware unmatched peaks"""
        if is_matched:
            pen = pg.mkPen(color, width=PlotConstants.PEAK_LINE_WIDTH)
        else:
            # Use theme-aware unmatched peak color
            unmatched_color = getattr(self, 'unmatched_peak_color', 'grey')
            color_obj = pg.mkColor(unmatched_color)
            color_obj.setAlpha(PlotConstants.UNMATCHED_PEAK_ALPHA)
            pen = pg.mkPen(color_obj, width=PlotConstants.PEAK_LINE_WIDTH)

        line_item = pg.PlotDataItem(x=[mz, mz], y=[0, intensity], pen=pen)
        line_item.original_pen = pen
        return line_item

    def _process_peak_data(self, row, is_matched):
        """Process and return standardized peak data"""
        return {
            "mz": row['m/z'],
            "intensity": row['Relative Intensity'],
            "annotation": row['text_annotation'] if is_matched else "",
            "is_matched": is_matched,
            "color": row.get("Color", EditorConstants.TEXT_COLOR()),
            "base_type": str(row.get('Base Type', '')).strip(),
            "ion_number": row.get('Ion Number', ''),
            "isotope": row.get('Isotope', 0)
        }

    def _should_create_annotation(self, peak_data, intensity_threshold):
        """Determine if a peak should have a text annotation"""
        return (peak_data["is_matched"] and
                np.isclose(float(peak_data["isotope"]), 0.0) and
                peak_data["intensity"] >= intensity_threshold)

    def toggle_non_colored_peaks(self, toggled):
        # Show/hide unmatched peaks in spectrum plot
        for line_item, data in self.peak_lines:
            if not data["is_matched"]:
                line_item.setVisible(not toggled)

        # Also hide corresponding error plot points for unmatched peaks
        for error_data in self.error_scatter_items:
            # Find corresponding peak data to check if it's matched
            mz = error_data['mz']
            # Find the corresponding peak in peak_lines
            for line_item, peak_data in self.peak_lines:
                if abs(peak_data['mz'] - mz) < 0.0001:  # Same peak
                    if not peak_data["is_matched"]:
                        error_data['scatter_item'].setVisible(not toggled)
                    break

    def plot_spectrum(self):
        # Save positions of text items that were dragged by the user
        for item in self.matched_items:
            if isinstance(item, EnhancedInteractiveTextItem):
                pk = getattr(item, 'peak_coord', None)
                fd = getattr(item, 'fragment_data', {})
                if pk:
                    pos = item.pos()
                    key = (
                        round(pk[0], 4),
                        str(fd.get('base_type', '')),
                        str(fd.get('ion_number', '')),
                        str(getattr(item, '_charge_str', '')),
                    )
                    self._saved_annotation_positions[key] = (pos.x(), pos.y())

        # Clear old items
        for item in self.matched_items:
            self.spectrumplot.removeItem(item)
        self.matched_items.clear()
        self.peak_lines.clear()

        # Pre-compute zoom factor for leader line width estimation (constant per plot pass)
        try:
            _vb = self.spectrumplot.getViewBox()
            _vr = _vb.viewRect()
            _sr = _vb.sceneBoundingRect()
            self._cached_zoom_factor = _vr.width() / _sr.width() if _sr.width() > 0 else 1.0
        except Exception:
            self._cached_zoom_factor = 1.0

        mask = pd.to_numeric(self.df['Matched'], errors='coerce').notnull()

        for idx, row in self.df.iterrows():
            mz = row['m/z']
            intensity = row['Relative Intensity']
            is_matched = bool(mask[idx])
            color = row.get("Color", EditorConstants.TEXT_COLOR())
            # Apply color override from annotation display settings
            if self.annotation_display_settings and is_matched:
                _key = self._get_annotation_settings_key(row)
                _override = self.annotation_display_settings.get(_key, {}).get("color")
                if _override:
                    color = _override
            line_item = self._create_peak_line_item(mz, intensity, color, is_matched)

            # Store peak data
            self.peak_lines.append((
                line_item,
                {
                    "mz": mz,
                    "intensity": intensity,
                    "annotation": row['text_annotation'] if is_matched else "",
                    "is_matched": is_matched,
                }
            ))

            self.spectrumplot.addItem(line_item)
            self.matched_items.append(line_item)

            # If matched & Isotope is 0 => create label with improved leader line
            if is_matched and np.isclose(float(row['Isotope']), 0.0) and (intensity >= self.text_annotation_threshold):

                # Check annotation display settings for visibility
                if self.annotation_display_settings:
                    _ion_key = self._get_annotation_settings_key(row)
                    _settings = self.annotation_display_settings.get(_ion_key)
                    if _settings and not _settings.get("visible", True):
                        continue

                # Check if text will be rotated
                is_rotated = hasattr(self, 'text_rotation_angle') and abs(self.text_rotation_angle - 90) < 5

                # Increase vertical offset for rotated text to prevent clipping
                if is_rotated:
                    vertical_offset = PlotConstants.PEAK_LABEL_OFFSET + 15  # Extra offset for rotated text
                else:
                    vertical_offset = PlotConstants.PEAK_LABEL_OFFSET

                horizontal_offset = 2  # Small horizontal offset for above placement
                side_offset = 15  # Larger offset for side placement

                # Determine if label should go directly above or to the side
                if intensity + vertical_offset <= PlotConstants.SPECTRUM_Y_LIMIT - 10:
                    # Place label directly above peak with small horizontal offset
                    label_x = mz + horizontal_offset
                    label_y = intensity + vertical_offset
                    anchor = (0, 0.5)  # Left-centered anchor
                else:
                    # Place label to the side of peak with larger offset
                    label_x = mz + side_offset + 10
                    label_y = intensity - 5
                    anchor = (0, 0.5)  # Left-centered anchor

                # Get annotation text for proper line calculation
                annotation_text = row["text_annotation"]
                html_annotation_text = row["html_annotation"]

                # Prepare fragment data for hover highlighting
                fragment_data = {
                    'fragment_sequence': row.get('Fragment Sequence', ''),
                    'base_type': str(row.get('Base Type', '')).strip(),
                    'ion_number': row.get('Ion Number', ''),
                    'position': self._calculate_fragment_position(row)
                }

                # Create simple straight leader line with opacity
                leader_line = self._create_simple_leader_line(
                    mz, intensity, label_x, label_y, color, annotation_text, is_rotated=is_rotated
                )

                # Add leader line to plot
                self.spectrumplot.addItem(leader_line)
                self.matched_items.append(leader_line)

                # Create enhanced text item
                text_item = EnhancedInteractiveTextItem(
                    text=annotation_text,
                    color=color,
                    peak_coord=(mz, intensity),
                    leader_line=leader_line,
                    viewer=self,
                    fragment_data=fragment_data,
                    anchor=anchor
                )

                # Apply font and rotation
                text_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, self.annotation_font_size))
                if hasattr(self, 'text_rotation_angle') and self.text_rotation_angle != 0:
                    text_item.setRotation(self.text_rotation_angle)

                # Set HTML content
                text_item.setHtml(annotation_text)
                text_item._html_annotation = html_annotation_text

                # Store charge string for position persistence key
                _charge_val = row.get('Charge', 1)
                try:
                    _charge_val = int(float(_charge_val))
                except (ValueError, TypeError):
                    _charge_val = 1
                text_item._charge_str = f"{_charge_val}+" if _charge_val > 1 else ""

                # Check for a saved user-dragged position
                _pos_key = (
                    round(mz, 4),
                    str(fragment_data.get('base_type', '')),
                    str(fragment_data.get('ion_number', '')),
                    text_item._charge_str,
                )
                if _pos_key in self._saved_annotation_positions:
                    saved_x, saved_y = self._saved_annotation_positions[_pos_key]
                    text_item.setPos(saved_x, saved_y)
                    # Update leader line to point to saved position
                    text_item._update_leader_line_simple(saved_x, saved_y)
                else:
                    text_item.setPos(label_x, label_y)

                self.spectrumplot.addItem(text_item)
                self.matched_items.append(text_item)

        self.spectrumplot.setYRange(0, PlotConstants.SPECTRUM_Y_LIMIT, padding=0)
        self.spectrumplot.getViewBox().setLimits(yMin=0, yMax=PlotConstants.SPECTRUM_Y_LIMIT)

        # Clear cached zoom factor after plot pass
        self._cached_zoom_factor = None

    def plot_error_ppm(self):
        self.errorbarplot.clear()
        self.error_scatter_items.clear()
        mask = pd.to_numeric(self.df['Matched'], errors='coerce').notnull()
        mask_error = (
            mask &
            pd.to_numeric(self.df['error_ppm'], errors='coerce').notnull() &
            (pd.to_numeric(self.df['Isotope'], errors='coerce') == 0)
        )
        df_error = self.df[mask_error]
        if df_error.empty:
            return
        # Create individual scatter items
        for idx, row in df_error.iterrows():
            mz = row['m/z']
            error = row['error_ppm']
            ion_type = str(row['Ion Type']).strip()
            color = row.get("Color", "")
            if not color:
                color = EditorConstants.UNMATCHED_PEAK_COLOR()
            scatter_item = pg.ScatterPlotItem(
                pos=[(mz, error)],
                brush=color,
                symbol='o',
                size=PlotConstants.ERROR_SCATTER_SIZE,
                pen=pg.mkPen(color, width=1)
            )
            # Store reference with data for linking
            scatter_data = {
                'mz': mz,
                'error': error,
                'idx': idx,
                'ion_type': ion_type,
                'original_brush': color,
                'scatter_item': scatter_item,
                'annotation': row['html_annotation'],  # Use HTML for tooltips
                'intensity': row['Relative Intensity']
            }

            self.error_scatter_items.append(scatter_data)
            self.errorbarplot.addItem(scatter_item)

        # Add a dashed horizontal red line at y = 0
        color = pg.mkColor('red')
        color.setAlpha(128)
        zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine))
        self.errorbarplot.addItem(zero_line)

    def _create_simple_leader_line(self, peak_mz, peak_intensity, label_x, label_y, color, annotation_text="", text_item=None, is_rotated=False):
        """
        Create a simple straight line from peak top to text label.
        Line has 40% opacity and matches the peak color.
        Handles rotation - attaches from top for high-intensity labels, bottom for normal.
        """

        # Get font size for positioning calculations
        font_size = getattr(self, 'annotation_font_size', 14)

        # Estimate text width to find center
        text_width = self._estimate_text_width_for_line(annotation_text, font_size)

        # Adjust connection point based on rotation
        if is_rotated:  # 90-degree rotation (vertical text)
            # Check if label is at high intensity (side placement) or above peak
            if label_y < peak_intensity:  # Label is to the side (high intensity peak)
                # Connect to top of rotated text - much closer
                connection_x = label_x + (font_size * 0.5)  # Offset to right edge
                connection_y = label_y + (font_size * 0.3)  # Just above label position
            else:  # Label is above peak (normal intensity)
                # Connect to bottom of rotated text
                connection_x = label_x + (font_size * 0.5)  # Offset to right edge
                connection_y = label_y - (font_size * 0.3)  # Just below label position
        else:  # Horizontal text
            # Connection point at the nearest border of the text bounding box
            text_height = self._estimate_text_height_for_line(font_size)
            connection_x = max(label_x, min(peak_mz, label_x + text_width))
            if peak_intensity < label_y:
                connection_y = label_y - (text_height / 2.0)  # Bottom border
            else:
                connection_y = label_y + (text_height / 2.0)  # Top border

        # Create a single straight line with 40% opacity (alpha = 102 out of 255)

        # Parse the color and add opacity
        if isinstance(color, str):
            qcolor = QColor(color)
        else:
            qcolor = QColor(*color)

        # Set opacity to 40% (0.4 * 255 = 102)
        qcolor.setAlpha(102)

        # Create single line from peak top to below text center
        # Enable antialiasing for smooth diagonal lines
        leader_line = pg.PlotDataItem(
            x=[peak_mz, connection_x],
            y=[peak_intensity, connection_y],
            pen=pg.mkPen(qcolor, width=1.5),
            antialias=True
        )

        return leader_line

    def _estimate_text_width_for_line(self, annotation_text, font_size):
        """Estimate text width based on annotation text and font size"""
        zoom_factor = getattr(self, '_cached_zoom_factor', None)
        if zoom_factor is None:
            try:
                viewbox = self.spectrumplot.getViewBox()
                view_rect = viewbox.viewRect()
                scene_rect = viewbox.sceneBoundingRect()
                zoom_factor = view_rect.width() / scene_rect.width() if scene_rect.width() > 0 else 1.0
            except Exception:
                zoom_factor = 1.0

        # Average character width (adjusted for typical annotations)
        char_width = font_size * 0.6 * zoom_factor

        # Strip HTML tags to get plain text
        if annotation_text:
            plain_text = re.sub('<[^<]+?>', '', annotation_text)
            char_count = len(plain_text) if plain_text else 3
        else:
            char_count = 3

        return char_count * char_width

    def _estimate_text_height_for_line(self, font_size):
        """Estimate text height in data coordinates for leader line positioning."""
        try:
            viewbox = self.spectrumplot.getViewBox()
            view_rect = viewbox.viewRect()
            scene_rect = viewbox.sceneBoundingRect()
            y_zoom = view_rect.height() / scene_rect.height() if scene_rect.height() > 0 else 1.0
        except Exception:
            y_zoom = 1.0
        return font_size * y_zoom
