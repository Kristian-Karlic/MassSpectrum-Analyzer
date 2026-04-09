import sys
import traceback
import logging
from typing import Optional, List, Tuple, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QTableWidget, QFrame, QTabWidget,
    QTableWidgetItem, QLineEdit, QLabel, QCheckBox, QComboBox, QHeaderView,
    QMenuBar, QMessageBox, QSizePolicy, QScrollArea,QMenu, QSpinBox
)
from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import QRegularExpressionValidator, QGuiApplication, QAction, QColor, QActionGroup

from config import ION_PRESETS, TableConfig
from utils.style.style import StyleSheet, ThemeManager, EditorConstants
from utils.utility_classes.widgets import WidgetFactory
from utils.utility_classes.toaster import QToaster
from utils.utilities import MockDataGenerator, CacheManager, IonTypeGenerator, SimplePasteTable, WindowSizeManager
from utils import (TableUtils, DataLoader)
from utils.style.GUI_dimensions import LayoutConstants
from utils.tables.tableeditor import TableEditorDialog
from utils.tables.Color_selection import ColorDelegate
from utils.utility_classes.dropdown import SearchableDropdown
from utils.gui_tabs.fragmentation_tab import FragmentationTabManager
from utils.gui_tabs.annotation_tab import AnnotationTabManager
from utils.gui_tabs.experiment_manager import ExperimentDataManager
from utils.utility_classes.event_handlers import EventHandlers
from utils.utility_classes.scoring_settings_dialog import ScoringSettingsDialog
from utils.utility_classes.dialog_manager import DataListEditorManager
from utils.peak_matching.persistent_fragmentation_worker import PersistentFragmentationManager
from utils.gui_tabs.rescoring_tab import RescoringTabManager
from utils.gui_tabs.protein_coverage_tab import ProteinCoverageTabManager
from utils.gui_tabs.manage_files_tab import ManageFilesTabManager
from utils.mod_database import CentralModificationDatabase
from utils.resource_path import get_data_file_path
from utils.fragmentation_presets_dialog import (
    PresetManagerDialog, load_custom_presets, save_custom_presets, format_preset_for_export
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('mass_spec_tool.log')
    ]
)
logger = logging.getLogger(__name__)

