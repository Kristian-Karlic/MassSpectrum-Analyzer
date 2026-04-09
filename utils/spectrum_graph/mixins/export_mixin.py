import logging
import os
import re

import pandas as pd
import pyqtgraph as pg
from pyqtgraph.exporters import SVGExporter

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QMessageBox

from ..config.constants import PlotConstants
from ..config.file_utils import get_save_filename, save_dataframe_to_file
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class ExportMixin:
    """Export functionality for MassSpecViewer (SVG, CSV, XLSX)."""

    def export_matched_fragments(self):
        """Export matched fragments data"""
        if not hasattr(self, 'matched_df') or self.matched_df is None or self.matched_df.empty:
            QMessageBox.warning(self, "Warning", "No matched fragments data to export.")
            return

        default_filename = self.generate_default_filename()
        if default_filename:
            default_filename += "_matched_data.csv"
        else:
            default_filename = "matched_data.csv"

        filename = get_save_filename(
            self,
            "Export Matched Fragments",
            default_filename,
            "CSV files (*.csv);;Excel files (*.xlsx);;All files (*.*)"
        )

        if filename:
            save_dataframe_to_file(self, self.matched_df, filename, "Matched Fragments")

    def export_theoretical_fragments(self):
        """Export theoretical fragments data"""
        if not hasattr(self, 'theoretical_df') or self.theoretical_df is None or self.theoretical_df.empty:
            QMessageBox.warning(self, "Warning", "No theoretical fragments data to export.")
            return

        default_filename = self.generate_default_filename()
        if default_filename:
            default_filename += "_theoretical_data.csv"
        else:
            default_filename = "theoretical_data.csv"

        filename = get_save_filename(
            self,
            "Export Theoretical Fragments",
            default_filename,
            "CSV files (*.csv);;Excel files (*.xlsx);;All files (*.*)"
        )

        if filename:
            save_dataframe_to_file(self, self.theoretical_df, filename, "Theoretical Fragments")

    def export_all_data(self):
        """Export all data (details, matched, theoretical) to Excel with multiple sheets"""
        if ((not hasattr(self, 'matched_df') or self.matched_df is None or self.matched_df.empty) and
            (not hasattr(self, 'theoretical_df') or self.theoretical_df is None or self.theoretical_df.empty)):
            QMessageBox.warning(self, "Warning", "No data to export.")
            return

        default_filename = self.generate_default_filename()
        if default_filename:
            default_filename += "_data.xlsx"
        else:
            default_filename = "fragment_data.xlsx"

        filename = get_save_filename(
            self,
            "Export All Data",
            default_filename,
            "Excel files (*.xlsx);;CSV files (*.csv)"
        )

        if filename:
            self._export_all_data_to_file(filename)

    def export_combined_svg_and_data(self):
        """Export both SVG and all data with the same base filename"""


        # Check if we have data to export
        has_data = ((hasattr(self, 'matched_df') and self.matched_df is not None and not self.matched_df.empty) or
                    (hasattr(self, 'theoretical_df') and self.theoretical_df is not None and not self.theoretical_df.empty))

        if not has_data:
            QMessageBox.warning(self, "Warning", "No data to export.")
            return

        # Get base filename for both exports
        default_filename = self.generate_default_filename()
        if not default_filename:
            default_filename = "fragment_export"

        filename = get_save_filename(
            self,
            "Export SVG + All Data (will create 2 files)",
            default_filename,
            "All files (*)"
        )

        if filename:
            try:
                # Remove any extension to get base name
                base_name = os.path.splitext(filename)[0]

                # Export SVG with _spectrum suffix
                svg_filename = f"{base_name}_spectrum.svg"
                self._export_svg_to_file(svg_filename)

                # Export data with _data suffix
                data_filename = f"{base_name}_data.xlsx"
                self._export_all_data_to_file(data_filename)

                QMessageBox.information(
                    self,
                    "Success",
                    f"Files exported successfully:\n• {svg_filename}\n• {data_filename}"
                )

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export files:\n{str(e)}")


    def _export_svg_to_file(self, filename):
        """Export SVG to specific filename with legend included"""
        legend_items = []
        annotation_backup = []
        try:
            # Swap annotation text items to HTML format before SVG export.
            # Unicode superscript characters ⁺ (U+207A, Superscripts block) and ² / ³
            # (U+00B2/U+00B3, Latin-1 Supplement) are in different Unicode ranges. Qt's
            # text shaper can split them into separate font runs, and QSvgGenerator then
            # serialises each run with its own x-coordinates, producing a visible gap
            # between + and the digit in the exported SVG. Using HTML <sup>+2</sup>
            # keeps + and 2 as plain ASCII in one font run, so no gap appears.
            annotation_backup = self._swap_to_html_annotations()

            # Add legend text items to the peptide plot temporarily
            legend_items = self._add_legend_to_scene()

            # Export the scene
            exporter = SVGExporter(self.glw.scene())
            exporter.export(filename)
            logger.debug(f"SVG exported to: {filename}")

        except Exception as e:
            raise Exception(f"SVG export failed: {str(e)}")
        finally:
            # Always remove legend items and restore Unicode annotations after export
            self._remove_legend_from_scene(legend_items)
            self._restore_unicode_annotations(annotation_backup)

    def _swap_to_html_annotations(self):
        """Temporarily replace Unicode annotation text with HTML-tagged equivalents on all
        matched text items. Returns a list of (item, original_html) tuples for restoration."""
        backup = []
        for item in getattr(self, 'matched_items', []):
            html_annotation = getattr(item, '_html_annotation', None)
            if html_annotation is not None:
                backup.append((item, item.toHtml()))
                item.setHtml(html_annotation)
        return backup

    def _restore_unicode_annotations(self, backup):
        """Restore original Unicode annotation HTML on text items after SVG export."""
        for item, original_html in backup:
            item.setHtml(original_html)

    def _add_legend_to_scene(self):
        """Add modification legend as graphics items to the peptide plot for SVG export.

        Everything is placed on a single horizontal row so there is no risk of
        vertical overlap with other content regardless of the plot's pixel height.
        """
        legend_items = []

        if not hasattr(self, 'legend') or not self.legend:
            return legend_items

        y_pos = 170   # Near top of peptide plot (y range -200 to 200)
        x_offset = 5

        # --- Modification colours ---
        if not self.legend.modification_colors:
            text_item = pg.TextItem(
                text="Modifications: None",
                color=EditorConstants.TEXT_COLOR(),
                anchor=(0, 0.5)
            )
            text_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, 10))
            text_item.setPos(x_offset, y_pos)
            self.peptide_plot.addItem(text_item)
            legend_items.append(text_item)
            x_offset += len("Modifications: None") * 2 + 2
        else:
            title_item = pg.TextItem(
                text="Modifications:",
                color=EditorConstants.TEXT_COLOR(),
                anchor=(0, 0.5)
            )
            title_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, 10, QFont.Weight.Bold))
            title_item.setPos(x_offset, y_pos)
            self.peptide_plot.addItem(title_item)
            legend_items.append(title_item)

            x_offset += 80

            for mass, (color, name, count) in sorted(self.legend.modification_colors.items()):
                color_box = pg.ScatterPlotItem(
                    pos=[(x_offset, y_pos)],
                    size=12,
                    brush=pg.mkBrush(color),
                    pen=pg.mkPen(EditorConstants.TEXT_COLOR(), width=1),
                    symbol='s'
                )
                self.peptide_plot.addItem(color_box)
                legend_items.append(color_box)

                x_offset += 4

                mod_text = f"{name} (×{count})" if count > 1 else name
                text_item = pg.TextItem(
                    text=mod_text,
                    color=EditorConstants.TEXT_COLOR(),
                    anchor=(0, 0.5)
                )
                text_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, 10))
                text_item.setPos(x_offset, y_pos)
                self.peptide_plot.addItem(text_item)
                legend_items.append(text_item)

                x_offset += len(mod_text) * 6 + 8

        # --- NL / labile / remainder symbol entries (same row, separated by " | ") ---
        nl_entries = getattr(self, 'nl_legend_entries', [])
        if nl_entries:
            sep_item = pg.TextItem(
                text=" | ",
                color=EditorConstants.TEXT_COLOR(),
                anchor=(0, 0.5)
            )
            sep_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, 10))
            sep_item.setPos(x_offset, y_pos)
            self.peptide_plot.addItem(sep_item)
            legend_items.append(sep_item)
            x_offset += 15

            for symbol, label, mass_da, mod_name in nl_entries:
                sign = "+" if mass_da >= 0 else ""
                entry_text = f"{symbol} = {sign}{mass_da:.3f} Da ({mod_name}, {label})"
                nl_item = pg.TextItem(
                    text=entry_text,
                    color=EditorConstants.TEXT_COLOR(),
                    anchor=(0, 0.5)
                )
                nl_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, 10))
                nl_item.setPos(x_offset, y_pos)
                self.peptide_plot.addItem(nl_item)
                legend_items.append(nl_item)
                x_offset += len(entry_text) * 6 + 6

        return legend_items

    def _remove_legend_from_scene(self, legend_items):
        """Remove temporary legend items from the scene after SVG export"""
        for item in legend_items:
            try:
                self.peptide_plot.removeItem(item)
            except Exception:
                pass  # Ignore removal errors

    def _export_all_data_to_file(self, filename):
        """Export all data to specific filename"""

        # Get selected row data
        selected_row_df = None
        if hasattr(self, 'row_data') and self.row_data:
            selected_row_df = pd.DataFrame([self.row_data])

        # Get peptide info export data from the annotation tab
        peptide_info_df = None
        try:
            from utils.utility_classes.widgets import get_main_window
            main_window = get_main_window(self, 'mass_spec_viewer')
            if main_window and hasattr(main_window, 'annotation_tab_manager'):
                piw = main_window.annotation_tab_manager.peptide_info_widget
                if piw:
                    export_data = piw.get_export_data()
                    if export_data:
                        peptide_info_df = pd.DataFrame([export_data])
        except Exception:
            pass

        try:
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                # Save to Excel with multiple sheets
                with pd.ExcelWriter(filename, engine='openpyxl') as writer:

                    # Sheet 1: Complete Details Data (selected row)
                    if selected_row_df is not None and not selected_row_df.empty:
                        selected_row_df.to_excel(writer, sheet_name='Complete Details', index=False)

                    # Sheet 2: Peptide Info (annotation summary, scores, ion counts/intensities)
                    if peptide_info_df is not None and not peptide_info_df.empty:
                        peptide_info_df.to_excel(writer, sheet_name='Peptide Info', index=False)

                    # Sheet 3: Matched Fragments
                    if hasattr(self, 'matched_df') and self.matched_df is not None and not self.matched_df.empty:
                        self.matched_df.to_excel(writer, sheet_name='Matched Fragments', index=False)

                    # Sheet 4: Theoretical Fragments
                    if hasattr(self, 'theoretical_df') and self.theoretical_df is not None and not self.theoretical_df.empty:
                        self.theoretical_df.to_excel(writer, sheet_name='Theoretical Fragments', index=False)
            else:
                # Save as separate CSV files
                base_name = filename.replace('.csv', '')

                # Complete details CSV
                if selected_row_df is not None and not selected_row_df.empty:
                    details_filename = f"{base_name}_complete_details.csv"
                    selected_row_df.to_csv(details_filename, index=False)

                # Peptide info CSV
                if peptide_info_df is not None and not peptide_info_df.empty:
                    peptide_info_filename = f"{base_name}_peptide_info.csv"
                    peptide_info_df.to_csv(peptide_info_filename, index=False)

                # Matched fragments CSV
                if hasattr(self, 'matched_df') and self.matched_df is not None and not self.matched_df.empty:
                    matched_filename = f"{base_name}_matched.csv"
                    self.matched_df.to_csv(matched_filename, index=False)

                # Theoretical fragments CSV
                if hasattr(self, 'theoretical_df') and self.theoretical_df is not None and not self.theoretical_df.empty:
                    theoretical_filename = f"{base_name}_theoretical.csv"
                    self.theoretical_df.to_csv(theoretical_filename, index=False)

        except Exception as e:
            raise Exception(f"Data export failed: {str(e)}")

    def export_svg(self):
        """Export the entire plot scene as SVG using PyQtGraph's built-in exporter"""
        try:
            # Get default filename with _spectrum suffix
            default_filename = self.generate_default_filename()
            if default_filename:
                default_filename += "_spectrum.svg"
            else:
                default_filename = "spectrum.svg"

            filename = get_save_filename(
                self,
                "Export SVG",
                default_filename,
                "SVG files (*.svg);;All files (*.*)"
            )

            if filename:
                self._export_svg_to_file(filename)
                QMessageBox.information(self, "Success", f"SVG exported to:\n{filename}")

        except Exception as e:
            logger.error(f"Failed to export SVG: {e}")
            QMessageBox.warning(self, "Export Error", f"Failed to export SVG:\n{str(e)}")

    def generate_default_filename(self):
        """Generate a default filename based on peptide, spectrum file, and scan index"""
        if not hasattr(self, 'peptide') or not self.peptide or not hasattr(self, 'row_data') or not self.row_data:
            return "fragment_data"

        # Get peptide sequence (clean it for filename)
        peptide = self.peptide.replace(" ", "_")

        # Get spectrum file name (without extension)
        spectrum_file = ""
        for key in ["Spectrum file", "spectrum_file", "Raw file", "raw_file", "File", "file"]:
            if key in self.row_data and self.row_data[key]:
                full_filename = str(self.row_data[key])
                # Remove file extension and path
                spectrum_file = os.path.splitext(os.path.basename(full_filename))[0]
                break

        # Get scan index
        index = ""
        for key in ["index", "Scan", "scan", "Scan Number", "scan_number"]:
            if key in self.row_data and self.row_data[key]:
                index = str(self.row_data[key])
                break

        # Build the base filename: Peptide-SpectrumFile-index
        components = []
        if peptide:
            components.append(peptide)
        if spectrum_file:
            components.append(spectrum_file)
        if index:
            components.append(index)

        # Join with hyphens
        base_filename = "-".join(components) if components else "fragment_data"

        return base_filename
