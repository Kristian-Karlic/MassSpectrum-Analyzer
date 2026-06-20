import logging
import os

import pandas as pd
import pyqtgraph as pg

from PyQt6.QtGui import QPdfWriter, QPainter, QPageSize, QPageLayout
from PyQt6.QtCore import QSizeF, QRectF, QMarginsF
from PyQt6.QtWidgets import QMessageBox

from ..config.constants import PlotConstants
from ..config.file_utils import get_save_filename, save_dataframe_to_file

logger = logging.getLogger(__name__)


class ExportMixin:
    """Export functionality for MassSpecViewer (SVG, CSV, XLSX)."""

    def export_matched_fragments(self):
        """Export matched fragments data"""
        if (
            not hasattr(self, "matched_df")
            or self.matched_df is None
            or self.matched_df.empty
        ):
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
            "CSV files (*.csv);;Excel files (*.xlsx);;All files (*.*)",
        )

        if filename:
            save_dataframe_to_file(self, self.matched_df, filename, "Matched Fragments")

    def export_theoretical_fragments(self):
        """Export theoretical fragments data"""
        if (
            not hasattr(self, "theoretical_df")
            or self.theoretical_df is None
            or self.theoretical_df.empty
        ):
            QMessageBox.warning(
                self, "Warning", "No theoretical fragments data to export."
            )
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
            "CSV files (*.csv);;Excel files (*.xlsx);;All files (*.*)",
        )

        if filename:
            save_dataframe_to_file(
                self, self.theoretical_df, filename, "Theoretical Fragments"
            )

    def export_all_data(self):
        """Export all data (details, matched, theoretical) to Excel with multiple sheets"""
        if (
            not hasattr(self, "matched_df")
            or self.matched_df is None
            or self.matched_df.empty
        ) and (
            not hasattr(self, "theoretical_df")
            or self.theoretical_df is None
            or self.theoretical_df.empty
        ):
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
            "Excel files (*.xlsx);;CSV files (*.csv)",
        )

        if filename:
            self._export_all_data_to_file(filename)

    def _export_pdf_to_file(self, filename):
        """Render the visible spectrum viewer to a vector PDF.

        Two critical design choices keep fonts and layout identical to the screen:

        1. Resolution = 96 DPI (screen DPI).
           scene.render() maps source→target with a scale = target_px / source_px.
           At 300 DPI the target is 3.125× the source, so Qt multiplies every font's
           point size by 3.125 before laying it out → axis labels appear ~25 pt instead
           of 8 pt.  At 96 DPI the scale is 1.0, so fonts stay at their intended size.
           The PDF is still fully vector (all shapes and text stored as outlines) so it
           is infinitely scalable in any viewer.

        2. Source rect = mapToScene(viewport), NOT scene.sceneRect().
           PyQtGraph's sceneRect() returns the union of every item's bounding box.
           Data items (peaks, scatter) report their bounding boxes in data coordinates
           (m/z 0–2500, intensity 0–100), making sceneRect() vastly larger than the
           visible layout.  Mapping the viewport pixel rect to scene coordinates gives
           the exact visible region.
        """
        try:
            # Source rect: the portion of the scene that the viewport actually shows.
            viewport = self.glw.viewport()
            scene_visible = self.glw.mapToScene(viewport.rect()).boundingRect()

            # Page size in mm so that at 96 DPI the device-pixel count equals the
            # viewport pixel count → scale = 1.0 → no font distortion.
            SCREEN_DPI = 96.0
            MM_PER_INCH = 25.4
            width_mm = viewport.width() / SCREEN_DPI * MM_PER_INCH
            height_mm = viewport.height() / SCREEN_DPI * MM_PER_INCH

            writer = QPdfWriter(filename)
            writer.setResolution(int(SCREEN_DPI))
            writer.setPageLayout(
                QPageLayout(
                    QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter),
                    QPageLayout.Orientation.Portrait,
                    QMarginsF(0.0, 0.0, 0.0, 0.0),
                )
            )

            # Enable export mode on all PyQtGraph items that support it.
            # PlotCurveItem: disables minimum-size / downsampling optimisations that
            #   can cause thin lines (fragment indicators) to disappear at screen DPI.
            # ScatterPlotItem: re-renders symbol pixmaps at resolutionScale × native,
            #   eliminating the blurry/pixelated scatter points in the error plot.
            scene = self.glw.scene()
            export_items = []
            for item in scene.items():
                if hasattr(item, "setExportMode"):
                    try:
                        # ScatterPlotItem: resolutionScale physically enlarges the
                        # rendered symbol pixmap, so omit it to keep correct sizes.
                        # The fresh pixmap cache from setExportMode alone fixes quality.
                        # PlotCurveItem (fragment lines): antialias enables path drawing.
                        if isinstance(item, pg.ScatterPlotItem):
                            item.setExportMode(True, {"antialias": True})
                        else:
                            item.setExportMode(
                                True, {"antialias": True, "resolutionScale": 2.0}
                            )
                        export_items.append(item)
                    except Exception:
                        pass

            # writer.width() == viewport.width() at 96 DPI → 1:1 scale.
            painter = QPainter(writer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scene.render(
                painter,
                QRectF(0.0, 0.0, writer.width(), writer.height()),
                scene_visible,
            )
            # Draw legend via direct QPainter calls — bypasses pg.TextItem's
            # resetTransform() path that encodes text with an unusual PDF transform,
            # causing text to be invisible in Affinity's edit mode.
            self._draw_pdf_legend(painter, scene_visible, writer)
            painter.end()

            for item in export_items:
                try:
                    item.setExportMode(False)
                except Exception:
                    pass

            logger.debug("PDF exported to: %s", filename)
        except Exception as e:
            raise Exception(f"PDF export failed: {str(e)}")

    def _draw_pdf_legend(self, painter, scene_visible, writer):
        """Draw the modification legend directly via QPainter after scene.render().

        Bypasses pg.TextItem's resetTransform() which causes legend text to be
        invisible in Affinity's edit mode when rendered through scene.render().
        Text is drawn with painter.drawText() so it remains live/editable in PDF viewers.
        """
        if not hasattr(self, "legend") or not self.legend:
            return

        from PyQt6.QtGui import QColor, QFont, QFontMetrics, QBrush, QPen
        from PyQt6.QtCore import QRectF

        black = QColor(0, 0, 0)
        font_bold = QFont(PlotConstants.DEFAULT_FONT_FAMILY, 8)
        font_bold.setBold(True)
        font_normal = QFont(PlotConstants.DEFAULT_FONT_FAMILY, 8)
        box_h = 10
        fm_b = QFontMetrics(font_bold)

        sx = writer.width() / scene_visible.width()
        sy = writer.height() / scene_visible.height()

        try:
            pr = self.peptide_plot.sceneBoundingRect()
            vb_rect = self.peptide_plot.getViewBox().sceneBoundingRect()
            x0 = (vb_rect.left() - scene_visible.left()) * sx + 6
            pr_top_pdf = (pr.top() - scene_visible.top()) * sy
            vb_top_pdf = (vb_rect.top() - scene_visible.top()) * sy
            y0 = vb_top_pdf - fm_b.descent() - 0.4
        except Exception:
            x0, y0, pr_top_pdf, vb_top_pdf = 8, 14, 0, 20

        # White strip covers only the axis margin (plot-item top → viewbox top).
        # Staying above the viewbox prevents the strip from clipping fragment
        # indicator brackets whose tops reach the very top of the data area.
        margin_h = vb_top_pdf - pr_top_pdf
        if margin_h > 0:
            painter.fillRect(
                QRectF(0.0, float(pr_top_pdf), float(writer.width()), float(margin_h)),
                QColor(255, 255, 255),
            )

        painter.setPen(black)

        def pt(x, y, text, fnt):
            painter.setFont(fnt)
            painter.drawText(int(x), int(y), text)

        if not self.legend.modification_colors:
            pt(x0, y0, "Modifications: None", font_bold)
            return

        label = "Modifications:  "
        pt(x0, y0, label, font_bold)
        x = x0 + QFontMetrics(font_bold).horizontalAdvance(label)

        fm = QFontMetrics(font_normal)

        for _mass, (color, name, count) in sorted(
            self.legend.modification_colors.items()
        ):
            try:
                qc = (
                    color
                    if isinstance(color, QColor)
                    else (
                        QColor(*color)
                        if isinstance(color, (list, tuple))
                        else QColor(color)
                    )
                )
            except Exception:
                qc = QColor(128, 128, 128)

            painter.setBrush(QBrush(qc))
            painter.setPen(QPen(black, 0.5))
            painter.drawRect(int(x), int(y0 - box_h + 2), box_h, box_h)
            painter.setPen(black)
            x += box_h + 3

            mod_text = f"{name} (×{count})  " if count > 1 else f"{name}  "
            pt(x, y0, mod_text, font_normal)
            x += fm.horizontalAdvance(mod_text)

        nl_entries = getattr(self, "nl_legend_entries", [])
        if nl_entries:
            sep = "  |  "
            pt(x, y0, sep, font_normal)
            x += fm.horizontalAdvance(sep)
            for symbol, lbl, mass_da, mod_name in nl_entries:
                sign = "+" if mass_da >= 0 else ""
                entry = f"{symbol} = {sign}{mass_da:.3f} Da ({mod_name}, {lbl})  "
                pt(x, y0, entry, font_normal)
                x += fm.horizontalAdvance(entry)

    def _export_all_data_to_file(self, filename):
        """Export all data to specific filename"""

        # Get selected row data
        selected_row_df = None
        if hasattr(self, "row_data") and self.row_data:
            selected_row_df = pd.DataFrame([self.row_data])

        # Get peptide info export data from the annotation tab
        peptide_info_df = None
        try:
            from utils.utility_classes.widgets import get_main_window

            main_window = get_main_window(self, "mass_spec_viewer")
            if main_window and hasattr(main_window, "annotation_tab_manager"):
                piw = main_window.annotation_tab_manager.peptide_info_widget
                if piw:
                    export_data = piw.get_export_data()
                    if export_data:
                        peptide_info_df = pd.DataFrame([export_data])
        except Exception:
            pass

        try:
            if filename.endswith(".xlsx") or filename.endswith(".xls"):
                # Save to Excel with multiple sheets
                with pd.ExcelWriter(filename, engine="openpyxl") as writer:

                    # Sheet 1: Complete Details Data (selected row)
                    if selected_row_df is not None and not selected_row_df.empty:
                        selected_row_df.to_excel(
                            writer, sheet_name="Complete Details", index=False
                        )

                    # Sheet 2: Peptide Info (annotation summary, scores, ion counts/intensities)
                    if peptide_info_df is not None and not peptide_info_df.empty:
                        peptide_info_df.to_excel(
                            writer, sheet_name="Peptide Info", index=False
                        )

                    # Sheet 3: Matched Fragments
                    if (
                        hasattr(self, "matched_df")
                        and self.matched_df is not None
                        and not self.matched_df.empty
                    ):
                        self.matched_df.to_excel(
                            writer, sheet_name="Matched Fragments", index=False
                        )

                    # Sheet 4: Theoretical Fragments
                    if (
                        hasattr(self, "theoretical_df")
                        and self.theoretical_df is not None
                        and not self.theoretical_df.empty
                    ):
                        self.theoretical_df.to_excel(
                            writer, sheet_name="Theoretical Fragments", index=False
                        )
            else:
                # Save as separate CSV files
                base_name = filename.replace(".csv", "")

                # Complete details CSV
                if selected_row_df is not None and not selected_row_df.empty:
                    details_filename = f"{base_name}_complete_details.csv"
                    selected_row_df.to_csv(details_filename, index=False)

                # Peptide info CSV
                if peptide_info_df is not None and not peptide_info_df.empty:
                    peptide_info_filename = f"{base_name}_peptide_info.csv"
                    peptide_info_df.to_csv(peptide_info_filename, index=False)

                # Matched fragments CSV
                if (
                    hasattr(self, "matched_df")
                    and self.matched_df is not None
                    and not self.matched_df.empty
                ):
                    matched_filename = f"{base_name}_matched.csv"
                    self.matched_df.to_csv(matched_filename, index=False)

                # Theoretical fragments CSV
                if (
                    hasattr(self, "theoretical_df")
                    and self.theoretical_df is not None
                    and not self.theoretical_df.empty
                ):
                    theoretical_filename = f"{base_name}_theoretical.csv"
                    self.theoretical_df.to_csv(theoretical_filename, index=False)

        except Exception as e:
            raise Exception(f"Data export failed: {str(e)}")

    def export_pdf(self):
        """Export the full plot scene as a vector PDF."""
        try:
            default_filename = self.generate_default_filename()
            default_filename = (
                (default_filename + "_spectrum.pdf")
                if default_filename
                else "spectrum.pdf"
            )

            filename = get_save_filename(
                self,
                "Export PDF",
                default_filename,
                "PDF files (*.pdf);;All files (*.*)",
            )
            if filename:
                self._export_pdf_to_file(filename)
                QMessageBox.information(
                    self, "Success", f"PDF exported to:\n{filename}"
                )
        except Exception as e:
            logger.error(f"Failed to export PDF: {e}")
            QMessageBox.warning(
                self, "Export Error", f"Failed to export PDF:\n{str(e)}"
            )

    def export_combined_pdf_and_data(self):
        """Export both a vector PDF spectrum and all data (Excel) with a shared base name."""
        has_data = (
            hasattr(self, "matched_df")
            and self.matched_df is not None
            and not self.matched_df.empty
        ) or (
            hasattr(self, "theoretical_df")
            and self.theoretical_df is not None
            and not self.theoretical_df.empty
        )
        if not has_data:
            QMessageBox.warning(self, "Warning", "No data to export.")
            return

        default_filename = self.generate_default_filename() or "fragment_export"
        filename = get_save_filename(
            self,
            "Export PDF + All Data (will create 2 files)",
            default_filename,
            "All files (*)",
        )
        if filename:
            try:
                base_name = os.path.splitext(filename)[0]
                self._export_pdf_to_file(f"{base_name}_spectrum.pdf")
                self._export_all_data_to_file(f"{base_name}_data.xlsx")
                QMessageBox.information(
                    self,
                    "Success",
                    f"Files exported successfully:\n• {base_name}_spectrum.pdf\n• {base_name}_data.xlsx",
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to export files:\n{str(e)}"
                )

    def generate_default_filename(self):
        """Generate a default filename based on peptide, spectrum file, and scan index"""
        if (
            not hasattr(self, "peptide")
            or not self.peptide
            or not hasattr(self, "row_data")
            or not self.row_data
        ):
            return "fragment_data"

        # Get peptide sequence (clean it for filename)
        peptide = self.peptide.replace(" ", "_")

        # Get spectrum file name (without extension)
        spectrum_file = ""
        for key in [
            "Spectrum file",
            "spectrum_file",
            "Raw file",
            "raw_file",
            "File",
            "file",
        ]:
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
