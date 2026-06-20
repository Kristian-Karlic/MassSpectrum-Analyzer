import re
import logging

import pandas as pd
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QDoubleSpinBox,
    QLabel,
)

from ..config.constants import PlotConstants
from ..classes.interactivetext import EnhancedInteractiveTextItem
from ..classes.loading_indicator import PlotDimmer
from ..classes.dataframe_viewer_dialog import DataframeViewerDialog

logger = logging.getLogger(__name__)


class ViewSettingsMixin:
    """View settings, tick management, and utility dialogs for MassSpecViewer."""

    def set_text_rotation(self, angle):
        """Set the rotation angle for text annotations and update menu selection"""
        logger.debug(f"Setting text rotation to: {angle}°")

        self.text_rotation_angle = angle

        # Update menu checkboxes
        self._update_rotation_menu_selection(angle)

        # Re-plot spectrum to apply new rotation
        if hasattr(self, "df") and not self.df.empty:
            self.plot_spectrum()

    def _update_rotation_menu_selection(self, angle):
        """Update rotation menu checkbox selection"""
        if hasattr(self, "menu_bar"):
            for action in self.menu_bar.actions():
                if action.text() == "View":
                    view_menu = action.menu()
                    for view_action in view_menu.actions():
                        if (
                            hasattr(view_action, "menu")
                            and view_action.menu()
                            and view_action.text() == "Text Rotation"
                        ):
                            rotation_menu = view_action.menu()
                            for rotation_action in rotation_menu.actions():
                                if (
                                    hasattr(rotation_action, "data")
                                    and rotation_action.data() == angle
                                ):
                                    rotation_action.setChecked(True)
                                    break
                            break
                    break

    def set_annotation_font_size(self, size):
        """Set the font size for spectrum annotations and measurements (NOT peptide text)"""
        logger.debug(f"Setting annotation font size to: {size}")

        # This is ONLY for annotation font size, NOT peptide base font size
        self.annotation_font_size = size  # Store separately from peptide sizing
        self.update_measurement_font_size(size)

        # Update menu checkboxes
        self._update_annotation_font_menu_selection(size)

        # Re-plot spectrum to apply new annotation font size
        if hasattr(self, "df") and not self.df.empty:
            self.plot_spectrum()

    def _update_annotation_font_menu_selection(self, size):
        """Update annotation font menu checkbox selection"""
        if hasattr(self, "menu_bar"):
            for action in self.menu_bar.actions():
                if action.text() == "View":
                    view_menu = action.menu()
                    for view_action in view_menu.actions():
                        if (
                            view_action.text() == "Annotation Font Size"
                        ):  # UPDATED menu name
                            font_menu = view_action.menu()
                            for font_action in font_menu.actions():
                                font_action.setChecked(font_action.data() == size)
                            break
                    break

    def update_measurement_font_size(self, size):
        """Update the font size of all measurement labels and peak annotations."""
        self.annotation_font_size = size  # RENAMED from current_font_size

        # Update peak difference measurements
        for _, text in self.peak_measurements:
            font = QFont(PlotConstants.DEFAULT_FONT_FAMILY, size, QFont.Weight.Bold)
            text.setFont(font)

        # Update peak annotations in matched_items
        for item in self.matched_items:
            if isinstance(item, EnhancedInteractiveTextItem):
                font = QFont(PlotConstants.DEFAULT_FONT_FAMILY, size)
                item.setFont(font)

    def update_text_annotation_threshold(self, new_threshold: int):
        self.text_annotation_threshold = new_threshold
        self.plot_spectrum()

    def _open_annotation_settings(self):
        from utils.spectrum_graph.annotation_settings_dialog import (
            AnnotationSettingsDialog,
        )

        glycan_compositions = getattr(self, "_glycan_compositions_list", [])
        dlg = AnnotationSettingsDialog(
            self, parent=self, glycan_compositions=glycan_compositions
        )
        dlg.exec()

    def _get_annotation_settings_key(self, row):
        """Map a DataFrame row to its annotation settings key."""
        ion_type = str(row.get("Ion Type", "")).strip()
        base_type = str(row.get("Base Type", "")).strip()
        series = str(row.get("Ion Series Type", "")).strip()
        nl = str(row.get("Neutral Loss", "None")).strip()

        if series == "GlycanY-Ion-Series":
            return "GlycanY"
        if series == "Mod-NL-Series":
            if nl.startswith("ModNL"):
                return "ModNL"
            if nl.startswith("LabileLoss"):
                return "LabileLoss"
            if nl.startswith("ModRM"):
                return "ModRM"
            # Mod-NL with standard loss (e.g. y*-H2O) — group under ModNL
            return "ModNL"
        if series == "Custom-Ion-Series":
            return "Custom"
        if nl == "Custom_Ion":
            return "Diagnostic"

        # Standard neutral loss: extract "base-lossType" key
        nl_match = re.match(r"^([abcxyzwvdMH]+)-\d*([A-Z].*)$", ion_type)
        if nl_match:
            base_part = nl_match.group(1)
            loss_part = nl_match.group(2)
            # Normalize satellite variants: da->d, db->d, wa->w, wb->w
            satellite_map = {"da": "d", "db": "d", "wa": "w", "wb": "w"}
            base_part = satellite_map.get(base_part, base_part)
            return f"{base_part}-{loss_part}"

        # Internal ions
        if base_type in ("b", "a") and ion_type.startswith("int-"):
            return "Internal"

        # Base ion
        return base_type

    def _force_range_sync(self):
        """Force immediate range synchronization between plots"""
        try:
            spectrum_viewbox = self.spectrumplot.getViewBox()
            error_viewbox = self.errorbarplot.getViewBox()

            # Get current range from spectrum plot
            spectrum_range = spectrum_viewbox.viewRange()
            current_x_range = spectrum_range[0]

            # Get current range from error plot for comparison
            error_current_range = error_viewbox.viewRange()

            # Force synchronization if ranges don't match
            tolerance = 0.001
            if (
                abs(current_x_range[0] - error_current_range[0][0]) > tolerance
                or abs(current_x_range[1] - error_current_range[0][1]) > tolerance
            ):
                error_viewbox.setXRange(
                    current_x_range[0], current_x_range[1], padding=0
                )

            # Update ticks for both plots
            self._update_plot_ticks(
                current_x_range, [self.spectrumplot, self.errorbarplot]
            )

            # Force a visual update
            spectrum_viewbox.update()
            error_viewbox.update()

        except Exception:
            # Silently handle any synchronization errors to avoid spam
            pass

    def _update_plot_ticks(self, x_range, target_plots, widget_width=None):
        """Update X-axis ticks with dynamic spacing calculation"""
        if widget_width is None:
            widget_width = self.width() if self.width() > 0 else 800

        x_min, x_max = x_range
        x_width = x_max - x_min

        tick_spacing = PlotConstants.auto_tick_spacing(
            x_width, target_ticks=PlotConstants.TARGET_X_TICKS
        )

        tick_positions = PlotConstants.generate_tick_positions(
            x_min, x_max, tick_spacing
        )

        if tick_positions:
            x_ticks = PlotConstants.format_ticks(tick_positions, tick_spacing)
            for plot in target_plots:
                plot.getAxis("bottom").setTicks(x_ticks)

    def update_y_axis_limits(self, ppm_tolerance):
        vb_bottom = self.errorbarplot.getViewBox()
        vb_bottom.update_y_axis_limits(ppm_tolerance)
        self.errorbarplot.update()

    def show_loading_indicator(self):
        """Show dimming on both plots without text indicator"""
        if self.is_loading:
            return

        self.is_loading = True

        # Create dimmers for both plots (no text indicator)
        if not self.spectrum_dimmer:
            self.spectrum_dimmer = PlotDimmer(self.spectrumplot)

        if not self.error_dimmer:
            self.error_dimmer = PlotDimmer(self.errorbarplot)

        # Add dimmers to both plots
        self.spectrumplot.addItem(self.spectrum_dimmer)
        self.errorbarplot.addItem(self.error_dimmer)

    def hide_loading_indicator(self):
        """Hide dimming from both plots"""
        if not self.is_loading:
            return

        self.is_loading = False

        # Remove dimmers from both plots
        if self.spectrum_dimmer:
            self.spectrumplot.removeItem(self.spectrum_dimmer)

        if self.error_dimmer:
            self.errorbarplot.removeItem(self.error_dimmer)

    def set_y_axis_mode(self, mode: str):
        """Switch the spectrum Y-axis between 'relative' and 'sqrt'."""
        # Guard against unknown modes (e.g. 'raw' from old saved state)
        if mode not in ("relative", "sqrt"):
            mode = "relative"

        if getattr(self, "y_axis_mode", "relative") != mode:
            # Clear saved label positions — they are in the old Y coordinate space
            # and would place labels in wrong positions after the scale changes.
            self._saved_annotation_positions.clear()

        self.y_axis_mode = mode

        # Enable intensity filter for both axis modes
        is_filterable = True
        if hasattr(self, "intensity_filter_action"):
            self.intensity_filter_action.setEnabled(is_filterable)
        if hasattr(self, "set_filter_value_action"):
            self.set_filter_value_action.setEnabled(is_filterable)

        # Reset filter value when switching modes so it stays in-range
        current_filter = getattr(self, "intensity_filter_value", None)
        if mode == "relative" and (current_filter is None or current_filter > 100.0):
            self.intensity_filter_value = 50.0
        elif mode == "sqrt" and (current_filter is None or current_filter <= 100.0):
            # Will be refined when the user opens the dialog; pick a large safe default
            self.intensity_filter_value = getattr(self, "_spectrum_y_max", 5000.0)

        self._update_y_axis_mode_menu(mode)

        if hasattr(self, "df") and not self.df.empty:
            self.plot_spectrum()

    def _update_y_axis_mode_menu(self, mode: str):
        """Keep the Y-Axis Mode submenu checkmarks in sync."""
        if not hasattr(self, "menu_bar"):
            return
        for action in self.menu_bar.actions():
            if action.text() == "View":
                view_menu = action.menu()
                for view_action in view_menu.actions():
                    if (
                        hasattr(view_action, "menu")
                        and view_action.menu()
                        and view_action.text() == "Y-Axis Mode"
                    ):
                        for y_action in view_action.menu().actions():
                            if hasattr(y_action, "data") and y_action.data() == mode:
                                y_action.setChecked(True)
                        return

    def set_intensity_filter_enabled(self, enabled: bool):
        """Enable or disable the intensity filter and replot."""
        self.intensity_filter_enabled = enabled
        # Y scale will change — saved positions are in old coordinate space
        self._saved_annotation_positions.clear()
        if hasattr(self, "df") and not self.df.empty:
            self.plot_spectrum()

    def show_intensity_filter_dialog(self):
        """Open a dialog for the user to set the intensity filter threshold."""
        y_mode = getattr(self, "y_axis_mode", "relative")

        if y_mode == "relative":
            title = "Set Relative Intensity Filter"
            info_text = (
                "Only peaks with relative intensity \u2264 this value will be plotted.\n"
                "Applies to Relative Intensity mode (range 0\u2013100%)."
            )
            min_val, max_val, step = 0.0, 100.0, 1.0
            decimals = 1
            row_label = "Max Relative Intensity (%):"
            default = getattr(self, "intensity_filter_value", 50.0)
            default = max(0.0, min(100.0, default))
        else:  # sqrt
            # Use the unfiltered max so the user can raise the threshold back up
            y_max = getattr(self, "_unfiltered_y_max", getattr(self, "_spectrum_y_max", 1000.0))
            title = "Set Sqrt Intensity Filter"
            info_text = (
                "Only peaks with sqrt intensity \u2264 this value will be plotted.\n"
                f"Applies to Sqrt Intensity mode (range 0\u2013{y_max:.1f})."
            )
            min_val, max_val = 0.0, y_max
            step = max(1.0, round(y_max / 50, 1))
            decimals = 1
            row_label = "Max Sqrt Intensity:"
            default = getattr(self, "intensity_filter_value", y_max)
            default = max(0.0, min(y_max, default))

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(360, 140)

        layout = QVBoxLayout(dialog)
        info = QLabel(info_text)
        info.setWordWrap(True)
        layout.addWidget(info)

        form_layout = QFormLayout()
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(decimals)
        spinbox.setRange(min_val, max_val)
        spinbox.setSingleStep(step)
        spinbox.setValue(default)
        form_layout.addRow(row_label, spinbox)
        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(
            lambda: self._apply_intensity_filter_value(spinbox.value(), dialog)
        )
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(apply_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def _apply_intensity_filter_value(self, value: float, dialog: QDialog):
        """Store the filter value and replot if the filter is active."""
        self.intensity_filter_value = value
        dialog.accept()
        if self.intensity_filter_enabled and hasattr(self, "df") and not self.df.empty:
            # Y scale changes with the new threshold — reset saved label positions
            self._saved_annotation_positions.clear()
            self.plot_spectrum()

    def show_dataframe_viewer(self):
        """Show dialog to view and save the fragment tables"""
        # If already open, bring to front
        if (
            hasattr(self, "_dataframe_viewer_dialog")
            and self._dataframe_viewer_dialog is not None
        ):
            self._dataframe_viewer_dialog.raise_()
            self._dataframe_viewer_dialog.activateWindow()
            return

        # Generate default filename based on current data with _data suffix
        default_filename = self.generate_default_filename()
        if default_filename:
            default_filename += "_data"
        else:
            default_filename = "fragment_data"

        # Get ONLY the selected row data (not the entire details table)
        selected_row_df = None
        if hasattr(self, "row_data") and self.row_data:
            # Convert the single row_data dict to a DataFrame
            selected_row_df = pd.DataFrame([self.row_data])

        dialog = DataframeViewerDialog(
            matched_df=self.matched_df,
            theoretical_df=self.theoretical_df,
            details_df=selected_row_df,  # Pass only the selected row
            parent=self,
            default_filename=default_filename,
        )
        self._dataframe_viewer_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, "_dataframe_viewer_dialog", None))
        dialog.show()