########################################################################
# Main GUI Application
########################################################################
class PeptideFragmentationApp(QWidget):
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
        #Initialize managers
        self.annotation_tab_manager = AnnotationTabManager(self)
        self.fragmentation_tab_manager = FragmentationTabManager(self)
        self.experiment_data_manager = ExperimentDataManager(self)
        self.event_handlers = EventHandlers(self)
        self.rescoring_tab_manager = RescoringTabManager(self)
        self.protein_coverage_tab_manager = ProteinCoverageTabManager(self)
        self.manage_files_tab_manager = ManageFilesTabManager(self)
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
        'on_settings_changed':          ('event_handlers', None),
        '_calculate_optimal_delay':     ('event_handlers', None),
        'perform_adaptive_update':      ('event_handlers', None),
        '_create_diagnostic_ion_rows':  ('event_handlers', None),
        '_update_spectrum_tracker':     ('event_handlers', None),
        '_get_selected_ion_types_for_tracking': ('event_handlers', None),
        'run_fragmentation_adaptive':   ('event_handlers', '_run_fragmentation_adaptive'),
        'update_modification_table':    ('event_handlers', 'on_peptide_changed'),
        'get_modifications_from_table': ('event_handlers', '_get_modifications_from_table'),
        '_on_cache_hit':                ('event_handlers', 'on_cache_hit'),
        '_on_cache_miss':               ('event_handlers', 'on_cache_miss'),
        'clear_mz_table':              ('event_handlers', 'on_clear_mz_table'),
        'extract_scan_data':            ('event_handlers', 'on_extract_scan_clicked'),
        'on_adaptive_fragmentation_finished': ('event_handlers', None),
        'on_fragmentation_error':       ('event_handlers', None),
        'validate_fragmentation_inputs': ('event_handlers', None),
        # experiment_data_manager
        'load_raw_data':                ('experiment_data_manager', None),
        'load_search_data':             ('experiment_data_manager', None),
        'add_msfragger_search_folder':  ('experiment_data_manager', None),
        'save_experiment':              ('experiment_data_manager', None),
        'load_experiment':              ('experiment_data_manager', None),
        # protein_coverage_tab_manager
        'load_fasta_file':              ('protein_coverage_tab_manager', None),
        # fragmentation_tab_manager
        'add_comparison_group':         ('fragmentation_tab_manager', None),
        'remove_comparison_group':      ('fragmentation_tab_manager', None),
        'clear_comparison_groups':      ('fragmentation_tab_manager', None),
        'update_comparison_plot':       ('fragmentation_tab_manager', None),
        'show_save_options':            ('fragmentation_tab_manager', None),
        'select_no_comparison_ion_types': ('fragmentation_tab_manager', None),
        'on_plot_type_changed':         ('fragmentation_tab_manager', None),
        '_update_group_name':           ('fragmentation_tab_manager', None),
    }

    # Maps attribute names to (manager_attr, target_attr) for property-like access.
    _PROPERTY_DELEGATION_MAP: dict[str, tuple[str, str | None]] = {
        'mass_spec_viewer':         ('annotation_tab_manager', None),
        'psm_summary_widget':       ('annotation_tab_manager', None),
        'spectrum_tracker':         ('annotation_tab_manager', None),
        'peptide_info_widget':      ('annotation_tab_manager', None),
        'raw_files':                ('experiment_data_manager', None),
        'search_files':             ('experiment_data_manager', None),
        'df_file_paths':            ('experiment_data_manager', None),
        'merged_df':                ('experiment_data_manager', None),
        'extracted_spectral_data':  ('experiment_data_manager', None),
    }

    def __getattr__(self, name):
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

        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    # -----------------------------------------------------------------
    # 1) Window and style
    # -----------------------------------------------------------------
    def _init_window_settings(self):

        ThemeManager.set_theme('light')  # Force light theme on startup
        # Configure application properties
        self.setWindowTitle("Mass Spectrum Analysis Tool")

        # Set minimum window size
        self.setMinimumSize(self.MIN_WINDOW_WIDTH, self.MIN_WINDOW_HEIGHT)


        # Set default size and center on screen
        self.resize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        self.center_on_screen()

        # Start maximized based on setting
        if LayoutConstants.START_MAXIMIZED:
            WindowSizeManager.set_fullscreen_windowed(self)

        self.setStyleSheet(StyleSheet.build_gui_style())

    # -----------------------------------------------------------------
    # 2) Data structures
    # -----------------------------------------------------------------
    def _init_data_structures(self):
        """Initialize data structures for the application - SIMPLIFIED"""
        # Row data for metadata
        self.selected_row_data = None

        # Load central modification database (replaces modifications_list.csv)
        self.central_mod_db = CentralModificationDatabase(
            get_data_file_path("central_modifications.json"),
            csv_fallback_path=get_data_file_path("modifications_list.csv"),
        )
        self.available_mods = self.central_mod_db.as_dataframe()
        self.diagnostic_ions = DataLoader.load_csv_with_fallback(
            get_data_file_path("diagnostic_ions.csv"), TableConfig.DIAGNOSTIC_IONS_COLUMNS, "diagnostic ions"
        )
        self.custom_ion_series = DataLoader.load_csv_with_fallback(
            get_data_file_path("custom_ion_series.csv"), TableConfig.CUSTOM_ION_SERIES_COLUMNS, "custom ion series"
        )

        # Initialize selected ions lists (keep in main app for UI)
        self.selected_custom_ions_data = []
        self.selected_diagnostic_ions_data = []

        # Scoring method toggles (X!Tandem always on)
        self.scoring_methods = {
            'consecutive_series': False,
            'complementary_pairs': False,
            'morpheus_score': False,
            'length_dependent_normalized_score': False
        }
        self.scoring_max_charge = 0  # 0 = no limit
        self._load_scoring_settings()
    # -----------------------------------------------------------------
    # 3) Main Layout
    # -----------------------------------------------------------------
    def _init_main_layout(self):
        self.top_layout = QVBoxLayout(self)
        self.setLayout(self.top_layout)
    # -----------------------------------------------------------------
    # 4) Menu Bar
    # ----------------------------------------------------------------- 
    def _init_menu_bar(self):
        self.menu_bar = QMenuBar(self)

        # Set fixed size policy for menu bar to prevent expansion
        self.menu_bar.setSizePolicy(
            QSizePolicy.Policy.Preferred,  # Use preferred width
            QSizePolicy.Policy.Fixed       # Fixed height
        )

        self.menu_bar.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        
        #File Button
        file_menu = self.menu_bar.addMenu("File")

        WidgetFactory.create_menu_action(self, file_menu,
                            "Load FASTA File",
                            "Load protein FASTA file for coverage analysis",
                            self.load_fasta_file)

        file_menu.addSeparator()  # Add separator for experiment options

        WidgetFactory.create_menu_action(self, file_menu,
                            "Save Experiment...",
                            "Save current experiment for quick reloading",
                            self.save_experiment)
        
        WidgetFactory.create_menu_action(self, file_menu, 
                            "Open Previous Experiment...",
                            "Load a previously saved experiment",
                            self.load_experiment)

        # Edit Modifications and Diagnostic Ions
        edit_menu = self.menu_bar.addMenu("Edit")
        WidgetFactory.create_menu_action(self, edit_menu,
                            "Edit Modifications List",
                            "Add, edit, or remove modifications",
                            lambda: self.edit_data_list("modifications"))

        WidgetFactory.create_menu_action(self, edit_menu,
                            "Edit Diagnostic Ions List",
                            "Add, edit, or remove diagnostic ions",
                            lambda: self.edit_data_list("diagnostic_ions"))
        WidgetFactory.create_menu_action(self, edit_menu,
                        "Edit Custom Ion Series",
                        "Add, edit, or remove custom ion series",
                        lambda: self.edit_data_list("custom_ion_series"))

        edit_menu.addSeparator()

        WidgetFactory.create_menu_action(self, edit_menu,
                        "Manage Fragmentation Presets...",
                        "View, rename, delete and export custom fragmentation method presets",
                        self._open_preset_manager)

        edit_menu.addSeparator()

        WidgetFactory.create_menu_action(self, edit_menu,
                            "Edit Search Tool Databases",
                            "View and edit MaxQuant/MetaMorpheus modification mass databases",
                            self.edit_mod_databases)

        #View Menu for themes
        view_menu = self.menu_bar.addMenu("View")
        
        # Theme submenu
        theme_menu = view_menu.addMenu("Theme")
        
        # Light theme action
        light_theme_action = QAction("Light Theme", self)
        light_theme_action.setCheckable(True)
        light_theme_action.setChecked(True)  # Default to light
        light_theme_action.triggered.connect(lambda: self.switch_theme('light'))
        theme_menu.addAction(light_theme_action)

        # Dark theme action
        dark_theme_action = QAction("Dark Theme", self)
        dark_theme_action.setCheckable(True)
        dark_theme_action.triggered.connect(lambda: self.switch_theme('dark'))
        theme_menu.addAction(dark_theme_action)
        
        # Create theme action group for mutual exclusivity
        theme_group = QActionGroup(self)
        theme_group.addAction(light_theme_action)
        theme_group.addAction(dark_theme_action)
        
        # Store references for theme switching
        self.light_theme_action = light_theme_action
        self.dark_theme_action = dark_theme_action
        
        # Window Size submenu
        view_menu.addSeparator()
        size_menu = view_menu.addMenu("Window Size")
        
        # Default size action (1680x900)
        default_size_action = QAction("Default (1680 x 900)", self)
        default_size_action.triggered.connect(lambda: self.set_window_size(1680, 900))
        size_menu.addAction(default_size_action)

        # Large size action (1920x1080)
        large_size_action = QAction("Large (1920 x 1080)", self)
        large_size_action.triggered.connect(lambda: self.set_window_size(1920, 1080))
        size_menu.addAction(large_size_action)

        # Small size action (1280x720)
        small_size_action = QAction("Small (1280 x 720)", self)
        small_size_action.triggered.connect(lambda: self.set_window_size(1280, 720))
        size_menu.addAction(small_size_action)

        # Settings menu
        settings_menu = self.menu_bar.addMenu("Settings")
        WidgetFactory.create_menu_action(self, settings_menu,
                            "Scoring Settings...",
                            "Configure scoring methods and parameters",
                            self._open_scoring_settings)

        settings_menu.addSeparator()

        # Cache management options
        WidgetFactory.create_menu_action(self, settings_menu,
                            "Clear Fragment Cache",
                            "Clear cached fragment calculations to free memory",
                            self.clear_fragment_cache)

        WidgetFactory.create_menu_action(self, settings_menu,
                            "Cache Statistics",
                            "View fragment cache performance statistics",
                            self.show_cache_statistics)


        # -----------------------------------------------------------------
        # 5) Left Scroll Area
        # -----------------------------------------------------------------
    def _create_resizable_left_panel(self, title: str) -> QWidget:
        """Create resizable left panel with menu bar at the top"""
        
        # Main container
        container = QWidget()
        # Use minimum width instead of fixed - allows resizing
        container.setMinimumWidth(LayoutConstants.LEFT_PANEL_MIN_WIDTH)
        container.setSizePolicy(
            QSizePolicy.Policy.Preferred,  # Can grow/shrink
            QSizePolicy.Policy.Expanding   # Takes vertical space
        )
        
        # Main layout
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Add the menu bar at the top of the left panel
        main_layout.addWidget(self.menu_bar)
            
        # Content widget for the scroll area
        content_widget = QWidget()
        # Remove fixed width to allow resizing
        content_widget.setMinimumWidth(LayoutConstants.LEFT_PANEL_MIN_WIDTH)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create the left scroll area content
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Create widget to hold all left content
        self.left_widget = QWidget()
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN
        )
        self.left_layout.setSpacing(LayoutConstants.LAYOUT_SPACING)
        
        # Set the widget to the scroll area
        self.left_scroll.setWidget(self.left_widget)
        
        # Add content to left scroll area
        self._setup_left_scroll_content()
        
        # Add scroll area to content widget
        content_layout.addWidget(self.left_scroll)
        
        # Add to main layout
        main_layout.addWidget(content_widget)
        
        # Store references
        container.content_widget = content_widget
        
        return container

    def _init_left_scroll_area(self):
        """Initialize the layout with fixed left panel and expanding content area"""

        ################################################################
        # CREATE MAIN HORIZONTAL LAYOUT
        ################################################################
        main_hlayout = QHBoxLayout()
        main_hlayout.setContentsMargins(0, 0, 0, 0)
        main_hlayout.setSpacing(0)

        ################################################################
        # LEFT PANEL - Fixed width controls with menu bar at top
        ################################################################
        self.left_panel_container = self._create_resizable_left_panel(title="Controls")
        self.left_panel_container.setFixedWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH)
        main_hlayout.addWidget(self.left_panel_container)

        ################################################################
        # MAIN CONTENT AREA - Tabbed interface
        ################################################################
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setStyleSheet(EditorConstants.get_tab_style())
        # Manage Files tab first (default tab)
        self.manage_files_tab_manager.setup_manage_files_tab()
        self.annotation_tab_manager.setup_annotation_tab()
        self.fragmentation_tab_manager.setup_fragmentation_analysis_tab()
        self.rescoring_tab_manager.setup_rescoring_tab()
        self.protein_coverage_tab_manager.setup_protein_coverage_tab()
        main_hlayout.addWidget(self.main_tab_widget, stretch=1)

        # Add layout to main layout
        self.top_layout.addLayout(main_hlayout)

        self.load_mock_data()
        
    #########################################
    #All Methods related to Fragmentation Tab
    #########################################

    ##########################
    #All Annotation tab 
    ##########################
  
    def _setup_left_scroll_content(self):
        """Setup the content inside the left scroll area with improved sizing"""
        # Peptide Sequence 
        row_peptide = QHBoxLayout()
        row_peptide.setSpacing(8)  
        
        peptide_label = QLabel("Peptide:")
        peptide_label.setMaximumWidth(50)  
        peptide_label.setMinimumHeight(28)  
        row_peptide.addWidget(peptide_label)
        
        self.peptide_input = QLineEdit()
        self.peptide_input.setPlaceholderText("Enter peptide")
        self.peptide_input.setMinimumHeight(28)
        self.peptide_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        regex = QRegularExpression("^[ACDEFGHIKLMNPQRSTVWY]*$")
        validator = QRegularExpressionValidator(regex, self.peptide_input)
        self.peptide_input.setValidator(validator)
        self.peptide_input.textChanged.connect(self.update_modification_table)
        self.peptide_input.textChanged.connect(self.on_settings_changed)
        row_peptide.addWidget(self.peptide_input)
        
        # Container widget for peptide row
        peptide_widget = QWidget()
        peptide_widget.setLayout(row_peptide)
        peptide_widget.setMinimumHeight(35)
        peptide_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  
        self.left_layout.addWidget(peptide_widget)
        
        # Create all spinboxes 
        spinbox_grid_layout = QVBoxLayout()
        spinbox_grid_layout.setSpacing(8)

         # First row: Max Charge and PPM Tolerance
        first_row_layout = QHBoxLayout()
        first_row_layout.setSpacing(8)
        
        # Max Charge spinbox with better width allocation
        max_charge_layout, self.max_charge_input = WidgetFactory.create_labeled_spinbox(
            "Max Charge:",
            min_value=1,
            max_value=10,
            default_value=1,
            parent=self,
            spinbox_width=80
        )
        self.max_charge_input.valueChanged.connect(self.validate_fragmentation_inputs)
        self.max_charge_input.valueChanged.connect(self.on_settings_changed) 
        first_row_layout.addLayout(max_charge_layout)

        # PPM spinbox
        ppm_layout, self.ppm_tolerance_input = WidgetFactory.create_labeled_spinbox(
            "PPM Tolerance:",
            min_value=1,
            max_value=1000000,
            default_value=10,
            parent=self,
            spinbox_width=80
        )
        self.ppm_tolerance_input.valueChanged.connect(self.on_settings_changed)  
        first_row_layout.addLayout(ppm_layout)

        spinbox_grid_layout.addLayout(first_row_layout)

        # Second row: Label Threshold and Max Neutral Losses
        second_row_layout = QHBoxLayout()
        second_row_layout.setSpacing(8)
        
        # Labelling Threshold spinbox
        threshold_layout, self.text_annotation_threshold = WidgetFactory.create_labeled_spinbox(
            "Label Threshold:",  
            min_value=0,
            max_value=100,
            default_value=0,
            parent=self,
            spinbox_width=60
        )
        second_row_layout.addLayout(threshold_layout)

        # Max Neutral Losses spinbox
        max_losses_layout, self.max_neutral_losses_input = WidgetFactory.create_labeled_spinbox(
            "Max Neutral Losses:",
            min_value=1,
            max_value=5,
            default_value=1,
            parent=self,
            spinbox_width=60
        )
        self.max_neutral_losses_input.valueChanged.connect(self.on_settings_changed)
        second_row_layout.addLayout(max_losses_layout)
        
        spinbox_grid_layout.addLayout(second_row_layout)

        # Isotope calculation checkbox
        self.calculate_isotopes_checkbox = QCheckBox("Calculate isotope peaks (M+1 to M+4)")
        self.calculate_isotopes_checkbox.setStyleSheet(EditorConstants.get_checkbox_style())
        self.calculate_isotopes_checkbox.setChecked(False)
        self.calculate_isotopes_checkbox.setToolTip(
            "When enabled, calculates isotope peaks M+1 through M+4 for all ions.\n"
            "Disabling this reduces the number of theoretical fragments and speeds up annotation.\n"
            "Note: The M-1 isotope for z+1 and c ions is always calculated regardless of this setting."
        )
        self.calculate_isotopes_checkbox.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.calculate_isotopes_checkbox)

        # Mod neutral losses checkbox
        self.enable_mod_nl_cb = QCheckBox("Enable mod neutral losses (*)")
        self.enable_mod_nl_cb.setStyleSheet(EditorConstants.get_checkbox_style())
        self.enable_mod_nl_cb.setChecked(False)
        self.enable_mod_nl_cb.setToolTip(
            "When enabled, generates * ion series for modification-specific neutral losses\n"
            "defined in the central modification database."
        )
        self.enable_mod_nl_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_mod_nl_cb)

        # Labile loss checkbox
        self.enable_labile_losses_cb = QCheckBox("Enable labile loss (~)")
        self.enable_labile_losses_cb.setStyleSheet(EditorConstants.get_checkbox_style())
        self.enable_labile_losses_cb.setChecked(False)
        self.enable_labile_losses_cb.setToolTip(
            "When enabled, generates ~ ion series for modifications marked as labile\n"
            "in the central modification database (entire modification mass lost)."
        )
        self.enable_labile_losses_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_labile_losses_cb)

        # Remainder ions checkbox
        self.enable_remainder_ions_cb = QCheckBox("Enable remainder ions (^)")
        self.enable_remainder_ions_cb.setStyleSheet(EditorConstants.get_checkbox_style())
        self.enable_remainder_ions_cb.setChecked(False)
        self.enable_remainder_ions_cb.setToolTip(
            "When enabled, generates ^ ion series for modifications with remainder masses\n"
            "in the central modification database (modification mass lost, remainder retained)."
        )
        self.enable_remainder_ions_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_remainder_ions_cb)

        # Container for spinboxes
        spinbox_container = QWidget()
        spinbox_container.setLayout(spinbox_grid_layout)
        spinbox_container.setMinimumHeight(140)
        spinbox_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.left_layout.addWidget(spinbox_container)

    # -----------------------------------------------------------------
    # 6) Collapsible Sections
    # -----------------------------------------------------------------
    def _init_collapsible_sections(self):
        """
        Create and add the collapsible widgets/tables:
          - m/z table
          - normal ion types
          - neutral loss ions
        """
        
        self._init_mz_table() # m/z and intensity table
        self._init_normal_ion_types()    # Normal ion types
        self._init_neutral_loss_ion_types() # Neutral loss ion types
        self._init_internal_ion_types()     # I_create_section_headernternal ion types
        self._init_custom_ion_series_section()  # Custom ion series selection
        self._init_diagnostic_ions_section() # Diagnostic Ion selection

    def _init_mz_table(self):
        """Create m/z table with simple paste functionality"""
        
        # Add section header
        mz_header = self._create_section_header("m/z and Intensity")
        self.left_layout.addWidget(mz_header)
        
        # Create simple paste table
        self.mz_table = SimplePasteTable(LayoutConstants.DEFAULT_TABLE_ROWS, 2, self)
        self.mz_table.setHorizontalHeaderLabels(["m/z", "Intensity"])
        
        # Apply your existing styling
        self.mz_table.setMinimumWidth(LayoutConstants.MIN_TABLE_WIDTH)
        self.mz_table.setMinimumHeight(LayoutConstants.MIN_TABLE_HEIGHT)
        self.mz_table.setMaximumHeight(200)
        self.mz_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Your existing styling code...
        self.mz_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mz_table.verticalHeader().setVisible(False)
        self.mz_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mz_table.setAlternatingRowColors(False)
        
  
        StyleSheet.apply_table_styling(self.mz_table)
        
        self.mz_table.itemChanged.connect(self.on_settings_changed)
        self.left_layout.addWidget(self.mz_table)

        # Add clear button underneath the table
        self.clear_mz_button = QPushButton("Clear Table")
        self.clear_mz_button.setMaximumWidth(100)  
        self.clear_mz_button.setMinimumHeight(28)  
        self.clear_mz_button.clicked.connect(self.clear_mz_table)
        self.clear_mz_button.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        
        # Create a container for the button to control alignment
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 5, 0, 5) 
        button_layout.addWidget(self.clear_mz_button)
        button_layout.addStretch()  # Push button to the left
        
        button_container.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        self.left_layout.addWidget(button_container)

    def _init_normal_ion_types(self):
        """Create normal ion types section with header that fits container"""
        # Load persisted custom presets
        self._custom_presets = load_custom_presets()

        # Add preset dropdown
        preset_combo = QComboBox()
        preset_combo.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        preset_combo.setStyleSheet(EditorConstants.get_combobox_style())
        preset_combo.currentTextChanged.connect(self._apply_ion_preset)
        self.left_layout.addWidget(preset_combo)
        self._ion_preset_combo = preset_combo
        self._refresh_preset_combo()

        # "Save as Preset" button row
        save_preset_btn = QPushButton("Save Current as Preset...")
        save_preset_btn.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        save_preset_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        save_preset_btn.setToolTip("Save the current ion selection as a named custom preset")
        save_preset_btn.clicked.connect(self._save_current_as_preset)
        self.left_layout.addWidget(save_preset_btn)

        # Add section header
        normal_ions_header = self._create_section_header("Normal Ion Types")
        self.left_layout.addWidget(normal_ions_header)
        
        # Create checkbox grid
        normal_ion_types = ["b", "y", "a", "x", "z", "z+1", "c", "c-1", "MH", "d", "w", "v"]
        self.normal_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self, 
            self.left_layout, 
            normal_ion_types,
            columns=4, 
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20
        )
        
        # Connect all checkboxes to adaptive update
        for checkbox in self.normal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)

    @staticmethod
    def _format_neutral_loss_label(raw: str) -> str:
        """
        Convert tokens like 'y-H2O' -> 'y–H₂O' using Unicode subscripts
        """
        parts = raw.split('-', 1)
        if len(parts) == 2:
            ion, loss = parts[0], parts[1]
        else:
            ion, loss = raw, ''

        def unicode_subscript(text: str) -> str:
            """Convert numbers to Unicode subscript"""
            subscript_map = {
                '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
                '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉'
            }
            result = text
            for digit, sub in subscript_map.items():
                result = result.replace(digit, sub)
            return result

        # Use en dash (–) instead of hyphen (-)
        if loss:
            return f'{ion}–{unicode_subscript(loss)}'
        return ion

    def _init_neutral_loss_ion_types(self):
        """Create neutral loss ion types section with header that fits container"""
        neutral_loss_header = self._create_section_header("Neutral Loss Ion Types")
        self.left_layout.addWidget(neutral_loss_header)

        neutral_loss_ion_types = [
            "y-H2O", "a-H2O", "b-H2O", "y-NH3", "b-NH3", "a-NH3",
            "b-SOCH4", "y-SOCH4", "b-H3PO4", "y-H3PO4", "a-H3PO4",
            "MH-H2O", "MH-NH3",
            "d-H2O", "d-NH3", "w-H2O", "w-NH3", "v-H2O", "v-NH3"
        ]

        self.neutral_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self,
            self.left_layout,
            neutral_loss_ion_types,
            columns=3,
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20,
            label_formatter=self._format_neutral_loss_label
        )

        for checkbox in self.neutral_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)

    def _apply_ion_preset(self, preset_name: str) -> None:
        """Apply an ion selection preset from the dropdown."""
        if preset_name == "-- Presets --":
            return

        # Check built-in presets first, then custom
        preset = ION_PRESETS.get(preset_name)
        is_full_preset = False
        if preset is None:
            raw_custom = self._custom_presets.get(preset_name)
            if raw_custom is None:
                return
            # Convert stored lists back to sets for the checkbox loop
            preset = {
                "normal": set(raw_custom.get("normal", [])),
                "neutral": set(raw_custom.get("neutral", [])),
            }
            is_full_preset = True
            custom_ions_data = raw_custom.get("custom_ions", [])
            diagnostic_ions_data = raw_custom.get("diagnostic_ions", [])

        # Block signals to avoid refragmenting for every single checkbox toggle
        for cb in self.normal_ion_checkboxes.values():
            cb.blockSignals(True)
        for cb in self.neutral_ion_checkboxes.values():
            cb.blockSignals(True)
        # Uncheck all, then check the preset's ions
        for ion, cb in self.normal_ion_checkboxes.items():
            cb.setCheckState(Qt.CheckState.Checked if ion in preset["normal"] else Qt.CheckState.Unchecked)
        for ion, cb in self.neutral_ion_checkboxes.items():
            cb.setCheckState(Qt.CheckState.Checked if ion in preset["neutral"] else Qt.CheckState.Unchecked)
        # Unblock
        for cb in self.normal_ion_checkboxes.values():
            cb.blockSignals(False)
        for cb in self.neutral_ion_checkboxes.values():
            cb.blockSignals(False)

        # Apply custom/diagnostic ions for full (user-defined) presets
        if is_full_preset:
            self.selected_custom_ions_data = list(custom_ions_data)
            self._reconcile_selected_ions_from_master(
                self.selected_custom_ions_data, self.custom_ion_series, "Series Name"
            )
            self._update_selected_custom_ions_table()
            self.selected_diagnostic_ions_data = list(diagnostic_ions_data)
            self._reconcile_selected_ions_from_master(
                self.selected_diagnostic_ions_data, self.diagnostic_ions, "Name"
            )
            self._update_selected_diagnostic_ions_table()

            # Restore enable-flag checkboxes (block signals; one update fires below)
            for attr, key in (
                ("enable_mod_nl_cb", "enable_mod_nl"),
                ("enable_labile_losses_cb", "enable_labile_losses"),
                ("enable_remainder_ions_cb", "enable_remainder_ions"),
            ):
                cb = getattr(self, attr, None)
                if cb is not None and key in raw_custom:
                    cb.blockSignals(True)
                    cb.setChecked(raw_custom[key])
                    cb.blockSignals(False)

        # Reset dropdown to placeholder
        self._ion_preset_combo.blockSignals(True)
        self._ion_preset_combo.setCurrentIndex(0)
        self._ion_preset_combo.blockSignals(False)
        # Trigger a single update
        self.on_settings_changed()

    def _refresh_preset_combo(self) -> None:
        """Re-populate the preset combo box with built-in and custom presets."""
        combo = self._ion_preset_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("-- Presets --")
        for name in ION_PRESETS:
            combo.addItem(name)
        for name in self._custom_presets:
            combo.addItem(name)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _get_current_preset_state(self) -> dict:
        """Capture the current ion selection state as a preset-compatible dict."""
        normal = [ion for ion, cb in self.normal_ion_checkboxes.items()
                  if cb.isChecked()]
        neutral = [ion for ion, cb in self.neutral_ion_checkboxes.items()
                   if cb.isChecked()]
        return {
            "normal": normal,
            "neutral": neutral,
            "custom_ions": list(self.selected_custom_ions_data),
            "diagnostic_ions": list(self.selected_diagnostic_ions_data),
            "enable_mod_nl": self.enable_mod_nl_cb.isChecked(),
            "enable_labile_losses": self.enable_labile_losses_cb.isChecked(),
            "enable_remainder_ions": self.enable_remainder_ions_cb.isChecked(),
        }

    def _save_current_as_preset(self) -> None:
        """Prompt the user for a name and save the current ion selection as a custom preset."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Save as Custom Preset",
            "Enter a name for this fragmentation method preset:"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Preset name cannot be empty.")
            return
        if name in ION_PRESETS:
            QMessageBox.warning(self, "Reserved Name",
                                f"'{name}' is a built-in preset name and cannot be overwritten.")
            return
        if name in self._custom_presets:
            reply = QMessageBox.question(
                self, "Overwrite Preset",
                f"A custom preset named '{name}' already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._custom_presets[name] = self._get_current_preset_state()
        if save_custom_presets(self._custom_presets):
            self._refresh_preset_combo()
            self.show_toast_message(f"Preset '{name}' saved.")
            # Refresh the manager dialog if it's open
            if hasattr(self, '_preset_manager_dialog') and self._preset_manager_dialog is not None:
                self._preset_manager_dialog.custom_presets = load_custom_presets()
                self._preset_manager_dialog.refresh()
        else:
            QMessageBox.critical(self, "Error", "Failed to save preset to disk.")

    def _open_preset_manager(self) -> None:
        """Open (or focus) the non-modal Preset Manager dialog."""
        if hasattr(self, '_preset_manager_dialog') and self._preset_manager_dialog is not None:
            self._preset_manager_dialog.raise_()
            self._preset_manager_dialog.activateWindow()
            return

        dlg = PresetManagerDialog(ION_PRESETS, parent=self)
        self._preset_manager_dialog = dlg

        def _on_presets_changed():
            self._custom_presets = load_custom_presets()
            self._refresh_preset_combo()

        dlg.presets_changed.connect(_on_presets_changed)
        dlg.finished.connect(lambda: setattr(self, '_preset_manager_dialog', None))
        dlg.show()

    def _init_internal_ion_types(self):
        """Create internal ion types section with header that fits container"""
        # Add section header
        internal_ions_header = self._create_section_header("Internal Ion Types")
        self.left_layout.addWidget(internal_ions_header)
        
        # Create checkbox grid
        internal_ions = ["b", "a"]
        self.internal_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self, 
            self.left_layout, 
            internal_ions, 
            columns=4,
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20
        )
        
        # Connect all checkboxes to adaptive update
        for checkbox in self.internal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)

    def _init_custom_ion_series_section(self):
        """Create custom ion series selection using SearchableDropdown"""
        self.left_layout.addWidget(self._create_section_header("Custom Ion Series"))

        self.custom_ion_dropdown = SearchableDropdown("Click or type to search custom ion series...")
        self.custom_ion_dropdown.item_selected.connect(self._add_custom_ion_from_dropdown)

        # Create a layout and pass it to the helper 
        inner_layout = QHBoxLayout()
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(4)
        inner_layout.addWidget(self.custom_ion_dropdown)

        # Create container widget using layout
        search_widget = self._create_widget_container(inner_layout, min_height=35)
        self.left_layout.addWidget(search_widget)

        # selected table
        self.selected_custom_ions_table = self._create_selection_table(
            ["Series Name", "Mass Offset", "Restriction"],
            self._show_custom_ion_context_menu,
            "selected_custom_ions_data"
        )
        # Apply color delegate to the Color column (index 3)
        self.selected_custom_ions_color_delegate = ColorDelegate()
        self.selected_custom_ions_table.setItemDelegateForColumn(3, self.selected_custom_ions_color_delegate)
        self.left_layout.addWidget(self.selected_custom_ions_table)

        # initialize lists
        self.selected_custom_ions_data = []
        self._refresh_custom_dropdown_items()
            
    def _init_diagnostic_ions_section(self):
        """Create diagnostic ions selection using SearchableDropdown"""
        self.left_layout.addWidget(self._create_section_header("Diagnostic Ions"))

        self.diagnostic_ion_dropdown = SearchableDropdown("Click or type to search diagnostic ions...")
        self.diagnostic_ion_dropdown.item_selected.connect(self._add_diagnostic_ion_from_dropdown)

        # Create a layout and pass it to the helper 
        inner_layout = QHBoxLayout()
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(4)
        inner_layout.addWidget(self.diagnostic_ion_dropdown)

        search_widget = self._create_widget_container(inner_layout, min_height=35)
        self.left_layout.addWidget(search_widget)

        # selected table
        self.selected_diagnostic_ions_table = self._create_selection_table(
            ["Name", "Mass"],
            self._show_diagnostic_ion_context_menu,
            "selected_diagnostic_ions_data"
        )
        # Apply color delegate to the Color column (index 3)
        self.selected_diagnostic_ions_color_delegate = ColorDelegate()
        self.selected_diagnostic_ions_table.setItemDelegateForColumn(3, self.selected_diagnostic_ions_color_delegate)
        self.left_layout.addWidget(self.selected_diagnostic_ions_table)

        self.selected_diagnostic_ions_data = []
        self._refresh_diagnostic_dropdown_items()

    def _refresh_ion_dropdown(self, dropdown_attr: str, data_source: str, display_format_fn) -> None:
        """
        Generic method to refresh dropdown items from a data source

        Args:
            dropdown_attr: Name of the dropdown attribute (e.g., 'custom_ion_dropdown')
            data_source: Name of the data source attribute (e.g., 'custom_ion_series')
            display_format_fn: Function that takes a row dict and returns (display_text, row_dict)
        """
        items = []
        try:
            dropdown = getattr(self, dropdown_attr)
            dropdown.clear_items()

            data = getattr(self, data_source)

            # If data is a pandas DataFrame
            if hasattr(data, 'iterrows'):
                for _, row in data.iterrows():
                    display, row_dict = display_format_fn(row.to_dict())
                    items.append((display, row_dict))
            else:
                # fallback: if it's a list of dicts
                for row in data or []:
                    display, row_dict = display_format_fn(row)
                    items.append((display, row_dict))

            dropdown.set_items(items)

        except Exception as e:
            logger.exception(f"Failed to refresh {dropdown_attr}")

    def _refresh_custom_dropdown_items(self):
        """Populate custom dropdown from self.custom_ion_series"""
        def format_custom_ion(row):
            restriction = str(row.get('Restriction', '')) if row.get('Restriction') is not None else ''
            restriction_suffix = f" [{restriction}]" if restriction else ""
            display = f"{row['Series Name']} — {row['Base Ion']} ({row['Mass Offset']:.4f}){restriction_suffix}"
            return display, row

        self._refresh_ion_dropdown('custom_ion_dropdown', 'custom_ion_series', format_custom_ion)

    def _refresh_diagnostic_dropdown_items(self):
        """Populate diagnostic dropdown from self.diagnostic_ions"""
        def format_diagnostic_ion(row):
            display = f"{row['Name']} ({row['Mass']:.4f})"
            return display, row

        self._refresh_ion_dropdown('diagnostic_ion_dropdown', 'diagnostic_ions', format_diagnostic_ion)

    def _add_custom_ion_from_dropdown(self, selected_row_dict):
        """Delegate to event handlers"""
        return self.event_handlers.on_custom_ion_selected(selected_row_dict)
    
    def _add_diagnostic_ion_from_dropdown(self, selected_row_dict):
        """Delegate to event handlers"""
        return self.event_handlers.on_diagnostic_ion_selected(selected_row_dict)


    def load_mock_data(self) -> None:
        """Load mock data using utility"""
        matched_data, mock_row_data = MockDataGenerator.generate_mock_spectrum_data()

        # Use annotation manager to set data
        self.annotation_tab_manager.set_mass_spec_data(
            matched_data=matched_data,
            peptide=self.DEFAULT_MOCK_PEPTIDE,
            mod_positions=[],
            row_data=mock_row_data
        )

    def _init_scan_selection_controls(self):
        """Initialize controls for direct scan selection with improved sizing"""
        
        # Add section header
        scan_selection_header = self._create_section_header("Direct Scan Selection")
        self.left_layout.addWidget(scan_selection_header)
        
        # Add checkbox to enable/disable this feature
        self.enable_direct_scan_checkbox = QCheckBox("Enable Direct Scan Selection")
        self.enable_direct_scan_checkbox.setChecked(False)
        self.enable_direct_scan_checkbox.stateChanged.connect(self.toggle_direct_scan_mode)
        self.enable_direct_scan_checkbox.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        self.enable_direct_scan_checkbox.setMinimumHeight(25)  
        self.left_layout.addWidget(self.enable_direct_scan_checkbox)
        
        # Raw file dropdown with improved layout
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8) 
        
        file_label = QLabel("Raw File:")
        file_label.setMaximumWidth(70)  
        file_label.setMinimumHeight(28)  
        file_layout.addWidget(file_label)
        
        self.raw_file_combo = QComboBox()
        self.raw_file_combo.setEnabled(False)  
        self.raw_file_combo.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 95)  
        self.raw_file_combo.setMinimumHeight(28) 
        file_layout.addWidget(self.raw_file_combo)
        
        # Create container widget for the layout
        file_widget = QWidget()
        file_widget.setLayout(file_layout)
        file_widget.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        file_widget.setMinimumHeight(35)  
        self.left_layout.addWidget(file_widget)
        
        # Scan number input 
        scan_layout = QHBoxLayout()
        scan_layout.setSpacing(8) 
        
        scan_label = QLabel("Scan:")
        scan_label.setMaximumWidth(45)
        scan_label.setMinimumHeight(28)  
        scan_layout.addWidget(scan_label)
        
        self.scan_number_input = QLineEdit()
        self.scan_number_input.setEnabled(False) 
        self.scan_number_input.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-9]*$")))
        self.scan_number_input.setMaximumWidth(90)  
        self.scan_number_input.setMinimumHeight(28)  
        scan_layout.addWidget(self.scan_number_input)
        
        # Extract button
        self.extract_scan_button = QPushButton("Extract")
        self.extract_scan_button.setEnabled(False)  
        self.extract_scan_button.clicked.connect(self.extract_scan_data)
        self.extract_scan_button.setMaximumWidth(75)  
        self.extract_scan_button.setMinimumHeight(28)  
        scan_layout.addWidget(self.extract_scan_button)
        
        # Add stretch to push everything left
        scan_layout.addStretch()
        
        # Create container widget for the scan layout
        scan_widget = QWidget()
        scan_widget.setLayout(scan_layout)
        scan_widget.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        scan_widget.setMinimumHeight(35) 
        self.left_layout.addWidget(scan_widget)

    
    # -----------------------------------------------------------------
    # 8) Adaptive update system
    # -----------------------------------------------------------------

    def edit_mod_databases(self):
        """Open the modification mass database editor."""
        from utils.mod_database import ModDatabaseEditorDialog, ModificationMassDatabase
        from utils.resource_path import get_data_file_path

        maxquant_db = getattr(self.experiment_data_manager, 'maxquant_mod_db', None)
        metamorpheus_db = getattr(self.experiment_data_manager, 'metamorpheus_mod_db', None)

        if maxquant_db is None:
            maxquant_db = ModificationMassDatabase(get_data_file_path("maxquant_mods.json"))
            self.experiment_data_manager.maxquant_mod_db = maxquant_db
        if metamorpheus_db is None:
            metamorpheus_db = ModificationMassDatabase(get_data_file_path("metamorpheus_mods.json"))
            self.experiment_data_manager.metamorpheus_mod_db = metamorpheus_db

        dialog = ModDatabaseEditorDialog(maxquant_db, metamorpheus_db, self)
        dialog.exec()

    def combine_and_process_psm_files(self):
        """Delegate to experiment data manager and sync data"""
        result = self.experiment_data_manager.combine_and_process_psm_files()
        
        # Sync the data across tabs
        if hasattr(self.experiment_data_manager, 'merged_df'):
            self.sync_psm_data_across_tabs(self.experiment_data_manager.merged_df)
        
        return result
    
    def sync_psm_data_across_tabs(self, data) -> None:
        """Sync PSM data across all tabs that need it"""
        try:
            # Update annotation tab PSM summary
            if (self.annotation_tab_manager and
                self.annotation_tab_manager.psm_summary_widget):
                self.annotation_tab_manager.psm_summary_widget.setData(data)
                logger.debug(f"Updated annotation tab PSM summary with {len(data)} records")

            # Update fragmentation tab PSM summary
            if hasattr(self, 'frag_psm_summary_widget') and self.frag_psm_summary_widget:
                self.frag_psm_summary_widget.setData(data)
                logger.debug(f"Updated fragmentation tab PSM summary with {len(data)} records")


            # Update protein coverage tab with PSM data
            if self.protein_coverage_tab_manager:
                self.protein_coverage_tab_manager.set_psm_data(data)
                logger.debug(f"Updated protein coverage tab with {len(data)} records")

            logger.debug(f"Synced PSM data across tabs: {len(data)} records")

        except Exception as e:
            logger.exception("Failed to sync PSM data across tabs")

    ####################################################################
    # Pasting m/z, modifications, run fragmentation...
    ####################################################################

    def on_peptide_selected(self, peptide: str, parsed_mods: list, charge: int, row_data: dict):
        """Legacy method - delegate to event handlers for backward compatibility"""
        return self.event_handlers.on_peptide_selected(peptide, parsed_mods, charge, row_data)

    def populate_mz_table(self, mz_array, intensity_array):
        """Populate the m/z table with given arrays"""
        self.event_handlers.set_populating_table(True)
        try:
            data_pairs = list(zip(mz_array, intensity_array))
            TableUtils.populate_two_column_table(self.mz_table, data_pairs)
        finally:
            self.event_handlers.set_populating_table(False)
        
        # Trigger validation after populating data (only once)
        self.validate_fragmentation_inputs()
        # Trigger one adaptive update after population is complete
        self.on_settings_changed()

    def on_interactive_modifications_changed(self, modifications: list):
        """Legacy method - delegate to event handlers for backward compatibility"""
        return self.event_handlers.on_interactive_modifications_changed(modifications)

    def toggle_direct_scan_mode(self, state):
        """Delegate to event handlers"""
        return self.event_handlers.on_direct_scan_toggle(state)

    def edit_data_list(self, data_type: str) -> None:
        """Edit data lists with proper update propagation - NON-MODAL"""
        # Central modification database gets its own dedicated editor
        if data_type == "modifications":
            self._edit_central_modifications()
            return

        data_map = {
            "diagnostic_ions": (self.diagnostic_ions, "Diagnostic Ions", get_data_file_path("diagnostic_ions.csv")),
            "custom_ion_series": (self.custom_ion_series, "Custom Ion Series", get_data_file_path("custom_ion_series.csv"))
        }

        if data_type not in data_map:
            logger.warning(f"Unknown data type for editing: {data_type}")
            return

        current_data, title, file_path = data_map[data_type]

        # Use the dialog manager to open the editor
        self.dialog_manager.open_editor(data_type, current_data, file_path, title)

    def _edit_central_modifications(self):
        """Open the central modification database editor."""
        from utils.mod_database import CentralModEditorDialog

        dialog_attr = "_modifications_editor_dialog"
        if hasattr(self, dialog_attr) and getattr(self, dialog_attr) is not None:
            existing = getattr(self, dialog_attr)
            existing.raise_()
            existing.activateWindow()
            return

        editor = CentralModEditorDialog(self.central_mod_db, self)
        setattr(self, dialog_attr, editor)

        def on_finished():
            # Refresh the backward-compat DataFrame view
            self.available_mods = self.central_mod_db.as_dataframe()
            self.annotation_tab_manager.set_available_modifications(
                self.central_mod_db.as_modification_list()
            )
            # Clear fragmentation cache so new NL definitions take effect
            if hasattr(self, 'persistent_fragmentation_manager'):
                self.persistent_fragmentation_manager.fragment_cache.clear()
            self.show_toast_message("Central modifications updated!")
            setattr(self, dialog_attr, None)

        def on_closed():
            setattr(self, dialog_attr, None)

        editor.finished.connect(on_finished)
        editor.rejected.connect(on_closed)
        editor.show()

    def _toggle_scoring_method(self, method_key, enabled):
        """Toggle a scoring method on/off and recalculate"""
        self.scoring_methods[method_key] = enabled
        self._save_scoring_settings()
        self.on_settings_changed()

    def _open_scoring_settings(self):
        """Open the scoring settings dialog."""
        dlg = ScoringSettingsDialog(self)
        dlg.exec()

    def _load_scoring_settings(self):
        """Load persisted scoring settings from QSettings."""
        from PyQt6.QtCore import QSettings
        s = QSettings(self.SETTINGS_ORGANIZATION, self.SETTINGS_APP_NAME)
        for key in self.scoring_methods:
            val = s.value(f"scoring/{key}")
            if val is not None:
                self.scoring_methods[key] = str(val).lower() in ('true', '1')
        mc = s.value("scoring/max_charge")
        if mc is not None:
            try:
                self.scoring_max_charge = int(mc)
            except (ValueError, TypeError):
                pass

    def _save_scoring_settings(self):
        """Persist current scoring settings to QSettings."""
        from PyQt6.QtCore import QSettings
        s = QSettings(self.SETTINGS_ORGANIZATION, self.SETTINGS_APP_NAME)
        for key, val in self.scoring_methods.items():
            s.setValue(f"scoring/{key}", val)
        s.setValue("scoring/max_charge", self.scoring_max_charge)

    def generate_dynamic_ion_types(self):
        """Generate ion types using utility"""
        
        return IonTypeGenerator.generate_dynamic_ion_types(
            self.normal_ion_checkboxes,
            self.neutral_ion_checkboxes,
            self.max_neutral_losses_input.value()
        )
    
    def clear_fragment_cache(self) -> None:
        """Clear cache using utility"""
        cleared_count = CacheManager.clear_cache(self.persistent_fragmentation_manager)
        logger.info(f"Cleared {cleared_count} cached fragments")
        self.cache_hit_count = 0
        self.cache_miss_count = 0
    
    def show_cache_statistics(self):
        """Show cache statistics using utility"""
        # Update manager with current counts
        if self.persistent_fragmentation_manager:
            self.persistent_fragmentation_manager.cache_hit_count = self.cache_hit_count
            self.persistent_fragmentation_manager.cache_miss_count = self.cache_miss_count
        
        stats = CacheManager.get_cache_stats(self.persistent_fragmentation_manager)
        
        message = f"""Fragment Cache Statistics:
        
