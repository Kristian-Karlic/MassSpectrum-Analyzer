import re
import logging

import pandas as pd
from PyQt6.QtGui import QFont

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
        if hasattr(self, 'df') and not self.df.empty:
            self.plot_spectrum()

    def _update_rotation_menu_selection(self, angle):
        """Update rotation menu checkbox selection"""
        if hasattr(self, 'menu_bar'):
            for action in self.menu_bar.actions():
                if action.text() == "View":
                    view_menu = action.menu()
                    for view_action in view_menu.actions():
                        if hasattr(view_action, 'menu') and view_action.menu() and view_action.text() == "Text Rotation":
                            rotation_menu = view_action.menu()
                            for rotation_action in rotation_menu.actions():
                                if hasattr(rotation_action, 'data') and rotation_action.data() == angle:
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
        if hasattr(self, 'df') and not self.df.empty:
            self.plot_spectrum()

    def _update_annotation_font_menu_selection(self, size):
        """Update annotation font menu checkbox selection"""
        if hasattr(self, 'menu_bar'):
            for action in self.menu_bar.actions():
                if action.text() == "View":
                    view_menu = action.menu()
                    for view_action in view_menu.actions():
                        if view_action.text() == "Annotation Font Size":  # UPDATED menu name
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
        from utils.spectrum_graph.annotation_settings_dialog import AnnotationSettingsDialog
        dlg = AnnotationSettingsDialog(self, parent=self)
        dlg.exec()

    def _get_annotation_settings_key(self, row):
        """Map a DataFrame row to its annotation settings key."""
        ion_type = str(row.get('Ion Type', '')).strip()
        base_type = str(row.get('Base Type', '')).strip()
        series = str(row.get('Ion Series Type', '')).strip()
        nl = str(row.get('Neutral Loss', 'None')).strip()

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
        nl_match = re.match(r'^([abcxyzwvdMH]+)-\d*([A-Z].*)$', ion_type)
        if nl_match:
            base_part = nl_match.group(1)
            loss_part = nl_match.group(2)
            # Normalize satellite variants: da->d, db->d, wa->w, wb->w
            satellite_map = {'da': 'd', 'db': 'd', 'wa': 'w', 'wb': 'w'}
            base_part = satellite_map.get(base_part, base_part)
            return f"{base_part}-{loss_part}"

        # Internal ions
        if base_type in ('b', 'a') and ion_type.startswith('int-'):
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
            if (abs(current_x_range[0] - error_current_range[0][0]) > tolerance or
                abs(current_x_range[1] - error_current_range[0][1]) > tolerance):
                error_viewbox.setXRange(current_x_range[0], current_x_range[1], padding=0)

            # Update ticks for both plots
            self._update_plot_ticks(current_x_range, [self.spectrumplot, self.errorbarplot])

            # Force a visual update
            spectrum_viewbox.update()
            error_viewbox.update()

        except Exception as e:
            # Silently handle any synchronization errors to avoid spam
            pass

    def _update_plot_ticks(self, x_range, target_plots, widget_width=None):
        """Update X-axis ticks with dynamic spacing calculation"""
        if widget_width is None:
            widget_width = self.width() if self.width() > 0 else 800

        x_min, x_max = x_range
        x_width = x_max - x_min

        tick_spacing = PlotConstants.auto_tick_spacing(
            x_width,
            target_ticks=PlotConstants.TARGET_X_TICKS
        )

        tick_positions = PlotConstants.generate_tick_positions(x_min, x_max, tick_spacing)

        if tick_positions:
            x_ticks = PlotConstants.format_ticks(tick_positions, tick_spacing)
            for plot in target_plots:
                plot.getAxis('bottom').setTicks(x_ticks)

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

    def show_dataframe_viewer(self):
        """Show dialog to view and save the fragment tables"""
        # If already open, bring to front
        if hasattr(self, '_dataframe_viewer_dialog') and self._dataframe_viewer_dialog is not None:
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
        if hasattr(self, 'row_data') and self.row_data:
            # Convert the single row_data dict to a DataFrame
            selected_row_df = pd.DataFrame([self.row_data])

        dialog = DataframeViewerDialog(
            matched_df=self.matched_df,
            theoretical_df=self.theoretical_df,
            details_df=selected_row_df,  # Pass only the selected row
            parent=self,
            default_filename=default_filename
        )
        self._dataframe_viewer_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, '_dataframe_viewer_dialog', None))
        dialog.show()
