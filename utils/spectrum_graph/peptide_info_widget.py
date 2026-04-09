from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from utils.style.style import EditorConstants
from utils.spectrum_graph.config.constants import matched_mask
import pandas as pd

# Colour palette for pie-chart segments (enough contrast for up to 8 slices)
_SEGMENT_PALETTE = [
    '#5B9BD5', '#ED7D31', '#70AD47', '#FFC000',
    '#E74C3C', '#9B59B6', '#1ABC9C', '#95A5A6',
]


class MiniDonutWidget(QWidget):
    """A small donut / ring chart showing numerator / denominator."""

    def __init__(self, parent=None, size=52):
        super().__init__(parent)
        self._numerator = 0
        self._denominator = 1
        self._label_text = ""
        self._value_text = ""
        self._size = size
        self.setFixedSize(size, size + 30)  # extra height for text below

    def set_data(self, numerator, denominator, label, value_text=None):
        self._numerator = numerator
        self._denominator = max(denominator, 1)
        self._label_text = label
        self._value_text = value_text or f"{numerator}/{denominator}"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ring_size = self._size - 8
        ring_width = 7
        cx = self._size / 2
        cy = ring_size / 2 + 4

        rect = QRectF(cx - ring_size / 2, cy - ring_size / 2, ring_size, ring_size)

        # Background ring (grey)
        bg_color = QColor(EditorConstants.GRAY_200())
        pen = QPen(bg_color, ring_width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        # Foreground arc (accent)
        fraction = self._numerator / self._denominator if self._denominator else 0
        fraction = min(fraction, 1.0)
        if fraction > 0:
            accent = QColor("#5B9BD5")  # steel blue
            pen2 = QPen(accent, ring_width)
            pen2.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen2)
            span = int(fraction * 360 * 16)
            painter.drawArc(rect, 90 * 16, -span)  # start at 12 o'clock, clockwise

        # Value text below the ring
        text_color = QColor(EditorConstants.TEXT_COLOR())
        painter.setPen(text_color)
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        text_y = cy + ring_size / 2 + 12
        painter.drawText(QRectF(0, text_y, self._size, 14),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         self._value_text)

        painter.end()