Cache Size: {stats['cache_size']} / {stats['max_cache_size']} entries
Total Requests: {stats['total_requests']}
Cache Hits: {stats['hit_count']}
Cache Misses: {stats['miss_count']}
Hit Rate: {stats['hit_rate_percent']:.1f}%
Memory Usage: ~{stats['cache_size'] * 50:.0f} KB (estimated)"""
        
        QMessageBox.information(self, "Cache Statistics", message)

    def _setup_persistent_fragmentation(self) -> None:
        """Setup persistent fragmentation manager"""
        # Initialize cache tracking counters
        self.cache_hit_count = 0
        self.cache_miss_count = 0

        self.persistent_fragmentation_manager = PersistentFragmentationManager()

        logger.debug("Persistent fragmentation manager initialized")

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

    def closeEvent(self, event) -> None:
        """Handle application close event with proper cleanup"""
        logger.debug("Application closing - cleaning up threads...")

        # Clean up protein coverage tab
        if hasattr(self, 'protein_coverage_tab_manager') and self.protein_coverage_tab_manager:
            logger.debug("Cleaning up protein coverage tab...")
            self.protein_coverage_tab_manager.cleanup()

        # Stop the persistent fragmentation manager
        if hasattr(self, 'persistent_fragmentation_manager') and self.persistent_fragmentation_manager:
            logger.debug("Shutting down persistent fragmentation manager...")
            self.persistent_fragmentation_manager.shutdown()

            # Wait for the thread to finish with a timeout
            if hasattr(self.persistent_fragmentation_manager, 'worker_thread') and self.persistent_fragmentation_manager.worker_thread:
                if self.persistent_fragmentation_manager.worker_thread.isRunning():
                    logger.debug("Waiting for worker thread to finish...")
                    if not self.persistent_fragmentation_manager.worker_thread.wait(3000):  # 3 second timeout
                        logger.warning("Worker thread didn't finish gracefully, terminating...")
                        self.persistent_fragmentation_manager.worker_thread.terminate()
                        self.persistent_fragmentation_manager.worker_thread.wait(1000)  # Wait 1 more second

        # Stop any pending timers
        if hasattr(self, '_update_timer'):
            self._update_timer.stop()

        # Save settings and geometry before closing
        self._save_scoring_settings()
        WindowSizeManager.save_geometry(self)

        logger.debug("Cleanup complete")
        event.accept()

    # -----------------------------------------------------------------
    # Generic Ion Selection Methods
    # -----------------------------------------------------------------
    def _remove_selected_ion(self, row_index, data_list_attr, update_method, name_key, ion_type_name):
        """Generic method to remove an ion from a selection list"""
        data_list = getattr(self, data_list_attr)
        if 0 <= row_index < len(data_list):
            removed_ion = data_list.pop(row_index)
            update_method()
            self.on_settings_changed()
            self.show_toast_message(f"Removed '{removed_ion[name_key]}' from {ion_type_name}.")

    def _show_ion_context_menu(self, position, table, data_list_attr, remove_action_text, remove_callback):
        """Generic method to show context menu for ion selection tables"""
        item = table.itemAt(position)

        if item is None:
            return

        row = item.row()
        data_list = getattr(self, data_list_attr)
        if row >= len(data_list):
            return

        menu = QMenu(self)
        remove_action = QAction(remove_action_text, self)
        remove_action.triggered.connect(lambda: remove_callback(row))
        menu.addAction(remove_action)
        menu.exec(table.mapToGlobal(position))

    @staticmethod
    def _reconcile_selected_ions_from_master(selected_list: list, master_data, key_column: str):
        """Refresh selected ion dicts in-place from the master DataFrame.

        Matches by key_column and updates all properties to current values.
        Ions no longer in master data are kept with their stored values.
        """
        if master_data is None or master_data.empty:
            return
        lookup = {}
        for _, row in master_data.iterrows():
            key = row.get(key_column)
            if key is not None:
                lookup[key] = row.to_dict()
        for ion_dict in selected_list:
            key = ion_dict.get(key_column)
            if key in lookup:
                for prop, value in lookup[key].items():
                    ion_dict[prop] = value

    def _update_ion_selection_table(self, table, data_list, column_configs, color_column_idx=None):
        """
        Generic method to update ion selection tables

        Args:
            table: The QTableWidget to update
            data_list: List of dictionaries containing ion data
            column_configs: List of tuples (data_key, format_string) for each column
                          format_string can be None (use str()), a format like '.4f', or a callable
            color_column_idx: Index of the color column (if any)
        """
        table.setRowCount(len(data_list))

        for row_idx, ion_data in enumerate(data_list):
            for col_idx, (data_key, format_spec) in enumerate(column_configs):
                value = ion_data.get(data_key, '')

                # Format the value
                if format_spec is None:
                    text = str(value) if value else ""
                elif callable(format_spec):
                    text = format_spec(value)
                elif isinstance(format_spec, str) and '.' in format_spec:
                    # It's a numeric format like '.4f'
                    text = f"{value:{format_spec}}"
                else:
                    text = str(value) if value else ""

                item = QTableWidgetItem(text)

                # Handle color column
                if col_idx == color_column_idx and value:
                    item.setBackground(QColor(value))
                    text_color = QColor(EditorConstants.get_contrasting_text_color(value))
                    item.setForeground(text_color)
                else:
                    item.setForeground(QColor(EditorConstants.TEXT_COLOR()))

                table.setItem(row_idx, col_idx, item)

    def _remove_custom_ion(self, row_index):
        """Remove custom ion from selected list"""
        self._remove_selected_ion(
            row_index,
            'selected_custom_ions_data',
            self._update_selected_custom_ions_table,
            'Series Name',
            'selected custom ions'
        )

    def _update_selected_custom_ions_table(self):
        """Update the selected custom ions table display"""
        column_configs = [
            ('Base Ion', None),
            ('Series Name', None),
            ('Mass Offset', '.4f'),
            ('Color', None),
            ('Restriction', lambda v: str(v) if v else "")
        ]
        self._update_ion_selection_table(
            self.selected_custom_ions_table,
            self.selected_custom_ions_data,
            column_configs,
            color_column_idx=3
        )

    def _show_custom_ion_context_menu(self, position):
        """Show context menu for custom ion table"""
        self._show_ion_context_menu(
            position,
            self.selected_custom_ions_table,
            'selected_custom_ions_data',
            "Remove Custom Ion",
            self._remove_custom_ion
        )

    def _remove_diagnostic_ion(self, row_index):
        """Remove diagnostic ion from selected list"""
        self._remove_selected_ion(
            row_index,
            'selected_diagnostic_ions_data',
            self._update_selected_diagnostic_ions_table,
            'Name',
            'selected diagnostic ions'
        )

    def _update_selected_diagnostic_ions_table(self):
        """Update the selected diagnostic ions table display"""
        column_configs = [
            ('Name', None),
            ('HTML Name', None),
            ('Mass', '.4f'),
            ('Color', None)
        ]
        self._update_ion_selection_table(
            self.selected_diagnostic_ions_table,
            self.selected_diagnostic_ions_data,
            column_configs,
            color_column_idx=3
        )

    def _show_diagnostic_ion_context_menu(self, position):
        """Show context menu for diagnostic ion table"""
        self._show_ion_context_menu(
            position,
            self.selected_diagnostic_ions_table,
            'selected_diagnostic_ions_data',
            "Remove Diagnostic Ion",
            self._remove_diagnostic_ion
        )

    def switch_theme(self, theme_name: str) -> None:
        """Switch between light and dark themes - UPDATED"""
        logger.debug(f"Switching to {theme_name} theme")

        # Update theme in theme manager
        ThemeManager.set_theme(theme_name)

        # Update theme selection in menu
        if theme_name == 'light':
            self.light_theme_action.setChecked(True)
            self.dark_theme_action.setChecked(False)
        else:
            self.light_theme_action.setChecked(False)
            self.dark_theme_action.setChecked(True)

        # Apply new stylesheet to main application
        self.setStyleSheet(StyleSheet.build_gui_style())

        # Update all major widget styles
        self._update_all_widget_styles()
        self.annotation_tab_manager.update_theme(theme_name)
        self.fragmentation_tab_manager.update_theme(theme_name)
        self.rescoring_tab_manager.update_theme(theme_name)
        self.protein_coverage_tab_manager.update_theme(theme_name)
        self.manage_files_tab_manager.update_theme(theme_name)

        logger.debug(f"Theme switched to {theme_name}")

    def _update_all_widget_styles(self) -> None:
        """Update styles for all widgets that need explicit theme updates"""
        self._update_section_headers()
        self._update_panel_headers()
        self._update_tables()
        self._update_form_widgets()
        self._update_special_widgets()

        logger.debug("Updated all widget styles including section headers and checkboxes")

    def _update_section_headers(self) -> None:
        """Update section header styles for theme changes"""
        section_headers = self.findChildren(QLabel, "section_header")
        for header in section_headers:
            # Apply new stylesheet
            header.setStyleSheet(StyleSheet.get_section_header_style())

            # Also update font directly to ensure immediate change
            font = header.font()
            font.setFamily(EditorConstants.FONT_FAMILY())
            font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
            font.setBold(True)
            header.setFont(font)

            # Force geometry update
            header.updateGeometry()
            header.update()

    def _update_panel_headers(self) -> None:
        """Update panel header styles for theme changes"""
        panel_headers = self.findChildren(QFrame)
        for frame in panel_headers:
            if hasattr(frame, 'layout') and frame.layout() and frame.layout().count() > 0:
                # Check if this is a panel header
                for i in range(frame.layout().count()):
                    item = frame.layout().itemAt(i)
                    if item and isinstance(item.widget(), QLabel):
                        frame.setStyleSheet(StyleSheet.get_panel_header_style())

                        # Update the label font inside the panel header
                        label = item.widget()
                        font = label.font()
                        font.setFamily(EditorConstants.FONT_FAMILY())
                        font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
                        font.setBold(True)
                        label.setFont(font)
                        label.updateGeometry()
                        label.update()
                        break

    def _update_tables(self) -> None:
        """Update table styles for theme changes"""
        all_tables = self.findChildren(QTableWidget)
        for table in all_tables:
            # Apply new table styling
            StyleSheet.apply_table_styling(table)

            # Force header updates
            h_header = table.horizontalHeader()
            if h_header:
                h_header.setFixedHeight(EditorConstants.HEADER_MIN_HEIGHT())
                # Update header font
                font = h_header.font()
                font.setFamily(EditorConstants.FONT_FAMILY())
                font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
                font.setBold(True)
                h_header.setFont(font)

    def _update_form_widgets(self) -> None:
        """Update form widget styles (spinboxes, checkboxes, labels)"""
        # Update spinboxes explicitly
        for spinbox in self.findChildren(QSpinBox):
            spinbox.setStyleSheet(EditorConstants.get_spinbox_style())

        # Update checkboxes
        for checkbox in self.findChildren(QCheckBox):
            checkbox.setStyleSheet(EditorConstants.get_checkbox_style())

        # Update all QLabel widgets (for spinbox labels, etc.)
        for label in self.findChildren(QLabel):
            # Skip section headers and other specially styled labels
            if label.objectName() != "section_header" and "section_header" not in label.styleSheet():
                # Check if label has custom styling or is a standard label
                current_style = label.styleSheet()
                if "color:" in current_style or not current_style:
                    # Update color for labels with explicit color or no styling
                    label.setStyleSheet(f"""
                        QLabel {{
                            color: {EditorConstants.TEXT_COLOR()};
                        }}
                    """)

        # Update tab widget styling
        for tab_widget in self.findChildren(QTabWidget):
            tab_widget.setStyleSheet(EditorConstants.get_tab_style())

    def _update_special_widgets(self) -> None:
        """Update special widget styles (ion tiles, PSM summary, spectrum tracker)"""
        # Update ion tiles for theme changes
        from utils.utility_classes.widgets import IonTile
        for tile in self.findChildren(IonTile):
            tile._update_style()

        # Update the PSM summary widget styling
        if hasattr(self, 'psm_summary_widget'):
            self.annotation_tab_manager._update_psm_summary_theme()

        # Update spectrum tracker styling
        if hasattr(self, 'spectrum_tracker'):
            self.annotation_tab_manager._update_spectrum_tracker_theme()

    def _create_section_header(self, title: str) -> QLabel:
        """Create a standardized section header with proper object name"""
        header = QLabel(title)
        header.setObjectName("section_header")  #Set object name for CSS targeting
        header.setStyleSheet(StyleSheet.get_section_header_style())
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return header

    def _create_widget_container(self, layout: QHBoxLayout, max_width: Optional[int] = None,
                                 min_height: Optional[int] = None) -> QWidget:
        """Create a standardized widget container"""
        widget = QWidget()
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if max_width is not None:
            widget.setMaximumWidth(max_width)

        if min_height:
            widget.setMinimumHeight(min_height)

        return widget

    def _create_selection_table(self, headers: List[str], context_menu_handler,
                                data_list_name: str) -> QTableWidget:
        """Create a standardized selection table with common properties"""
        table = TableUtils.create_basic_table(
            row_count=3,
            col_count=len(headers),
            headers=headers,
            min_width=LayoutConstants.MIN_TABLE_WIDTH,
            parent=self
        )

        table.setMinimumHeight(80)
        table.setMaximumHeight(150)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(context_menu_handler)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.itemChanged.connect(self.on_settings_changed)

        return table

    def show_toast_message(self, message: str, duration: int = 2000) -> None:
        """Show a toast message using QToaster"""
        toaster = QToaster(self)
        toaster.show_message(message, duration)

   #backwards compatibility - getter/setter property pairs
    @property
    def _skip_adaptive_update(self):
        """Get skip adaptive update flag from event handlers"""
        return self.event_handlers.get_skip_adaptive_update()
    
    @_skip_adaptive_update.setter
    def _skip_adaptive_update(self, value):
        """Set skip adaptive update flag in event handlers"""
        self.event_handlers.set_skip_adaptive_update(value)
    
    @property
    def _has_manual_changes(self):
        """Get manual changes flag from event handlers"""
        return self.event_handlers.get_has_manual_changes()
    
    @_has_manual_changes.setter
    def _has_manual_changes(self, value):
        """Set manual changes flag in event handlers"""
        self.event_handlers.set_has_manual_changes(value)

def main():
    app = QApplication(sys.argv)
    window = PeptideFragmentationApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    main()
