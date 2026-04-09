# mass_spec_viewer_widget.py
"""Facade module — assembles MassSpecViewer from mixins."""
import logging

import pandas as pd
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QSizePolicy

from utils.utility_classes.htmlformating import HTMLFormatter
from utils.style.style import EditorConstants
from .config.constants import PlotConstants
from .classes.tooltipmanager import PersistentTooltip

from .mixins.ui_setup_mixin import UISetupMixin
from .mixins.peptide_display_mixin import PeptideDisplayMixin
from .mixins.modification_mixin import ModificationMixin
from .mixins.annotation_undo_mixin import AnnotationUndoMixin
from .mixins.mouse_interaction_mixin import MouseInteractionMixin
from .mixins.export_mixin import ExportMixin
from .mixins.spectrum_plotting_mixin import SpectrumPlottingMixin
from .mixins.view_settings_mixin import ViewSettingsMixin

logger = logging.getLogger(__name__)


class MassSpecViewer(
    UISetupMixin,
    PeptideDisplayMixin,
    ModificationMixin,
    AnnotationUndoMixin,
    MouseInteractionMixin,
    ExportMixin,
    SpectrumPlottingMixin,
    ViewSettingsMixin,
    QWidget,
):

    diagnosticIonSelected = pyqtSignal(float)
    modificationsChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.persistent_tooltip = PersistentTooltip(self)
        self.setMinimumSize(400, 200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        # Initialize attributes
        self._initialize_attributes()
        self.unmatched_peak_color = EditorConstants.UNMATCHED_PEAK_COLOR()
        # Setup UI components
        self._setup_main_layout()
        self._setup_event_handlers()

    def _initialize_attributes(self):
        """Initialize all instance attributes"""
        # Mode flags
        self.interactive_mode = True
        self.current_peak_line = None
        self.peptide = ""

        # Cross-plot highlighting
        self.current_error_point = None
        self.linked_highlighting = True
        self.error_scatter_items = []

        # Data storage
        self.matched_items = []
        self.peak_lines = []
        self.df = pd.DataFrame()
        self.text_annotation_threshold = 0
        self.annotation_display_settings = {}  # {ion_key: {"visible": bool, "color": str|None}}
        self._saved_annotation_positions = {}  # {(mz_round, ion_type, ion_number, charge): (x, y)}
        self.matched_df = None
        self.theoretical_df = None
        self.annotation_removal_history = []
        self.max_undo_history = 10

        # Peak measurement
        self.peak_measure_mode = False
        self.first_peak_selected = None
        self.peak_measurements = []
        self.first_peak_line = None
        self.current_peak_data = None

        # Loading - only need dimmers now
        self.spectrum_dimmer = None
        self.error_dimmer = None
        self.is_loading = False

        #  Initialize annotation font size (separate from peptide font sizing)
        self.annotation_font_size = 18  # Default for spectrum annotations only

        #  Flag to disable peak highlighting during annotation dragging
        self.annotation_dragging = False

        # Flag: when True the next set_data() call will NOT restore the
        # previous x-range (used when a brand-new scan is selected).
        self._new_scan_pending = False

    def set_data(self, matched_data, peptide, mod_positions, row_data, theoretical_data=None):
        """Update the viewer with new data and re-plot"""

        # Prevent recursive updates during data setting
        self._updating_data = True

        self.show_loading_indicator()

        self.clear_peak_measurements()

        # Capture current x-range before clearing, so re-annotations preserve user zoom.
        # Skip when a brand-new scan was selected — always show full range for new scans.
        saved_x_range = None
        is_new_scan = self._new_scan_pending
        self._new_scan_pending = False
        spectrum_vb = self.spectrumplot.getViewBox()
        if not is_new_scan and hasattr(self, 'df') and not self.df.empty:
            try:
                saved_x_range = spectrum_vb.viewRange()[0]
            except Exception:
                pass

        self.annotation_removal_history.clear()
        self._saved_annotation_positions.clear()

        # Store data
        self.df = matched_data.copy()
        self.matched_df = matched_data.copy()
        self.theoretical_df = theoretical_data
        self.peptide = peptide
        self.row_data = row_data

        # Process data
        self.df["Ion Number"] = self.df["Ion Number"].apply(HTMLFormatter.clean_number)
        self.df["Charge"] = self.df["Charge"].apply(HTMLFormatter.clean_number)
        self.df["Isotope"] = self.df["Isotope"].apply(HTMLFormatter.clean_number)
        self.df["text_annotation"] = self.df.apply(HTMLFormatter.format_annotation_unicode, axis=1)
        self.df["html_annotation"] = self.df.apply(HTMLFormatter.format_annotation, axis=1)
        self.df["Relative Intensity"] = (self.df["intensity"] / self.df["intensity"].max()) * 100

        # Set up ranges for spectrum/error plots
        data_min_mz = self.df['m/z'].min()
        data_max_mz = self.df['m/z'].max()
        init_x_min = max(0, data_min_mz - 50)
        init_x_max = data_max_mz + 100
        self.initial_x_range = (init_x_min, init_x_max)

        # Get error viewbox (spectrum_vb already captured above)
        error_vb = self.errorbarplot.getViewBox()

        # Configure viewboxes with initial ranges
        for vb in [spectrum_vb, error_vb]:
            vb.initial_x_range = self.initial_x_range
            vb.setLimits(xMin=data_min_mz - 100, xMax=data_max_mz + 200)
            vb.setXRange(init_x_min, init_x_max, padding=0)

        # Set initial Y ranges
        spectrum_vb.initial_y_range = (0, PlotConstants.SPECTRUM_Y_LIMIT)
        spectrum_vb.setYRange(0, PlotConstants.SPECTRUM_Y_LIMIT, padding=0)

        if hasattr(error_vb, 'fixed_y_min') and hasattr(error_vb, 'fixed_y_max'):
            error_vb.initial_y_range = (error_vb.fixed_y_min, error_vb.fixed_y_max)

        spectrum_vb.reset_to_initial_ranges()
        error_vb.reset_to_initial_ranges()

        # Restore user's x-range if the spectrum data limits still accommodate it
        if saved_x_range is not None:
            sr_min, sr_max = saved_x_range
            limit_min = data_min_mz - 100
            limit_max = data_max_mz + 200
            if sr_min >= limit_min and sr_max <= limit_max:
                for vb in [spectrum_vb, error_vb]:
                    vb.setXRange(sr_min, sr_max, padding=0)

        self._force_range_sync()

        # Update peptide sequence
        self.set_peptide_sequence(peptide)

        # Set modifications if provided and emit signal
        if mod_positions:
            self.set_modifications(mod_positions)

        # Plot data with slight delay
        QTimer.singleShot(20, self._delayed_plot_data)

    def _delayed_plot_data(self):
        """Delayed plotting to ensure peptide widget is properly initialized"""
        try:
            # Plot peptide sequence with ions
            self.plot_peptide_sequence_with_ions(self.peptide, getattr(self, 'current_interactive_mods', []))

            # Plot spectrum and error data
            self.plot_spectrum()
            self.plot_error_ppm()

            if hasattr(self, 'current_interactive_mods') and self.current_interactive_mods:
                # Force complete rebuild of modifications display
                QTimer.singleShot(50, self._restore_modifications_display)

            self.hide_loading_indicator()


            self.update_undo_button_state()

            # Reset the updating flag
            self._updating_data = False

        except Exception as e:
            logger.debug(f"Error in delayed plot data: {e}")
            self.hide_loading_indicator()
            self._updating_data = False
