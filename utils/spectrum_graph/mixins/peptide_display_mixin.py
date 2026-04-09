import logging
from typing import Optional

import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont

from ..config.constants import PlotConstants, matched_mask
from ..classes.peptide_position_calculator import PositionCalculator
from ..classes.amino_acid_text_item import AminoAcidTextItem
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class PeptideDisplayMixin:
    """Peptide sequence display and fragment line management for MassSpecViewer."""

    def set_peptide_sequence(self, sequence: str):
        """Set peptide sequence with responsive sizing - FIXED"""

        # IMPORTANT: Reset to base values first
        self.letter_spacing = self.base_letter_spacing
        self.current_font_size = self.base_font_size

        self.peptide_sequence = sequence.upper()
        self.peptide = self.peptide_sequence
        self._clear_peptide_display()
        self._update_peptide_visual_parameters()

        # Create position calculator after visual parameters are computed
        if self.peptide_sequence:
            self.position_calculator = PositionCalculator(
                self.start_x, self.letter_spacing, len(self.peptide_sequence)
            )

        self._draw_peptide_sequence()

    def _clear_peptide_display(self):
        """Clear all peptide visual elements"""
        self.peptide_plot.clear()
        self.amino_acid_items.clear()
        self.modification_items.clear()
        self.fragment_lines.clear()
        self.highlight_items.clear()

    def calculate_responsive_parameters(self, sequence_length):
        """Calculate font size, letter spacing, and line parameters based on sequence length - FIXED"""

        if sequence_length <= self.max_aa_for_full_size:
            # Full size for short peptides - USE BASE VALUES
            self.current_font_size = self.base_font_size
            self.letter_spacing = self.base_letter_spacing
            line_thickness = 3
            line_offset_vertical = 80
        else:
            # Calculate scaling factors for long peptides - CALCULATE FROM BASE
            excess_aa = sequence_length - self.max_aa_for_full_size

            # Font size decreases by 0.8 points per additional AA, min 12
            font_reduction = excess_aa * 0.8
            self.current_font_size = max(self.min_font_size, self.base_font_size - font_reduction)

            # Letter spacing decreases to fit within fixed width - CALCULATE FROM FIXED WIDTH
            available_space = self.fixed_width - (2 * 25)  # Use fixed margin, not current start_x
            self.letter_spacing = max(self.min_letter_spacing, available_space / (sequence_length - 1))

            # Line parameters scale with font size
            font_scale = self.current_font_size / self.base_font_size
            line_thickness = max(2, int(3 * font_scale))
            line_offset_vertical = max(40, int(80 * font_scale))

        return line_thickness, line_offset_vertical

    def _update_peptide_visual_parameters(self):
        """Calculate visual parameters based on sequence length - FIXED"""
        if not self.peptide_sequence:
            # RESET to base values when no sequence
            self.letter_spacing = self.base_letter_spacing
            self.current_font_size = self.base_font_size
            self.start_x = 25
            return

        sequence_length = len(self.peptide_sequence)

        # ALWAYS recalculate from base values (don't use current values)
        line_thickness, line_offset = self.calculate_responsive_parameters(sequence_length)

        # Store line parameters for fragment line drawing
        self.current_line_thickness = line_thickness
        self.current_line_offset = line_offset

        # CENTERED POSITIONING: Calculate start_x to center the peptide
        total_sequence_width = (sequence_length - 1) * self.letter_spacing
        self.start_x = (self.fixed_width - total_sequence_width) / 2

    def _calculate_font_size(self, base_font_size: int, scale: float = 1.0) -> int:
        """Calculate font size based on current responsive settings"""
        return max(8, int(self.current_font_size * scale))

    def _apply_text_formatting(self, text_item, amino_acid: str, color: str = None, scale: float = 1.0):
        """Apply responsive text formatting"""
        if color is None:
            color = EditorConstants.TEXT_COLOR()
        font_size = self._calculate_font_size(self.current_font_size, scale)
        text_item.setHtml(f'''
            <span style="
                font-weight: bold;
                color: {color};
                font-size: {font_size}px;
            ">{amino_acid}</span>
        ''')

    def _draw_peptide_sequence(self):
        """Draw peptide sequence with responsive text sizing"""
        if not self.peptide_sequence or not self.position_calculator:
            return

        # Clear existing items
        for item_data in self.amino_acid_items:
            self.peptide_plot.removeItem(item_data['item'])
        self.amino_acid_items.clear()

        for i, amino_acid in enumerate(self.peptide_sequence):
            x_pos = self.position_calculator.get_amino_acid_position(i)

            text_color = EditorConstants.TEXT_COLOR()
            text_item = AminoAcidTextItem(
                text=amino_acid,
                position=i + 1,
                parent_widget=self,
                color=text_color,
                anchor=(0.5, 0.5)
            )

            # Use responsive formatting with theme-aware color
            self._apply_text_formatting(text_item, amino_acid, text_color, 1.0)
            text_item.char = amino_acid

            text_item.setPos(x_pos, 0)
            self.peptide_plot.addItem(text_item)

            self.amino_acid_items.append({
                'item': text_item,
                'position': i + 1,
                'x_pos': x_pos,
                'amino_acid': amino_acid
            })

    def highlight_peptide_sequence(self, fragment_sequence):
        """Highlight the peptide sequence range corresponding to a fragment"""
        if not fragment_sequence or not hasattr(self, 'peptide_sequence') or not self.peptide_sequence:
            return

        self.reset_peptide_highlighting()

        peptide_upper = self.peptide_sequence.upper()
        fragment_upper = fragment_sequence.upper()

        start_pos = peptide_upper.find(fragment_upper)
        if start_pos == -1:
            return

        end_pos = start_pos + len(fragment_upper) - 1
        self._highlight_peptide_range(start_pos, end_pos)

    def reset_peptide_highlighting(self):
        """Remove any existing peptide sequence highlighting"""
        for item_data in self.amino_acid_items:
            text_item = item_data['item']
            amino_acid = item_data['amino_acid']
            font_size = int(self.current_font_size)
            # Use theme-aware text color instead of hardcoded black
            text_color = EditorConstants.TEXT_COLOR()
            text_item.setHtml(f'<span style="font-weight:bold; color:{text_color}; font-size:{font_size}px;">{amino_acid}</span>')
        self.highlight_items.clear()

    def _highlight_peptide_range(self, start_pos, end_pos):
        """Highlight amino acids in red"""
        self.highlight_items.clear()

        position_map = {item_data['position']: item_data for item_data in self.amino_acid_items}
        font_size = int(self.current_font_size * 1.2)
        for i in range(start_pos, end_pos + 1):
            item_data = position_map.get(i + 1)
            if item_data:
                text_item = item_data['item']
                amino_acid = item_data['amino_acid']
                text_item.setHtml(f'<span style="font-weight:bold; color:#CC0000; font-size:{font_size}px;">{amino_acid}</span>')
                self.highlight_items.append(text_item)

    def clear_fragment_lines(self):
        """Clear fragment lines"""
        for line_item in self.fragment_lines:
            self.peptide_plot.removeItem(line_item)
        self.fragment_lines.clear()
        if hasattr(self, 'fragment_line_data'):
            self.fragment_line_data.clear()

    def add_fragment_line(self, position: int, ion_type: str, color: str, y_offset: int):
        """Add a corner-bracket fragment marker at the given cleavage position.

        Uses y_offset from ION_FRAGMENT_OFFSETS for nested stacking so
        different ion types at the same position never overlap.
        Positive y_offset = C-terminal (above, arm RIGHT),
        negative y_offset = N-terminal (below, arm LEFT).
        """
        if not self.position_calculator:
            return

        x_pos = self.position_calculator.get_fragment_line_position(position, ion_type)

        line_width = getattr(self, 'current_line_thickness', 2)
        scale = self.current_font_size / self.base_font_size

        # Use fixed y_offset in data coordinates, independent of font scale,
        # so lines always extend the same distance regardless of peptide length
        final_y = float(y_offset)

        # Horizontal arm length, responsive to font scaling
        arm_length = max(4, int(6 * scale))

        pen = pg.mkPen(color, width=line_width)

        # Vertical line from baseline to the assigned nesting level
        vertical_line = pg.PlotDataItem(
            x=[x_pos, x_pos],
            y=[0, final_y],
            pen=pen
        )

        # Horizontal arm: C-terminal (positive y) extends RIGHT,
        # N-terminal (negative y) extends LEFT
        if y_offset > 0:
            horizontal_line = pg.PlotDataItem(
                x=[x_pos, x_pos + arm_length],
                y=[final_y, final_y],
                pen=pen
            )
        else:
            horizontal_line = pg.PlotDataItem(
                x=[x_pos - arm_length, x_pos],
                y=[final_y, final_y],
                pen=pen
            )

        # Store original pen for reset after highlighting
        for item in (vertical_line, horizontal_line):
            item.original_pen = pg.mkPen(color, width=line_width)
            item.original_color = color

        self.peptide_plot.addItem(vertical_line)
        self.peptide_plot.addItem(horizontal_line)
        self.fragment_lines.extend([vertical_line, horizontal_line])

        # Store fragment data for lookup during highlighting
        if not hasattr(self, 'fragment_line_data'):
            self.fragment_line_data = []
        self.fragment_line_data.append({
            'position': position,
            'ion_type': ion_type,
            'color': color,
            'vertical_line': vertical_line,
            'horizontal_line': horizontal_line
        })

    def highlight_fragment_line(self, position: int, ion_type: str):
        """Highlight the fragment line at the given position and ion type"""
        if not hasattr(self, 'fragment_line_data'):
            return

        highlight_width = getattr(self, 'current_line_thickness', 2) * 2  # Double width for highlight

        for frag_data in self.fragment_line_data:
            if frag_data['position'] == position and frag_data['ion_type'] == ion_type:
                # Create highlight pen with increased width
                highlight_pen = pg.mkPen(frag_data['color'], width=highlight_width)
                frag_data['vertical_line'].setPen(highlight_pen)
                frag_data['horizontal_line'].setPen(highlight_pen)
                break

    def reset_fragment_line_highlighting(self):
        """Reset all fragment lines to their original appearance"""
        if not hasattr(self, 'fragment_line_data'):
            return

        for frag_data in self.fragment_line_data:
            vertical_line = frag_data['vertical_line']
            horizontal_line = frag_data['horizontal_line']

            if hasattr(vertical_line, 'original_pen'):
                vertical_line.setPen(vertical_line.original_pen)
            if hasattr(horizontal_line, 'original_pen'):
                horizontal_line.setPen(horizontal_line.original_pen)

    def _calculate_fragment_position(self, data):
        """Calculate the fragment line position from a dict or DataFrame row.

        Accepts any mapping with 'Base Type' and 'Ion Number' keys.
        """
        try:
            base_type = str(data.get('Base Type', '')).strip()
            ion_number_raw = data.get('Ion Number')

            if not base_type or ion_number_raw is None:
                return None

            ion_number_str = str(ion_number_raw)
            if '-' in ion_number_str or not ion_number_str:
                return None

            ion_number = int(ion_number_str)
            sequence_length = len(self.peptide) if hasattr(self, 'peptide') and self.peptide else 0

            if sequence_length == 0:
                return None

            if base_type in ['x', 'y', 'z', 'w', 'v']:
                position = sequence_length - ion_number
            else:
                position = ion_number

            if position < 1 or position > sequence_length:
                return None

            return position
        except (ValueError, TypeError):
            return None

    def get_position_x(self, position: int) -> Optional[float]:
        """Get X coordinate for a given position using centralized calculator - FIXED like original"""
        if self.position_calculator:
            return self.position_calculator.get_amino_acid_position_1_based(position)

        # Fallback to old method
        for item in self.amino_acid_items:
            if item['position'] == position:
                return item['x_pos']
        return None

    def get_nearest_position(self, x_coord: float) -> int:
        """Find nearest position using centralized calculator - FIXED like original"""
        if self.position_calculator:
            return self.position_calculator.find_nearest_position_from_x(x_coord)

        # Fallback to old method
        if not self.amino_acid_items:
            return 1

        min_distance = float('inf')
        nearest_position = 1

        for item in self.amino_acid_items:
            distance = abs(item['x_pos'] - x_coord)
            if distance < min_distance:
                min_distance = distance
                nearest_position = item['position']

        return nearest_position

    def _iter_fragment_positions(self):
        """Yield (position, base_type, color, y_offset) for each unique matched fragment.

        Filters the DataFrame for matched, monoisotopic rows, computes positions,
        and deduplicates by (base_type, ion_number, position).
        """
        sequence_length = len(self.peptide) if hasattr(self, 'peptide') and self.peptide else 0
        if sequence_length == 0 or self.df.empty:
            return

        ion_offsets = PlotConstants.ION_FRAGMENT_OFFSETS

        matched_fragments = self.df[matched_mask(self.df, monoisotopic_only=True)]

        unique_fragments = set()

        for _, row in matched_fragments.iterrows():
            base_type = str(row['Base Type']).strip()
            if base_type not in ion_offsets:
                continue

            ion_number_str = str(row['Ion Number'])
            if '-' in ion_number_str:
                continue

            try:
                ion_number = int(ion_number_str)
            except (ValueError, TypeError):
                continue

            if base_type in ['x', 'y', 'z', 'w', 'v']:
                position = sequence_length - ion_number
            else:
                position = ion_number

            if position < 1 or position > sequence_length:
                continue

            fragment_key = (base_type, ion_number, position)
            if fragment_key in unique_fragments:
                continue
            unique_fragments.add(fragment_key)

            color = row.get('Color', ion_offsets[base_type]['color_default'])
            y_offset = ion_offsets[base_type]['y_offset']

            yield position, base_type, color, y_offset

    def _delayed_plot_data_fragments_only(self):
        """Re-draw fragment lines on the peptide widget based on current DataFrame."""
        try:
            self.clear_fragment_lines()
            for position, base_type, color, y_offset in self._iter_fragment_positions():
                self.add_fragment_line(position, base_type, color, y_offset)
        except Exception as e:
            logger.debug(f"Fragment line refresh error: {e}")

    def plot_peptide_sequence_with_ions(self, sequence, modifications=None):
        """Plot the peptide sequence with enhanced ion fragment lines overlaid on the interactive widget"""
        self.clear_fragment_lines()
        for position, base_type, color, y_offset in self._iter_fragment_positions():
            self.add_fragment_line(position, base_type, color, y_offset)

    def remove_fragment_line_from_peptide(self, fragment_sequence, target_mz):
        """Remove fragment line from peptide graphic based on fragment sequence"""
        try:
            self.peptide_plot.clear_fragment_lines()
            self._delayed_plot_data_fragments_only()

        except Exception as e:
            logger.debug("Error removing fragment line: %s", e)
