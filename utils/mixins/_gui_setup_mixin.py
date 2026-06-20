import logging

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QCheckBox,
    QComboBox,
    QCompleter,
    QHeaderView,
    QMenuBar,
    QSizePolicy,
    QScrollArea,
    QLineEdit,
    QTabWidget,
)
from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import QRegularExpressionValidator, QAction, QActionGroup

from config import TableConfig
from utils.style.style import StyleSheet, ThemeManager, EditorConstants
from utils.utility_classes.widgets import WidgetFactory, IonTile, NoScrollSpinBox, NoScrollComboBox
from utils.utilities import SimplePasteTable, WindowSizeManager, DataLoader
from utils.style.GUI_dimensions import LayoutConstants
from utils.mod_database import CentralModificationDatabase
from utils.resource_path import get_data_file_path

logger = logging.getLogger(__name__)


class _GUISetupMixin:

    # -----------------------------------------------------------------
    # 1) Window and style
    # -----------------------------------------------------------------
    def _init_window_settings(self):

        ThemeManager.set_theme("light")  # Force light theme on startup
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
            get_data_file_path("diagnostic_ions.csv"),
            TableConfig.DIAGNOSTIC_IONS_COLUMNS,
            "diagnostic ions",
        )
        self.custom_ion_series = DataLoader.load_csv_with_fallback(
            get_data_file_path("custom_ion_series.csv"),
            TableConfig.CUSTOM_ION_SERIES_COLUMNS,
            "custom ion series",
        )
        self.glycan_compositions = self._load_glycan_compositions()

        from utils.peak_matching.constants import load_snfg_shapes
        from utils.utility_classes.htmlformating import HTMLFormatter

        HTMLFormatter.update_snfg_shapes(load_snfg_shapes())

        # Initialize selected ions lists (keep in main app for UI)
        self.selected_custom_ions_data = []
        self.selected_diagnostic_ions_data = []

        # Scoring method toggles (X!Tandem always on)
        self.scoring_methods = {
            "consecutive_series": False,
            "complementary_pairs": False,
            "mokapot_fdr": False,
        }
        self.scoring_max_charge = 0  # 0 = no limit
        self.scoring_nl_in_count = (
            False  # Whether NL species count toward ion position count
        )
        self.calculate_isotopes = False  # Whether to calculate M+1 to M+N isotope peaks
        self.isotope_max = 4  # Max isotope number when calculate_isotopes is True
        self.annotation_mode = "manual"  # 'auto' | 'manual'
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
            QSizePolicy.Policy.Fixed,  # Fixed height
        )

        self.menu_bar.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)

        # File Button
        file_menu = self.menu_bar.addMenu("File")

        WidgetFactory.create_menu_action(
            self,
            file_menu,
            "Load FASTA File",
            "Load protein FASTA file for coverage analysis",
            self.load_fasta_file,
        )

        file_menu.addSeparator()  # Add separator for experiment options

        WidgetFactory.create_menu_action(
            self,
            file_menu,
            "Save Experiment...",
            "Save current experiment for quick reloading",
            self.save_experiment,
        )

        WidgetFactory.create_menu_action(
            self,
            file_menu,
            "Open Previous Experiment...",
            "Load a previously saved experiment",
            self.load_experiment,
        )

        # Edit Modifications and Diagnostic Ions
        edit_menu = self.menu_bar.addMenu("Edit")
        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Edit Modifications List",
            "Add, edit, or remove modifications",
            lambda: self.edit_data_list("modifications"),
        )

        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Edit Diagnostic Ions List",
            "Add, edit, or remove diagnostic ions",
            lambda: self.edit_data_list("diagnostic_ions"),
        )
        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Edit Custom Ion Series",
            "Add, edit, or remove custom ion series",
            lambda: self.edit_data_list("custom_ion_series"),
        )

        edit_menu.addSeparator()

        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Manage Fragmentation Presets...",
            "View, rename, delete and export custom fragmentation method presets",
            self._open_preset_manager,
        )

        edit_menu.addSeparator()

        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Glycan Database...",
            "Manage glycan structure presets and custom monosaccharide definitions",
            self._open_glycan_database_editor,
        )

        edit_menu.addSeparator()

        WidgetFactory.create_menu_action(
            self,
            edit_menu,
            "Edit Search Tool Databases",
            "View and edit MaxQuant/MetaMorpheus modification mass databases",
            self.edit_mod_databases,
        )

        # View Menu for themes
        view_menu = self.menu_bar.addMenu("View")

        # Theme submenu
        theme_menu = view_menu.addMenu("Theme")

        # Light theme action
        light_theme_action = QAction("Light Theme", self)
        light_theme_action.setCheckable(True)
        light_theme_action.setChecked(True)  # Default to light
        light_theme_action.triggered.connect(lambda: self.switch_theme("light"))
        theme_menu.addAction(light_theme_action)

        # Dark theme action
        dark_theme_action = QAction("Dark Theme", self)
        dark_theme_action.setCheckable(True)
        dark_theme_action.triggered.connect(lambda: self.switch_theme("dark"))
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
        WidgetFactory.create_menu_action(
            self,
            settings_menu,
            "Scoring Settings...",
            "Configure scoring methods and parameters",
            self._open_scoring_settings,
        )

        settings_menu.addSeparator()

        # Cache management options
        WidgetFactory.create_menu_action(
            self,
            settings_menu,
            "Clear Fragment Cache",
            "Clear cached fragment calculations to free memory",
            self.clear_fragment_cache,
        )

        WidgetFactory.create_menu_action(
            self,
            settings_menu,
            "Cache Statistics",
            "View fragment cache performance statistics",
            self.show_cache_statistics,
        )

        settings_menu.addSeparator()

        self.manual_annotation_action = QAction("Manual Annotation Mode", self)
        self.manual_annotation_action.setCheckable(True)
        self.manual_annotation_action.setChecked(True)
        self.manual_annotation_action.setToolTip(
            "When enabled, fragmentation only runs when you press the Annotate button."
        )
        self.manual_annotation_action.triggered.connect(self._toggle_annotation_mode)
        settings_menu.addAction(self.manual_annotation_action)

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
            QSizePolicy.Policy.Expanding,  # Takes vertical space
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
        self.left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Create widget to hold all left content
        self.left_widget = QWidget()
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN,
            LayoutConstants.WIDGET_MARGIN,
        )
        self.left_layout.setSpacing(LayoutConstants.LAYOUT_SPACING)

        # Set the widget to the scroll area
        self.left_scroll.setWidget(self.left_widget)

        # Add content to left scroll area
        self._setup_left_scroll_content()

        # Annotate button — pinned above scroll so it stays visible when scrolling
        self.annotate_button = QPushButton("Annotate")
        self.annotate_button.setToolTip(
            "Run fragmentation and annotation with current settings.\n"
            "Enable 'Manual Annotation Mode' in Settings to use this button."
        )
        self.annotate_button.setMinimumHeight(30)
        self.annotate_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.annotate_button.setEnabled(True)
        self.annotate_button.setStyleSheet(
            "QPushButton { background-color: #90EE90; color: #1a1a1a; font-weight: bold; border: 1px solid #5cb85c; border-radius: 3px; }"
            "QPushButton:hover { background-color: #7CDB7C; }"
            "QPushButton:pressed { background-color: #6ACC6A; }"
            "QPushButton:disabled { background-color: #c8c8c8; color: #888; border-color: #aaa; }"
        )
        self.annotate_button.clicked.connect(
            self.event_handlers.perform_adaptive_update
        )
        content_layout.addWidget(self.annotate_button)

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
        self.left_panel_container.setFixedWidth(
            LayoutConstants.LEFT_PANEL_INITIAL_WIDTH
        )
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
        self.peptide_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
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
        peptide_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
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
            spinbox_width=80,
        )
        self.max_charge_input.valueChanged.connect(self.validate_fragmentation_inputs)
        self.max_charge_input.valueChanged.connect(self.on_settings_changed)
        self.max_charge_input.setToolTip(
            "Maximum charge for the peptide ions. Max charge for precursor and fragments ions will be Max Charge -1"
            )
        first_row_layout.addLayout(max_charge_layout)

        # PPM spinbox
        ppm_layout, self.ppm_tolerance_input = WidgetFactory.create_labeled_spinbox(
            "PPM Tolerance:",
            min_value=1,
            max_value=1000000,
            default_value=10,
            parent=self,
            spinbox_width=80,
        )
        self.ppm_tolerance_input.valueChanged.connect(self.on_settings_changed)
        first_row_layout.addLayout(ppm_layout)

        spinbox_grid_layout.addLayout(first_row_layout)

        # Second row: Label Threshold and Max Neutral Losses
        second_row_layout = QHBoxLayout()
        second_row_layout.setSpacing(8)

        # Labelling Threshold spinbox
        threshold_layout, self.text_annotation_threshold = (
            WidgetFactory.create_labeled_spinbox(
                "Label Threshold:",
                min_value=0,
                max_value=100,
                default_value=0,
                parent=self,
                spinbox_width=60,
            )
        )
        self.text_annotation_threshold.setToolTip(
            "Labeling threshold for text annotations. (e.g. if 1% only peaks with >1% relative intensity will be labeled with text. Setting to 0 labels all peaks.)"
            )
        second_row_layout.addLayout(threshold_layout)

        # Max Neutral Losses spinbox
        max_losses_layout, self.max_neutral_losses_input = (
            WidgetFactory.create_labeled_spinbox(
                "Max Neutral Losses:",
                min_value=1,
                max_value=5,
                default_value=1,
                parent=self,
                spinbox_width=60,
            )
        )
        self.max_neutral_losses_input.valueChanged.connect(self.on_settings_changed)
        self.max_neutral_losses_input.setToolTip(
            "Maximum number of neutral losses (e.g. 1 Neutral Loss -H2O, - NH3, 2 Neutral Losses -2H2O, - 2NH3)."
            )
        second_row_layout.addLayout(max_losses_layout)

        spinbox_grid_layout.addLayout(second_row_layout)

        # Mod neutral losses tile
        self.enable_mod_nl_cb = IonTile("Modification Neutral Loss (*)")
        self.enable_mod_nl_cb.setChecked(False)
        self.enable_mod_nl_cb.setToolTip(
            "When enabled, generates * ion series for modification-specific neutral losses\n"
            "defined in the central modification database."
        )
        self.enable_mod_nl_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_mod_nl_cb)

        # Labile loss tile
        self.enable_labile_losses_cb = IonTile("Modification Labile Loss (~)")
        self.enable_labile_losses_cb.setChecked(False)
        self.enable_labile_losses_cb.setToolTip(
            "When enabled, generates ~ ion series for modifications marked as labile\n"
            "in the central modification database (entire modification mass lost)."
        )
        self.enable_labile_losses_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_labile_losses_cb)

        # Remainder ions tile
        self.enable_remainder_ions_cb = IonTile("Modification Remainder Ions (^)")
        self.enable_remainder_ions_cb.setChecked(False)
        self.enable_remainder_ions_cb.setToolTip(
            "When enabled, generates ^ ion series for modifications with remainder masses\n"
            "in the central modification database (modification mass lost, remainder retained)."
        )
        self.enable_remainder_ions_cb.stateChanged.connect(self.on_settings_changed)
        spinbox_grid_layout.addWidget(self.enable_remainder_ions_cb)




        # Glycan Y-ions row 1: enable + composition
        glycan_row1 = QHBoxLayout()
        glycan_row1.setSpacing(4)
        self.glycan_enabled_cb = IonTile("Glycan Y-ions")
        self.glycan_enabled_cb.setToolTip(
            "Enable glycan Y-ion series.\nSelect the glycan composition to fragment."
        )
        glycan_row1.addWidget(self.glycan_enabled_cb)
        self.glycan_composition_combo = NoScrollComboBox()
        self.glycan_composition_combo.setEditable(True)
        self.glycan_composition_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.glycan_composition_combo.setPlaceholderText("e.g. Hex(5)HexNAc(2)")
        self.glycan_composition_combo.setToolTip(
            "Glycan composition to fragment (e.g. Hex(5)HexNAc(2)NeuAc(1)).\n"
            "Use Edit → Glycan Database to manage presets."
        )
        # Enable substring (contains) search in the dropdown
        _glycan_completer = self.glycan_composition_combo.completer()
        if _glycan_completer is None:
            _glycan_completer = QCompleter(self.glycan_composition_combo)
            self.glycan_composition_combo.setCompleter(_glycan_completer)
        _glycan_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        _glycan_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        _glycan_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        glycan_row1.addWidget(self.glycan_composition_combo, 1)
        spinbox_grid_layout.addLayout(glycan_row1)

        # Glycan Y-ions row 2: max charge + SNFG toggle
        glycan_row2 = QHBoxLayout()
        glycan_row2.setSpacing(4)
        glycan_row2.addWidget(QLabel("Glycan Max charge:"))
        self.glycan_max_charge_spin = NoScrollSpinBox()
        self.glycan_max_charge_spin.setRange(1, 10)
        self.glycan_max_charge_spin.setValue(4)
        self.glycan_max_charge_spin.setFixedWidth(52)
        self.glycan_max_charge_spin.setToolTip(
            "Maximum charge state for glycan Y-ions."
        )
        glycan_row2.addWidget(self.glycan_max_charge_spin)
        self.glycan_snfg_cb = QCheckBox("SNFG shapes")
        self.glycan_snfg_cb.setStyleSheet(EditorConstants.get_checkbox_style())
        self.glycan_snfg_cb.setToolTip(
            "Display glycan Y-ion annotations using SNFG shape symbols\n"
            "instead of shorthand letters (e.g. ■₂●₁ instead of N₂H₁)."
        )
        glycan_row2.addWidget(self.glycan_snfg_cb)
        glycan_row2.addStretch()
        spinbox_grid_layout.addLayout(glycan_row2)

        self.glycan_enabled_cb.stateChanged.connect(self._on_glycan_settings_changed)
        self.glycan_composition_combo.currentTextChanged.connect(
            self._on_glycan_settings_changed
        )
        self.glycan_max_charge_spin.valueChanged.connect(
            self._on_glycan_settings_changed
        )
        self.glycan_snfg_cb.stateChanged.connect(self._on_glycan_snfg_toggled)

        # Container for spinboxes
        spinbox_container = QWidget()
        spinbox_container.setLayout(spinbox_grid_layout)
        spinbox_container.setMinimumHeight(140)
        spinbox_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
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

        self._init_mz_table()  # m/z and intensity table
        self._init_normal_ion_types()  # Normal ion types
        self._init_neutral_loss_ion_types()  # Neutral loss ion types
        self._init_internal_ion_types()  # Internal ion types
        self._init_diagnostic_ions_section()  # Diagnostic Ion selection
        self._init_custom_ion_series_section()  # Custom ion series selection


    def _init_mz_table(self):
        """Create m/z table with simple paste functionality"""

        # Create simple paste table
        self.mz_table = SimplePasteTable(LayoutConstants.DEFAULT_TABLE_ROWS, 2, self)
        self.mz_table.setHorizontalHeaderLabels(["m/z", "Intensity"])

        # Apply your existing styling
        self.mz_table.setMinimumWidth(LayoutConstants.MIN_TABLE_WIDTH)
        self.mz_table.setMinimumHeight(LayoutConstants.MIN_TABLE_HEIGHT)
        self.mz_table.setMaximumHeight(200)
        self.mz_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        # Your existing styling code...
        self.mz_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.mz_table.verticalHeader().setVisible(False)
        self.mz_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.mz_table.setAlternatingRowColors(False)

        StyleSheet.apply_table_styling(self.mz_table)

        self.mz_table.itemChanged.connect(self.on_settings_changed)
        self.left_layout.addWidget(self.mz_table)

        # Add clear button underneath the table
        self.clear_mz_button = QPushButton("Clear Table")
        self.clear_mz_button.setMaximumWidth(100)
        self.clear_mz_button.setMinimumHeight(28)
        self.clear_mz_button.clicked.connect(self.clear_mz_table)
        self.clear_mz_button.setStyleSheet(
            EditorConstants.get_pushbutton_style("danger")
        )

        # Create a container for the button to control alignment
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.addWidget(self.clear_mz_button)
        button_layout.addStretch()  # Push button to the left

        button_container.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        self.left_layout.addWidget(button_container)
