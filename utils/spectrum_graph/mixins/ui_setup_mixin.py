import logging

import pyqtgraph as pg
from pyqtgraph import GraphicsLayoutWidget

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction, QActionGroup
from PyQt6.QtWidgets import (
    QWidget, QMenu, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QDialog, QPushButton, QDoubleSpinBox,
    QFormLayout, QMenuBar, QMessageBox,
)

from ..config.constants import PlotConstants
from ..classes.viewboxes import SpectrumPlotViewBox, ErrorplotViewBox
from ..classes.modification_legend import ModificationLegend
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class UISetupMixin:
    """UI layout, menu bar, and plot configuration for MassSpecViewer."""

    def _setup_plot_background_and_styling(self, plots):
        """Apply consistent background and styling to multiple plots"""
        for plot in plots:
            plot.getViewBox().setBackgroundColor('w')
        self.glw.setBackground('w')

    def _setup_main_layout(self):
        """Setup the main layout structure — glw fills all available space directly"""
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Menu bar at the top
        self._setup_menu_bar()
        main_layout.addWidget(self.menu_bar)

        # ADD: Legend widget (above the graphics layout)
        self.legend = ModificationLegend()
        self.legend.setFixedHeight(25)  # Always 25px regardless of content
        self.legend.setMinimumHeight(25)
        self.legend.setMaximumHeight(25)
        main_layout.addWidget(self.legend)

        # Graphics layout widget — expands to fill all available space
        self.glw = GraphicsLayoutWidget()
        self.glw.setBackground('w')
        self.glw.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        main_layout.addWidget(self.glw)

        # Add peptide plot at row 0
        self.peptide_plot = self.glw.addPlot(row=0, col=0)
        self._setup_peptide_plot()

        # Add spectrum and error plots below
        self.spectrumplot = self.glw.addPlot(row=1, col=0, viewBox=SpectrumPlotViewBox())
        self.errorbarplot = self.glw.addPlot(row=2, col=0, viewBox=ErrorplotViewBox())

        # Configure plots - MOVED FROM _setup_plots()
        self._configure_plot_axis(
            self.spectrumplot, 'Relative Intensity (%)', 'm/z',
            PlotConstants.SPECTRUM_Y_RANGE, (True, True)
        )
        self._configure_plot_axis(
            self.errorbarplot, 'Error (ppm)', 'm/z',
            PlotConstants.ERROR_Y_RANGE, (True, False)
        )

        # Set viewbox references - MOVED FROM _setup_plots()
        self.view = self.spectrumplot.getViewBox()
        for viewbox in [self.view, self.errorbarplot.getViewBox()]:
            viewbox.set_plot_item(self.spectrumplot if viewbox == self.view else self.errorbarplot)
            viewbox.viewer_instance = self

        # Setup linking and styling - MOVED FROM _setup_plots()
        self._setup_plot_linking()
        self._setup_plot_background_and_styling([self.spectrumplot, self.errorbarplot])
        self._setup_plot_row_stretching()

    def _setup_peptide_plot(self):
        """Setup the peptide sequence plot with full interactive functionality"""
        # Initialize peptide-related attributes
        self.peptide_sequence = ""
        self.modifications = {}  # position -> [(mass, name), ...]
        self.nl_legend_entries = []  # [(symbol, label, mass_da, mod_name), ...]
        self.available_modifications = []
        self.fragment_lines = []  # List of tuples: (vertical_line, horizontal_line, fragment_data)
        self.fragment_line_data = []  # Store fragment data separately for lookup
        self.highlight_items = []

        # RESPONSIVE TEXT SIZING PARAMETERS
        self.fixed_width = 600  # Available width for peptide display
        self.max_aa_for_full_size = 28 # Maximum amino acids at full size
        self.base_font_size = 25  # Base font size for <= 20 AA
        self.min_font_size = 12  # Minimum font size for very long peptides
        self.base_letter_spacing = 20.0  # Base spacing between letters
        self.min_letter_spacing = 10.0  # Minimum spacing for long peptides

        # Visual parameters - will be calculated dynamically
        self.letter_spacing = self.base_letter_spacing
        self.current_font_size = self.base_font_size
        self.start_x = 25  # Left margin
        self.amino_acid_items = []
        self.modification_items = []
        self.position_calculator = None


        # Configure peptide plot
        self.peptide_plot.hideAxis('left')
        self.peptide_plot.hideAxis('bottom')
        self.peptide_plot.setMouseEnabled(x=False, y=False)
        self.peptide_plot.hideButtons()
        self.peptide_plot.setXRange(0, self.fixed_width, padding=0)
        self.peptide_plot.setYRange(-200, 200, padding=0)

        # Disable context menu for peptide plot
        try:
            vb = self.peptide_plot.getViewBox()
            vb.setMenuEnabled(False)
        except Exception:
            pass

    def _setup_menu_bar(self):
        """Setup menu bar with all controls moved from toolbar"""
        self.menu_bar = QMenuBar(self)
        self.menu_bar.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed
        )
        self.menu_bar.setMaximumWidth(1000)  # Match widget width

        # File Menu
        file_menu = self.menu_bar.addMenu("File")

        # Export submenu
        export_menu = file_menu.addMenu("Export")

        # Export SVG action
        export_svg_action = QAction("Export as SVG...", self)
        export_svg_action.triggered.connect(self.export_svg)
        export_svg_action.setShortcut("Ctrl+E")
        export_menu.addAction(export_svg_action)

        export_menu.addSeparator()

        # Export data actions
        export_matched_action = QAction("Export Matched Fragments...", self)
        export_matched_action.triggered.connect(self.export_matched_fragments)
        export_menu.addAction(export_matched_action)

        export_theoretical_action = QAction("Export Theoretical Fragments...", self)
        export_theoretical_action.triggered.connect(self.export_theoretical_fragments)
        export_menu.addAction(export_theoretical_action)

        export_all_data_action = QAction("Export All Data...", self)
        export_all_data_action.triggered.connect(self.export_all_data)
        export_menu.addAction(export_all_data_action)

        export_menu.addSeparator()

        # Combined export action
        export_combined_action = QAction("Export SVG + All Data...", self)
        export_combined_action.triggered.connect(self.export_combined_svg_and_data)
        export_combined_action.setShortcut("Ctrl+Shift+E")
        export_menu.addAction(export_combined_action)

        file_menu.addSeparator()

        # View Menu
        view_menu = self.menu_bar.addMenu("View")

        # View tables action (separate from export)
        view_tables_action = QAction("View Tables...", self)
        view_tables_action.triggered.connect(self.show_dataframe_viewer)
        view_menu.addAction(view_tables_action)

        # Hide unassigned peaks action
        self.hide_unassigned_action = QAction("Hide Unassigned Peaks", self)
        self.hide_unassigned_action.setCheckable(True)
        self.hide_unassigned_action.toggled.connect(self.toggle_non_colored_peaks)
        view_menu.addAction(self.hide_unassigned_action)

        annotation_settings_action = QAction("Annotation Settings...", self)
        annotation_settings_action.triggered.connect(self._open_annotation_settings)
        view_menu.addAction(annotation_settings_action)

        view_menu.addSeparator()

        # RENAMED: Annotation Font Size submenu (only for spectrum annotations)
        font_menu = view_menu.addMenu("Annotation Font Size")
        font_group = QActionGroup(self)

        font_sizes = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32]

        for size in font_sizes:
            action = QAction(f"{size}pt", self)
            action.setCheckable(True)
            action.setData(size)
            if size == self.annotation_font_size:
                action.setChecked(True)
            action.triggered.connect(lambda checked, s=size: self.set_annotation_font_size(s))
            font_group.addAction(action)
            font_menu.addAction(action)

        # Text Rotation submenu
        rotation_menu = view_menu.addMenu("Text Rotation")
        rotation_group = QActionGroup(self)

        # Initialize rotation attribute
        self.text_rotation_angle = 0  # Default: horizontal

        # Horizontal rotation action
        horizontal_action = QAction("Horizontal (0\u00b0)", self)
        horizontal_action.setCheckable(True)
        horizontal_action.setChecked(True)  # Default
        horizontal_action.setData(0)
        horizontal_action.triggered.connect(lambda: self.set_text_rotation(0))
        rotation_group.addAction(horizontal_action)
        rotation_menu.addAction(horizontal_action)

        # Vertical rotation action
        vertical_action = QAction("Vertical (90\u00b0)", self)
        vertical_action.setCheckable(True)
        vertical_action.setData(90)
        vertical_action.triggered.connect(lambda: self.set_text_rotation(90))
        rotation_group.addAction(vertical_action)
        rotation_menu.addAction(vertical_action)

        # Tools Menu
        tools_menu = self.menu_bar.addMenu("Tools")

        # Peak measurement action
        self.measure_action = QAction("Peak Measurement Mode", self)
        self.measure_action.setCheckable(True)
        self.measure_action.toggled.connect(self.toggle_peak_measure_mode)
        self.measure_action.setShortcut("M")  # Keyboard shortcut
        tools_menu.addAction(self.measure_action)

        # Clear measurements action
        clear_measurements_action = QAction("Clear All Measurements", self)
        clear_measurements_action.triggered.connect(self.clear_peak_measurements)
        clear_measurements_action.setShortcut("Ctrl+Shift+C")
        tools_menu.addAction(clear_measurements_action)

        tools_menu.addSeparator()

        # Undo annotation action
        self.undo_annotation_action = QAction("Undo Annotation Removal", self)
        self.undo_annotation_action.triggered.connect(self.undo_annotation_removal)
        self.undo_annotation_action.setEnabled(False)
        self.undo_annotation_action.setShortcut("Ctrl+Z")
        tools_menu.addAction(self.undo_annotation_action)

    def _setup_plot_row_stretching(self):
        """Configure row stretch factors with peptide widget included"""
        stretch_factors = {
            0: 1,  # Peptide plot - fixed size
            1: 7,  # Spectrum plot - main content
            2: 2   # Error plot - smaller
        }
        for row, factor in stretch_factors.items():
            self.glw.ci.layout.setRowStretchFactor(row, factor)

    def _setup_plot_linking(self):
        """Setup X-axis linking and viewbox synchronization with forced updates"""
        self.errorbarplot.setXLink(self.spectrumplot)

        spectrum_viewbox = self.spectrumplot.getViewBox()
        error_viewbox = self.errorbarplot.getViewBox()
        spectrum_viewbox.set_linked_viewbox(error_viewbox)
        error_viewbox.set_linked_viewbox(spectrum_viewbox)
        spectrum_viewbox.viewer_instance = self
        error_viewbox.viewer_instance = self
        spectrum_viewbox.sigRangeChanged.connect(self._force_range_sync)
        error_viewbox.sigRangeChanged.connect(self._force_range_sync)

    def _configure_plot_axis(self, plot, left_label, bottom_label, y_range, mouse_enabled=(True, True)):
        """Configure plot with responsive font sizing and theme-aware colors"""
        plot.hideButtons()
        plot.showGrid(x=PlotConstants.SHOW_GRID, y=PlotConstants.SHOW_GRID)

        # Get theme-aware axis color
        axis_color = EditorConstants.TEXT_COLOR()

        # Use consistent font sizes with theme-aware color
        plot.setLabel('left', f'<span style="font-size:{PlotConstants.LABEL_FONT_SIZE}pt;font-weight:bold;color:{axis_color}">{left_label}</span>')
        plot.setLabel('bottom', f'<span style="font-size:{PlotConstants.LABEL_FONT_SIZE}pt;font-weight:bold;color:{axis_color}">{bottom_label}</span>')

        # Font styling with responsive sizes
        tick_font = QFont(PlotConstants.DEFAULT_FONT_FAMILY, PlotConstants.TICK_FONT_SIZE, QFont.Weight.Bold)

        # Configure left (Y) axis with theme-aware colors
        left_axis = plot.getAxis('left')
        left_axis.setStyle(
            tickFont=tick_font,
            showValues=True,
            tickLength=PlotConstants.TICK_LENGTH
        )
        left_axis.setTextPen(axis_color)
        left_axis.setPen(pg.mkPen(axis_color, width=PlotConstants.AXIS_PEN_WIDTH))
        left_axis.setWidth(PlotConstants.Y_AXIS_WIDTH)  # Fixed width for alignment

        # Configure bottom (X) axis with theme-aware colors
        bottom_axis = plot.getAxis('bottom')
        bottom_axis.setStyle(
            tickFont=tick_font,
            showValues=True,
            tickLength=PlotConstants.TICK_LENGTH
        )
        bottom_axis.setTextPen(axis_color)
        bottom_axis.setPen(pg.mkPen(axis_color, width=PlotConstants.AXIS_PEN_WIDTH))

        # Set major tick spacing based on plot type
        if 'Intensity' in left_label:  # Spectrum plot
            # Set major ticks for spectrum Y-axis (every 20%)
            left_axis.setTicks([[(i, str(i)) for i in range(0, 101, PlotConstants.MAJOR_TICK_SPACING_SPECTRUM)]])
        elif 'Error' in left_label:  # Error plot
            # Set major ticks for error Y-axis (every 5 ppm)
            error_ticks = list(range(-10, 11, PlotConstants.MAJOR_TICK_SPACING_ERROR))
            left_axis.setTicks([[(i, str(i)) for i in error_ticks]])

        # Disable SI prefix scaling on Y-axis
        left_axis.enableAutoSIPrefix(False)
        bottom_axis.enableAutoSIPrefix(False)

        # Set ranges and mouse interaction
        plot.setYRange(*y_range)
        plot.setMouseEnabled(x=mouse_enabled[0], y=mouse_enabled[1])

    def show_custom_context_menu(self, global_pos, viewbox, scene_pos):
        """Show unified custom context menu for spectrum and error plots"""
        menu = QMenu(self)

        # Determine which plot this is from
        is_spectrum_plot = viewbox == self.spectrumplot.getViewBox()
        is_error_plot = viewbox == self.errorbarplot.getViewBox()

        plot_name = "Spectrum" if is_spectrum_plot else "Error"

        # Reset Zoom action
        reset_action = QAction(f"Reset {plot_name} Zoom", self)
        reset_action.triggered.connect(lambda: self.reset_plot_zoom(viewbox, is_spectrum_plot))
        menu.addAction(reset_action)

        menu.addSeparator()

        # X-axis adjust action
        x_axis_action = QAction("Adjust X-Axis Range...", self)
        x_axis_action.triggered.connect(lambda: self.show_axis_adjust_dialog(viewbox, 'x', plot_name))
        menu.addAction(x_axis_action)

        # Y-axis adjust action
        y_axis_action = QAction("Adjust Y-Axis Range...", self)
        y_axis_action.triggered.connect(lambda: self.show_axis_adjust_dialog(viewbox, 'y', plot_name))
        menu.addAction(y_axis_action)

        # Show menu
        menu.exec(global_pos)

    def reset_plot_zoom(self, viewbox, is_spectrum_plot):
        """Reset plot to initial zoom ranges"""
        try:
            if is_spectrum_plot:
                # Reset spectrum plot
                if hasattr(viewbox, 'initial_x_range') and viewbox.initial_x_range:
                    viewbox.setXRange(*viewbox.initial_x_range, padding=0)
                if hasattr(viewbox, 'initial_y_range') and viewbox.initial_y_range:
                    viewbox.setYRange(*viewbox.initial_y_range, padding=0)
                else:
                    # Default spectrum Y range
                    viewbox.setYRange(0, PlotConstants.SPECTRUM_Y_LIMIT, padding=0)

                # Set spectrum Y ticks
                if hasattr(viewbox, 'plot_item') and viewbox.plot_item:
                    left_axis = viewbox.plot_item.getAxis('left')
                    left_axis.setTicks([[(i, str(i)) for i in range(0, 101, PlotConstants.MAJOR_TICK_SPACING_SPECTRUM)]])

            else:
                # Reset error plot
                if hasattr(viewbox, 'initial_x_range') and viewbox.initial_x_range:
                    viewbox.setXRange(*viewbox.initial_x_range, padding=0)
                if hasattr(viewbox, 'initial_y_range') and viewbox.initial_y_range:
                    viewbox.setYRange(*viewbox.initial_y_range, padding=0)
                else:
                    # Default error Y range
                    if hasattr(viewbox, 'fixed_y_min') and hasattr(viewbox, 'fixed_y_max'):
                        viewbox.setYRange(viewbox.fixed_y_min, viewbox.fixed_y_max, padding=0)
                    else:
                        viewbox.setYRange(-10, 10, padding=0)

                if hasattr(viewbox, 'plot_item') and viewbox.plot_item:
                    left_axis = viewbox.plot_item.getAxis('left')
                    if hasattr(viewbox, 'fixed_y_min') and hasattr(viewbox, 'fixed_y_max'):
                        y_min = int(viewbox.fixed_y_min)
                        y_max = int(viewbox.fixed_y_max)
                    else:
                        y_min = -10
                        y_max = 10

                    # Generate error plot ticks
                    error_ticks = list(range(y_min, y_max + 1, PlotConstants.MAJOR_TICK_SPACING_ERROR))
                    left_axis.setTicks([[(i, str(i)) for i in error_ticks]])

            if hasattr(viewbox, 'update_adaptive_x_ticks'):
                viewbox.update_adaptive_x_ticks()
            elif hasattr(viewbox, 'viewer_instance') and viewbox.viewer_instance:
                # Update X ticks using viewer instance
                if hasattr(viewbox, 'initial_x_range') and viewbox.initial_x_range:
                    plots = [viewbox.plot_item]
                    if hasattr(viewbox, 'linked_viewbox') and viewbox.linked_viewbox and viewbox.linked_viewbox.plot_item:
                        plots.append(viewbox.linked_viewbox.plot_item)
                    viewbox.viewer_instance._update_plot_ticks(viewbox.initial_x_range, plots)

            logger.debug(f"Reset zoom for {'spectrum' if is_spectrum_plot else 'error'} plot")

        except Exception as e:
            logger.error(f"Failed to reset plot zoom: {e}")

    def show_axis_adjust_dialog(self, viewbox, axis, plot_name):
        """Show dialog to adjust axis range"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Adjust {plot_name} {axis.upper()}-Axis Range")
        dialog.setFixedSize(300, 150)

        layout = QVBoxLayout(dialog)

        # Create form layout
        form_layout = QFormLayout()

        # Get current range
        if axis == 'x':
            current_range = viewbox.viewRange()[0]
        else:
            current_range = viewbox.viewRange()[1]

        # Create spin boxes with appropriate precision
        if axis == 'x':
            # X-axis (m/z values) - higher precision
            min_spinbox = QDoubleSpinBox()
            max_spinbox = QDoubleSpinBox()
            min_spinbox.setDecimals(4)
            max_spinbox.setDecimals(4)
            min_spinbox.setRange(-999999.0, 999999.0)
            max_spinbox.setRange(-999999.0, 999999.0)
            min_spinbox.setSingleStep(1.0)
            max_spinbox.setSingleStep(1.0)
        else:
            # Y-axis - different ranges for spectrum vs error plot
            min_spinbox = QDoubleSpinBox()
            max_spinbox = QDoubleSpinBox()

            if plot_name == "Spectrum":
                # Spectrum Y-axis (0-100% intensity)
                min_spinbox.setDecimals(1)
                max_spinbox.setDecimals(1)
                min_spinbox.setRange(0.0, 1000.0)
                max_spinbox.setRange(0.0, 1000.0)
                min_spinbox.setSingleStep(5.0)
                max_spinbox.setSingleStep(5.0)
            else:
                # Error plot Y-axis (ppm values)
                min_spinbox.setDecimals(1)
                max_spinbox.setDecimals(1)
                min_spinbox.setRange(-1000.0, 1000.0)
                max_spinbox.setRange(-1000.0, 1000.0)
                min_spinbox.setSingleStep(1.0)
                max_spinbox.setSingleStep(1.0)

        # Set current values
        min_spinbox.setValue(current_range[0])
        max_spinbox.setValue(current_range[1])

        # Add to form
        form_layout.addRow("Minimum:", min_spinbox)
        form_layout.addRow("Maximum:", max_spinbox)

        layout.addLayout(form_layout)

        # Buttons
        button_layout = QHBoxLayout()

        # Apply button
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(lambda: self.apply_axis_range(
            viewbox, axis, min_spinbox.value(), max_spinbox.value(), dialog
        ))
        button_layout.addWidget(apply_button)

        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        # Show dialog
        dialog.exec()

    def apply_axis_range(self, viewbox, axis, min_val, max_val, dialog):
        """Apply the new axis range"""
        try:
            # Validate range
            if min_val >= max_val:

                QMessageBox.warning(dialog, "Invalid Range",
                                  f"Minimum value ({min_val}) must be less than maximum value ({max_val})")
                return

            # Apply the range
            if axis == 'x':
                viewbox.setXRange(min_val, max_val, padding=0)
            else:
                viewbox.setYRange(min_val, max_val, padding=0)

            # Update ticks after range change
            if hasattr(viewbox, 'viewer_instance') and viewbox.viewer_instance:
                if axis == 'x':
                    # Update X ticks for both plots if linked
                    plots = [viewbox.plot_item]
                    if hasattr(viewbox, 'linked_viewbox') and viewbox.linked_viewbox and viewbox.linked_viewbox.plot_item:
                        plots.append(viewbox.linked_viewbox.plot_item)
                    viewbox.viewer_instance._update_plot_ticks((min_val, max_val), plots)
                else:
                    # Update Y ticks
                    if hasattr(viewbox, 'update_adaptive_y_ticks'):
                        viewbox.update_adaptive_y_ticks()

            logger.debug(f"Applied {axis}-axis range: {min_val} to {max_val}")
            dialog.accept()

        except Exception as e:
            logger.error(f"Failed to apply axis range: {e}")
            QMessageBox.critical(dialog, "Error", f"Failed to apply range:\n{str(e)}")