class IonDistributionWidget(QWidget):
    """Segmented pie chart showing the sub-type distribution for one base ion type.

    Layout: title centred at top, legend items stacked on the left,
    pie chart on the right.
    """

    _PIE_DIAM = 60
    _TITLE_H = 18
    _LEGEND_LINE_H = 16
    _LEGEND_X = 4
    _PAD = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._segments = []  # list of (label, count, fraction, color, pct_text)
        self._total = 0

    def set_data(self, title, total, segments, formatted_title=None):
        """
        title:    base type name (e.g. "y")
        total:    sum of all sub-type counts
        segments: list of (short_label, count) sorted largest-first
        formatted_title: optional override for the title string
        """
        self._title = formatted_title if formatted_title is not None else f"{title}: {total}"
        self._total = total
        self._segments = []
        for i, (label, count) in enumerate(segments):
            frac = count / total if total > 0 else 0
            color = _SEGMENT_PALETTE[i % len(_SEGMENT_PALETTE)]
            pct = f"{frac * 100:.0f}%"
            self._segments.append((label, count, frac, color, pct))

        # Height = title + max(pie, legend) + padding
        n = len(self._segments)
        legend_h = n * self._LEGEND_LINE_H
        content_h = max(self._PIE_DIAM, legend_h)
        self.setFixedHeight(self._TITLE_H + content_h + self._PAD)
        self.update()

    def paintEvent(self, event):
        if not self._segments:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        text_color = QColor(EditorConstants.TEXT_COLOR())

        # ── Title ──
        painter.setPen(text_color)
        title_font = QFont()
        title_font.setPixelSize(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(0, 0, w, self._TITLE_H),
                         Qt.AlignmentFlag.AlignCenter, self._title)

        # ── Geometry ──
        pie_diam = self._PIE_DIAM
        pie_x = w - pie_diam - 4          # right-align pie
        pie_y = self._TITLE_H             # top of content area
        rect = QRectF(pie_x, pie_y, pie_diam, pie_diam)

        outline_pen = QPen(text_color, 1.2)

        # ── Pie chart ──
        if len(self._segments) == 1:
            painter.setPen(outline_pen)
            painter.setBrush(QColor(self._segments[0][3]))
            painter.drawEllipse(rect)
        else:
            spans = []
            remaining = 360 * 16
            for i, (_, _, frac, _, _) in enumerate(self._segments):
                if i == len(self._segments) - 1:
                    spans.append(remaining)
                else:
                    s = round(frac * 360 * 16)
                    spans.append(s)
                    remaining -= s

            start = 90 * 16
            for i, (_, _, _, color, _) in enumerate(self._segments):
                span = spans[i]
                if span <= 0:
                    continue
                painter.setPen(outline_pen)
                painter.setBrush(QColor(color))
                painter.drawPie(rect, start, -span)
                start -= span

        # ── Legend (stacked vertically on the left) ──
        legend_font = QFont()
        legend_font.setPixelSize(11)
        painter.setFont(legend_font)

        # Vertically centre the legend block against the pie
        n = len(self._segments)
        legend_block_h = n * self._LEGEND_LINE_H
        legend_y_start = pie_y + (pie_diam - legend_block_h) / 2
        legend_y_start = max(legend_y_start, pie_y)

        avail_text_w = pie_x - self._LEGEND_X - 6  # leave gap before pie

        for i, (label, _count, _frac, color, pct) in enumerate(self._segments):
            y = legend_y_start + i * self._LEGEND_LINE_H

            # Coloured square
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(self._LEGEND_X, y + 2, 8, 8))

            # Label text
            painter.setPen(text_color)
            painter.drawText(
                QRectF(self._LEGEND_X + 11, y, avail_text_w, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{label} {pct}")

        painter.end()


class PeptideInfoWidget(QWidget):
    # Signal to open analysis dialog
    analysisRequested = pyqtSignal(object, object)  # Will emit matched_data

    def __init__(self):
        super().__init__()
        self.current_matched_data = None
        self.setup_ui()

    def setup_ui(self):
        """Setup the UI components with overall scrolling support"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header row with column labels
        pie_header = QWidget()
        pie_header_layout = QHBoxLayout(pie_header)
        pie_header_layout.setContentsMargins(0, 0, 0, 0)
        pie_header_layout.setSpacing(4)
        for label_text in ["Theor.\nFrags", "Peaks", "TIC", "Cov."]:
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    color: {EditorConstants.TEXT_COLOR()};
                    padding: 0px;
                }}
            """)
            pie_header_layout.addWidget(lbl)
        layout.addWidget(pie_header)

        # Donut widgets row
        pie_row = QWidget()
        pie_row_layout = QHBoxLayout(pie_row)
        pie_row_layout.setContentsMargins(0, 0, 0, 0)
        pie_row_layout.setSpacing(4)
        self.pie_theor = MiniDonutWidget(size=52)
        self.pie_peaks = MiniDonutWidget(size=52)
        self.pie_int = MiniDonutWidget(size=52)
        self.pie_cov = MiniDonutWidget(size=52)
        for w in [self.pie_theor, self.pie_peaks, self.pie_int, self.pie_cov]:
            pie_row_layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(pie_row)

        # ── Score labels ───────────────────────────────────────────
        self.fragmented_bonds_label = self.create_info_label("Fragmented Bonds: -")
        self.annotated_tic_label = self.create_info_label("Annotated TIC: -")
        self.rescore_label = self.create_info_label("X!Tandem: -")
        self.consecutive_label = self.create_info_label("Longest Consecutive: -")
        self.complementary_label = self.create_info_label("Complementary Pairs: -")
        self.morpheus_label = self.create_info_label("Morpheus Score: -")

        layout.addWidget(self.rescore_label)
        layout.addWidget(self.consecutive_label)
        layout.addWidget(self.complementary_label)
        layout.addWidget(self.morpheus_label)

        # ── Ion counts section ─────────────────────────────────────
        ion_counts_title = QLabel("Ion counts")
        ion_counts_title.setStyleSheet(f"""
            QLabel {{
                font-size: 12px;
                font-weight: bold;
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                padding: 4px 0px;
                margin-top: 5px;
            }}
        """)
        layout.addWidget(ion_counts_title)

        # Container for ion distribution pie charts
        self.ion_counts_container = QWidget()
        self.ion_counts_layout = QVBoxLayout(self.ion_counts_container)
        self.ion_counts_layout.setContentsMargins(5, 5, 5, 5)
        self.ion_counts_layout.setSpacing(6)

        self.ion_counts_container.setStyleSheet(f"""
            QWidget {{
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
                background-color: {EditorConstants.GRAY_50()};
            }}
        """)

        layout.addWidget(self.ion_counts_container)

        # ── Ion intensities section ───────────────────────────────
        ion_intensities_title = QLabel("Ion Intensities (%)")
        ion_intensities_title.setStyleSheet(f"""
            QLabel {{
                font-size: 12px;
                font-weight: bold;
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                padding: 4px 0px;
                margin-top: 5px;
            }}
        """)
        layout.addWidget(ion_intensities_title)

        self.ion_intensities_container = QWidget()
        self.ion_intensities_layout = QVBoxLayout(self.ion_intensities_container)
        self.ion_intensities_layout.setContentsMargins(5, 5, 5, 5)
        self.ion_intensities_layout.setSpacing(6)

        self.ion_intensities_container.setStyleSheet(f"""
            QWidget {{
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
                background-color: {EditorConstants.GRAY_50()};
            }}
        """)

        layout.addWidget(self.ion_intensities_container)

    def update_theme(self):
        """Update all widgets to match the current theme"""
        for label in [self.rescore_label,
                      self.consecutive_label, self.complementary_label,
                      self.morpheus_label]:
            label.setStyleSheet(f"""
                QLabel {{
                    font-size: 13px;
                    padding: 6px 10px;
                    background-color: {EditorConstants.GRAY_50()};
                    border: 1px solid {EditorConstants.GRAY_200()};
                    border-radius: 3px;
                    color: {EditorConstants.TEXT_COLOR()};
                }}
            """)

        # Repaint pie charts to pick up new theme colours
        for w in [self.pie_theor, self.pie_peaks, self.pie_int, self.pie_cov]:
            w.update()

        # Update section titles
        for child in self.findChildren(QLabel):
            if child.text() in ("Ion Type Counts", "Ion Type Intensities", "Annotation"):
                child.setStyleSheet(f"""
                    QLabel {{
                        font-size: 12px;
                        font-weight: bold;
                        color: {EditorConstants.HEADER_TEXT_COLOR()};
                        padding: 4px 0px;
                        margin-top: 5px;
                    }}
                """)

        # Update ion counts container
        self.ion_counts_container.setStyleSheet(f"""
            QWidget {{
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
                background-color: {EditorConstants.GRAY_50()};
            }}
        """)

        # Update ion intensities container
        self.ion_intensities_container.setStyleSheet(f"""
            QWidget {{
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
                background-color: {EditorConstants.GRAY_50()};
            }}
        """)

        # Recreate ion count/intensity charts with new theme
        if hasattr(self, 'current_matched_data') and self.current_matched_data is not None:
            self.update_ion_counts(self.current_matched_data)
            self.update_ion_intensities(self.current_matched_data)

    def create_info_label(self, text):
        """Create a styled info label with larger text"""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                padding: 6px 10px;
                background-color: {EditorConstants.GRAY_50()};
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
                color: {EditorConstants.TEXT_COLOR()};
            }}
        """)
        return label

    # ================================================================
    # UPDATE ENTRY POINT
    # ================================================================

    def update_peptide_info(self, peptide="", fragmented_bonds="", annotated_tic="",
                            matched_data=None, rescore=None, theoretical_data=None):
        """Update all peptide information.

        rescore can be:
            - a dict with keys: hyperscore, consecutive_series, complementary_pairs
            - a float (legacy: treated as hyperscore only)
            - None
        """
        # Store current data for analysis
        self.current_matched_data = matched_data

        # Store current calculated values for spectrum tracker access
        self.current_fragmented_bonds = fragmented_bonds
        self.current_annotated_tic = annotated_tic

        self.fragmented_bonds_label.setText(f"Fragmented Bonds: {fragmented_bonds}")
        self.annotated_tic_label.setText(f"Annotated TIC: {annotated_tic}")

        # ── Update annotation pie charts ───────────────────────────
        self._update_pie_charts(peptide, matched_data, theoretical_data)

        # Update score labels
        if rescore is not None and isinstance(rescore, dict):
            hs = rescore.get('xtandem', 0.0)
            self.rescore_label.setText(f"X!Tandem: {hs:.4f}" if hs else "X!Tandem: -")

            consec = rescore.get('consecutive_series')
            if consec is not None and isinstance(consec, dict):
                self.consecutive_label.setVisible(True)
                longest = consec.get('longest', 0)
                per_type = consec.get('per_type', {})
                if per_type:
                    details = ", ".join(f"{k}:{v}" for k, v in sorted(per_type.items()) if v > 0)
                    self.consecutive_label.setText(
                        f"Longest Consecutive: {longest}  ({details})"
                    )
                else:
                    self.consecutive_label.setText(f"Longest Consecutive: {longest}")
            else:
                self.consecutive_label.setVisible(False)

            comp = rescore.get('complementary_pairs')
            if comp is not None and isinstance(comp, dict):
                self.complementary_label.setVisible(True)
                pairs = comp.get('pairs', 0)
                possible = comp.get('possible', 0)
                self.complementary_label.setText(
                    f"Complementary Pairs: {pairs}/{possible}"
                )
            else:
                self.complementary_label.setVisible(False)

            morph = rescore.get('morpheus_score')
            if morph is not None:
                self.morpheus_label.setVisible(True)
                self.morpheus_label.setText(f"Morpheus Score: {morph:.4f}")
            else:
                self.morpheus_label.setVisible(False)

        elif rescore is not None:
            self.rescore_label.setText(f"X!Tandem: {rescore:.4f}")
            self.consecutive_label.setVisible(False)
            self.complementary_label.setVisible(False)
            self.morpheus_label.setVisible(False)
        else:
            self.rescore_label.setText("X!Tandem: -")
            self.consecutive_label.setVisible(False)
            self.complementary_label.setVisible(False)
            self.morpheus_label.setVisible(False)

        # Update ion counts and intensities
        self.update_ion_counts(matched_data)
        self.update_ion_intensities(matched_data)

    # ================================================================
    # ANNOTATION SUMMARY DONUTS
    # ================================================================

    def _update_pie_charts(self, peptide, matched_data, theoretical_data):
        """Compute stats and update the four annotation donut charts."""
        if matched_data is None or matched_data.empty:
            for w in [self.pie_theor, self.pie_peaks, self.pie_int, self.pie_cov]:
                w.set_data(0, 1, "", "\u2013")
            return

        mask = matched_mask(matched_data)
        total_peaks = len(matched_data)
        matched_peaks_count = int(mask.sum())

        # ── Pie 1: Theoretical fragments ──
        theor_matched = 0
        theor_total = 0
        if theoretical_data is not None and not theoretical_data.empty:
            theor_total = len(theoretical_data)
            mono_matched = matched_data[mask].copy()
            if 'Isotope' in mono_matched.columns:
                mono_matched = mono_matched[
                    pd.to_numeric(mono_matched['Isotope'], errors='coerce') == 0
                ]
            if 'Ion Type' in mono_matched.columns and 'Ion Number' in mono_matched.columns:
                theor_matched = mono_matched.drop_duplicates(
                    subset=['Ion Type', 'Ion Number']
                ).shape[0]
            else:
                theor_matched = len(mono_matched)
        self.pie_theor.set_data(theor_matched, theor_total, "theor. frag.",
                                f"{theor_matched}/{theor_total}")

        # ── Pie 2: Peaks annotated ──
        self.pie_peaks.set_data(matched_peaks_count, total_peaks, "peaks",
                                f"{matched_peaks_count}/{total_peaks}")

        # ── Pie 3: Annotated TIC (intensity) — show as percentage ──
        total_int = matched_data['intensity'].sum()
        matched_int = matched_data[mask]['intensity'].sum()
        if total_int > 0:
            pct = (matched_int / total_int) * 100
            int_text = f"{pct:.1f}%"
        else:
            int_text = "0%"
        self.pie_int.set_data(matched_int, total_int, "int.", int_text)

        # ── Pie 4: Fragmented bonds (coverage) ──
        cov_num, cov_den = self._parse_fraction(
            getattr(self, 'current_fragmented_bonds', '0/0')
        )
        self.pie_cov.set_data(cov_num, cov_den, "cov.", f"{cov_num}/{cov_den}")

    @staticmethod
    def _parse_fraction(text):
        """Parse '8/14' style string into (numerator, denominator)."""
        try:
            parts = text.split('/')
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 0, 0

    # ================================================================
    # ION TYPE DISTRIBUTION PIE CHARTS
    # ================================================================

    def update_ion_counts(self, matched_data):
        """Replace ion count text with segmented pie charts per base type (2 per row)."""
        # Clear existing widgets
        while self.ion_counts_layout.count():
            child = self.ion_counts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if matched_data is None or matched_data.empty:
            no_data_label = QLabel("No ion data available")
            no_data_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    color: {EditorConstants.TEXT_COLOR()};
                    font-style: italic;
                    padding: 4px 6px;
                }}
            """)
            self.ion_counts_layout.addWidget(no_data_label)
            return

        base_counts, ion_type_counts = self.calculate_ion_counts(matched_data)

        # Collect charts to place in grid
        charts = []
        for base_type, base_count in base_counts.items():
            if base_count <= 0:
                continue

            segments = []
            for ion_type, count in ion_type_counts.items():
                if ion_type[0] == base_type:
                    segments.append((ion_type[1], count))

            segments.sort(key=lambda t: t[1], reverse=True)

            if not segments:
                segments = [(base_type, base_count)]

            chart = IonDistributionWidget()
            chart.set_data(base_type, base_count, segments)
            charts.append(chart)

        # Lay out in a 2-column grid
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(4)

        for i, chart in enumerate(charts):
            grid_layout.addWidget(chart, i // 2, i % 2)

        self.ion_counts_layout.addWidget(grid_widget)

    # ================================================================
    # ION COUNTING HELPERS
    # ================================================================

    def calculate_ion_counts(self, matched_data):
        """Calculate counts grouped by Base Type, with sub-counts by Ion Type.

        Returns:
            base_counts:     dict  {base_type_str: total_count}
            ion_type_counts: dict  {(base_type_str, ion_type_str): count}

        Both use the actual column values from the DataFrame — no regex
        extraction or remapping.
        """
        if matched_data is None or matched_data.empty:
            return {}, {}

        matched_peaks = matched_data[matched_mask(matched_data)].copy()
        if matched_peaks.empty:
            return {}, {}

        # Only monoisotopic peaks
        base_peaks = matched_peaks[
            pd.to_numeric(matched_peaks['Isotope'], errors='coerce') == 0
        ]

        base_counts = {}
        ion_type_counts = {}  # keyed by (base_type, ion_type)

        if 'Ion Type' in base_peaks.columns and 'Base Type' in base_peaks.columns:
            for _, row in base_peaks.iterrows():
                base_type = str(row['Base Type']).strip()
                ion_type = str(row['Ion Type']).strip()

                if not base_type or base_type in ('', 'nan', 'None'):
                    continue

                base_counts[base_type] = base_counts.get(base_type, 0) + 1

                key = (base_type, ion_type)
                ion_type_counts[key] = ion_type_counts.get(key, 0) + 1

        return base_counts, ion_type_counts

    # ================================================================
    # BOND / TIC CALCULATIONS
    # ================================================================

    def calculate_fragmented_bonds(self, peptide, matched_data):
        """Calculate the ratio of observed to potential fragment bonds"""
        if not peptide or matched_data is None or matched_data.empty:
            return "0/0"

        potential_fragments = (len(peptide) * 2) - 2

        matched_df = matched_data[matched_mask(matched_data)].copy()
        if matched_df.empty:
            return f"0/{potential_fragments}"

        unique_fragments = set()
        for _, row in matched_df.iterrows():
            base_type = str(row.get('Base Type', '')).strip()
            ion_number = row.get('Ion Number', '')

            if not base_type or pd.isna(ion_number):
                continue
            try:
                ion_num = int(ion_number)
                if base_type in ['y', 'z', 'x']:
                    unique_fragments.add(('yzx', ion_num))
                elif base_type in ['b', 'c', 'a']:
                    unique_fragments.add(('bca', ion_num))
            except (ValueError, TypeError):
                continue

        observed_fragments = len(unique_fragments)
        return f"{observed_fragments}/{potential_fragments}"

    def calculate_annotated_percentage(self, matched_data):
        """Calculate the percentage of total intensity that comes from annotated peaks"""
        if matched_data is None or matched_data.empty:
            return "0.0%"

        mask = matched_mask(matched_data)
        total_intensity = matched_data['intensity'].sum()
        matched_intensity = matched_data[mask]['intensity'].sum()

        if total_intensity > 0:
            annotated_percentage = (matched_intensity / total_intensity) * 100
            return f"{annotated_percentage:.1f}%"
        else:
            return "0.0%"

    # ================================================================
    # ION INTENSITY DISTRIBUTION
    # ================================================================

    def calculate_ion_intensities(self, matched_data):
        """Calculate intensities grouped by Base Type, with sub-intensities by Ion Type.

        Returns:
            base_intensities:     dict  {base_type_str: total_intensity}
            ion_type_intensities: dict  {(base_type_str, ion_type_str): intensity}
        """
        if matched_data is None or matched_data.empty:
            return {}, {}

        matched_peaks = matched_data[matched_mask(matched_data)].copy()
        if matched_peaks.empty:
            return {}, {}

        base_peaks = matched_peaks[
            pd.to_numeric(matched_peaks['Isotope'], errors='coerce') == 0
        ]

        intensity_col = 'intensity' if 'intensity' in base_peaks.columns else 'Intensity'
        base_intensities = {}
        ion_type_intensities = {}

        if 'Ion Type' in base_peaks.columns and 'Base Type' in base_peaks.columns:
            for _, row in base_peaks.iterrows():
                base_type = str(row['Base Type']).strip()
                ion_type = str(row['Ion Type']).strip()

                if not base_type or base_type in ('', 'nan', 'None'):
                    continue

                try:
                    intensity = float(row.get(intensity_col, 0))
                except (ValueError, TypeError):
                    continue

                base_intensities[base_type] = base_intensities.get(base_type, 0) + intensity
                key = (base_type, ion_type)
                ion_type_intensities[key] = ion_type_intensities.get(key, 0) + intensity

        return base_intensities, ion_type_intensities

    def update_ion_intensities(self, matched_data):
        """Show intensity distribution pie charts per base type (2 per row)."""
        while self.ion_intensities_layout.count():
            child = self.ion_intensities_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if matched_data is None or matched_data.empty:
            no_data = QLabel("No intensity data available")
            no_data.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    color: {EditorConstants.TEXT_COLOR()};
                    font-style: italic;
                    padding: 4px 6px;
                }}
            """)
            self.ion_intensities_layout.addWidget(no_data)
            return

        base_intensities, ion_type_intensities = self.calculate_ion_intensities(matched_data)

        charts = []
        for base_type, base_int in base_intensities.items():
            if base_int <= 0:
                continue

            segments = []
            for key, intensity in ion_type_intensities.items():
                if key[0] == base_type:
                    segments.append((key[1], intensity))

            segments.sort(key=lambda t: t[1], reverse=True)
            if not segments:
                segments = [(base_type, base_int)]

            chart = IonDistributionWidget()
            chart.set_data(base_type, base_int, segments,
                           formatted_title=base_type)
            charts.append(chart)

        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(4)

        for i, chart in enumerate(charts):
            grid_layout.addWidget(chart, i // 2, i % 2)

        self.ion_intensities_layout.addWidget(grid_widget)

    # ================================================================
    # EXPORT DATA
    # ================================================================

    def get_export_data(self):
        """Return all current peptide info data as a dict for export."""
        data = {}

        # Annotation donut summaries
        data['Theor. Frags Matched'] = self.pie_theor._numerator
        data['Theor. Frags Total'] = self.pie_theor._denominator
        data['Peaks Matched'] = self.pie_peaks._numerator
        data['Peaks Total'] = self.pie_peaks._denominator
        data['Annotated Intensity'] = self.pie_int._value_text
        data['Bond Coverage'] = self.pie_cov._value_text

        # Fragmented bonds / annotated TIC
        data['Fragmented Bonds'] = getattr(self, 'current_fragmented_bonds', '')
        data['Annotated TIC'] = getattr(self, 'current_annotated_tic', '')

        # Scores (extract from labels)
        score_labels = [
            (self.rescore_label, 'X!Tandem'),
            (self.consecutive_label, 'Longest Consecutive'),
            (self.complementary_label, 'Complementary Pairs'),
            (self.morpheus_label, 'Morpheus Score'),
        ]
        for label_widget, key in score_labels:
            if label_widget.isVisible():
                text = label_widget.text()
                if ':' in text:
                    value = text.split(':', 1)[1].strip()
                    if value and value != '-':
                        data[key] = value

        # Ion counts and intensities per sub-type
        if self.current_matched_data is not None and not self.current_matched_data.empty:
            base_counts, ion_type_counts = self.calculate_ion_counts(self.current_matched_data)
            for (base, ion_type), count in ion_type_counts.items():
                data[f'{ion_type} Count'] = count

            base_int, ion_type_int = self.calculate_ion_intensities(self.current_matched_data)
            for (base, ion_type), intensity in ion_type_int.items():
                pct = (intensity / base_int[base] * 100) if base_int.get(base, 0) > 0 else 0
                data[f'{ion_type} Intensity'] = round(intensity, 2)
                data[f'{ion_type} Intensity %'] = f"{pct:.1f}"

        return data
