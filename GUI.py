import sys
import logging

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QGuiApplication, QCloseEvent

from utils.utility_classes.toaster import QToaster
from utils.utilities import WindowSizeManager
from utils.gui_tabs.fragmentation_tab import FragmentationTabManager
from utils.gui_tabs.annotation_tab import AnnotationTabManager
from utils.gui_tabs.experiment_manager import ExperimentDataManager
from utils.utility_classes.event_handlers import EventHandlers
from utils.utility_classes.dialog_manager import DataListEditorManager
from utils.gui_tabs.rescoring_tab import RescoringTabManager
from utils.gui_tabs.protein_coverage_tab import ProteinCoverageTabManager
from utils.gui_tabs.manage_files_tab import ManageFilesTabManager
from utils.gui_tabs.results_tab import ResultsTabManager
from utils.mixins._gui_setup_mixin import _GUISetupMixin
from utils.mixins._gui_ion_panel_mixin import _GUIIonPanelMixin
from utils.mixins._gui_data_mixin import _GUIDataMixin
from utils.mixins._gui_theme_mixin import _GUIThemeMixin

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("mass_spec_tool.log")],
)
logger = logging.getLogger(__name__)


########################################################################
# Main GUI Application
########################################################################
class PeptideFragmentationApp(
    _GUISetupMixin,
    _GUIIonPanelMixin,
    _GUIDataMixin,
    _GUIThemeMixin,
    QWidget,
):
    # Application constants
    SETTINGS_ORGANIZATION = "YourCompany"
    SETTINGS_APP_NAME = "MassSpecAnalyzer"

    # Window dimensions
    MIN_WINDOW_WIDTH = 1500
    MIN_WINDOW_HEIGHT = 700
    DEFAULT_WINDOW_WIDTH = 1680
    DEFAULT_WINDOW_HEIGHT = 900

    # Mock data
    DEFAULT_MOCK_PEPTIDE = "SAMPLE"

    def __init__(self):
        super().__init__()
        # Initialize managers
        self.annotation_tab_manager = AnnotationTabManager(self)
        self.fragmentation_tab_manager = FragmentationTabManager(self)
        self.experiment_data_manager = ExperimentDataManager(self)
        self.event_handlers = EventHandlers(self)
        self.rescoring_tab_manager = RescoringTabManager(self)
        self.protein_coverage_tab_manager = ProteinCoverageTabManager(self)
        self.manage_files_tab_manager = ManageFilesTabManager(self)
        self.results_tab_manager = ResultsTabManager(self)
        self.dialog_manager = DataListEditorManager(self)

        # 1) Window and style
        self._init_window_settings()
        # 2) Data structures (df, lists, etc.)
        self._init_data_structures()
        # 3) Main Layout
        self._init_main_layout()
        # 4) Menu Bar
        self._init_menu_bar()
        # 5) Left Scroll Area and its contents
        self._init_left_scroll_area()
        self._populate_glycan_combo()
        # 6) Collapsible sections (m/z table, modifications, etc.)
        self._init_collapsible_sections()
        # New direct scan selection
        self._init_scan_selection_controls()
        # 7) Summary widget and signals
        self.current_interactive_mods = []
        self.current_parsed_mods = []
        self._has_manual_changes = False

        # Initialize persistent fragmentation manager
        self.persistent_fragmentation_manager = None
        self._setup_persistent_fragmentation()
        self.event_handlers.connect_all_signals()

    # -----------------------------------------------------------------
    # Manager delegation via __getattr__
    # -----------------------------------------------------------------
    # Maps attribute names to (manager_attr, target_name) for delegation.
    # When target_name is None, the same attribute name is looked up.
    _DELEGATION_MAP: dict[str, tuple[str, str | None]] = {
        # event_handlers
        "on_settings_changed": ("event_handlers", None),
        "_calculate_optimal_delay": ("event_handlers", None),
        "perform_adaptive_update": ("event_handlers", None),
        "_create_diagnostic_ion_rows": ("event_handlers", None),
        "_update_spectrum_tracker": ("event_handlers", None),
        "_get_selected_ion_types_for_tracking": ("event_handlers", None),
        "run_fragmentation_adaptive": ("event_handlers", "_run_fragmentation_adaptive"),
        "update_modification_table": ("event_handlers", "on_peptide_changed"),
        "get_modifications_from_table": (
            "event_handlers",
            "_get_modifications_from_table",
        ),
        "_on_cache_hit": ("event_handlers", "on_cache_hit"),
        "_on_cache_miss": ("event_handlers", "on_cache_miss"),
        "clear_mz_table": ("event_handlers", "on_clear_mz_table"),
        "extract_scan_data": ("event_handlers", "on_extract_scan_clicked"),
        "on_adaptive_fragmentation_finished": ("event_handlers", None),
        "on_fragmentation_error": ("event_handlers", None),
        "validate_fragmentation_inputs": ("event_handlers", None),
        # experiment_data_manager
        "load_raw_data": ("experiment_data_manager", None),
        "load_search_data": ("experiment_data_manager", None),
        "add_msfragger_search_folder": ("experiment_data_manager", None),
        "save_experiment": ("experiment_data_manager", None),
        "load_experiment": ("experiment_data_manager", None),
        # protein_coverage_tab_manager
        "load_fasta_file": ("protein_coverage_tab_manager", None),
        # fragmentation_tab_manager
        "add_comparison_group": ("fragmentation_tab_manager", None),
        "remove_comparison_group": ("fragmentation_tab_manager", None),
        "clear_comparison_groups": ("fragmentation_tab_manager", None),
        "update_comparison_plot": ("fragmentation_tab_manager", None),
        "show_save_options": ("fragmentation_tab_manager", None),
        "select_no_comparison_ion_types": ("fragmentation_tab_manager", None),
        "on_plot_type_changed": ("fragmentation_tab_manager", None),
        "_update_group_name": ("fragmentation_tab_manager", None),
    }

    # Maps attribute names to (manager_attr, target_attr) for property-like access.
    _PROPERTY_DELEGATION_MAP: dict[str, tuple[str, str | None]] = {
        "mass_spec_viewer": ("annotation_tab_manager", None),
        "psm_summary_widget": ("annotation_tab_manager", None),
        "spectrum_tracker": ("annotation_tab_manager", None),
        "peptide_info_widget": ("annotation_tab_manager", None),
        "raw_files": ("experiment_data_manager", None),
        "search_files": ("experiment_data_manager", None),
        "df_file_paths": ("experiment_data_manager", None),
        "merged_df": ("experiment_data_manager", None),
        "extracted_spectral_data": ("experiment_data_manager", None),
    }

    def __getattr__(self, name: str) -> object:
        # Method delegation
        if name in self._DELEGATION_MAP:
            manager_attr, target_name = self._DELEGATION_MAP[name]
            manager = object.__getattribute__(self, manager_attr)
            return getattr(manager, target_name or name)

        # Property-like delegation
        if name in self._PROPERTY_DELEGATION_MAP:
            manager_attr, target_name = self._PROPERTY_DELEGATION_MAP[name]
            manager = object.__getattribute__(self, manager_attr)
            return getattr(manager, target_name or name)

        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def set_window_size(self, width: int, height: int):
        """Set window to specific size and center on screen"""
        self.resize(width, height)
        self.center_on_screen()

    def center_on_screen(self):
        """Center the window on the screen"""
        screen = QGuiApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle application close event with proper cleanup"""
        logger.debug("Application closing - cleaning up threads...")

        # Clean up protein coverage tab
        if (
            hasattr(self, "protein_coverage_tab_manager")
            and self.protein_coverage_tab_manager
        ):
            logger.debug("Cleaning up protein coverage tab...")
            self.protein_coverage_tab_manager.cleanup()

        # Stop the persistent fragmentation manager
        if (
            hasattr(self, "persistent_fragmentation_manager")
            and self.persistent_fragmentation_manager
        ):
            logger.debug("Shutting down persistent fragmentation manager...")
            self.persistent_fragmentation_manager.shutdown()

        # Stop any pending timers
        if hasattr(self, "_update_timer"):
            self._update_timer.stop()

        # Save settings and geometry before closing
        self._save_scoring_settings()
        WindowSizeManager.save_geometry(self)

        logger.debug("Cleanup complete")
        event.accept()

    def show_toast_message(self, message: str, duration: int = 2000) -> None:
        """Show a toast message using QToaster"""
        toaster = QToaster(self)
        toaster.show_message(message, duration)


def main():
    # When running as a bundled .exe, seed the writable user-data directory so
    # editable databases (glycan compositions, custom monosaccharides,
    # modifications, presets, …) persist across runs. Without this, edits are
    # written into PyInstaller's read-only _MEIPASS temp folder and lost on exit.
    try:
        from utils.resource_path import (
            is_bundled,
            ensure_user_data_structure,
            initialize_user_data_files,
        )

        if is_bundled():
            ensure_user_data_structure()
            initialize_user_data_files()
    except Exception:
        logger.exception("Failed to initialize user data directory")

    app = QApplication(sys.argv)
    window = PeptideFragmentationApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    main()
