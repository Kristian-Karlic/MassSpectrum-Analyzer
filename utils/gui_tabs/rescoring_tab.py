import pandas as pd
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox,
    QLabel, QGroupBox, QCheckBox, QGridLayout, QTableWidget,
    QFileDialog, QLineEdit, QSplitter, QScrollArea, QHeaderView, QTableWidgetItem,
    QDialog, QTextEdit, QMessageBox, QTabWidget, QComboBox, QApplication,
    QAbstractItemView
)
import numpy as np
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.utility_classes.widgets import WidgetFactory
from utils.style.style import StyleSheet, EditorConstants
from utils.utilities import  UIHelpers, IonCollectionUtils
from utils.rescoring.rescoring_worker import RescoringWorker
from utils.rescoring.results_viewer_widget import RescoreResultsViewerWidget
from utils.utilities import DataProcessingUtils
from utils.tables.excel_table import ExcelLikeTableWidget


class RescoringTabManager:
    """Manager for the Rescoring tab"""
    def __init__(self, parent):
        self.parent = parent
        self.rescoring_tab = None
        self.results_viewer = None
        self.worker_thread = None
        self.current_results_df = None
        
    def setup_rescoring_tab(self):
        """Setup the rescoring tab with controls and results viewer - FIXED layout"""
        self.rescoring_tab = QWidget()
        main_layout = QVBoxLayout(self.rescoring_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create tab widget for rescoring sections
        self.rescoring_tab_widget = QTabWidget()
        self.rescoring_tab_widget.setStyleSheet(EditorConstants.get_tab_style())
        main_layout.addWidget(self.rescoring_tab_widget)
        
        # Tab 1: Configuration (with preview)
        config_tab = self._create_configuration_tab()
        self.rescoring_tab_widget.addTab(config_tab, "Configuration")
        self.results_viewer = RescoreResultsViewerWidget(self.parent)
        self.rescoring_tab_widget.addTab(self.results_viewer, "Results")
        
        # Add main rescoring tab to application
        self.parent.main_tab_widget.addTab(self.rescoring_tab, "Rescoring")
        
        return self.rescoring_tab
        
    def _create_configuration_tab(self):
        """Create configuration tab with preview"""
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)
        
        # Store reference for theme updates
        self.config_widget = config_widget

        
        # Create horizontal splitter: Controls | Preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left: Controls
        controls_widget = self._create_controls_panel()
        splitter.addWidget(controls_widget)
        
        # Right: Preview
        preview_widget = self._create_preview_panel()
        splitter.addWidget(preview_widget)
        
        # Set splitter proportions (40% controls, 60% preview)
        splitter.setSizes([400, 600])
        
        # Action buttons at bottom
        button_layout = QHBoxLayout()
        
        self.run_button = QPushButton("Run Rescoring")
        self.run_button.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        self.run_button.clicked.connect(self.run_rescoring)
        button_layout.addWidget(self.run_button)

        self.debug_export_button = QPushButton("Export Debug Data")
        self.debug_export_button.setStyleSheet(EditorConstants.get_pushbutton_style("warning"))
        self.debug_export_button.setToolTip("Export full dataframe with all intermediate columns for debugging")
        self.debug_export_button.clicked.connect(self.export_debug_data)
        self.debug_export_button.setEnabled(False)
        button_layout.addWidget(self.debug_export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        return config_widget
    
    def _create_preview_panel(self):
        """Create preview panel showing filtered dataframe statistics"""
        preview_widget = QWidget()
        layout = QVBoxLayout(preview_widget)
        
        # Store reference for theme updates
        self.preview_widget = preview_widget
        
        # Header
        preview_header = QLabel("Data Preview")
        preview_header.setStyleSheet(StyleSheet.get_section_header_style())
        layout.addWidget(preview_header)
        
        # Info text
        info_label = QLabel(
            "Preview shows the data that will be rescored based on current filter settings. "
            "Adjust filters and click 'Update Preview' to see changes."
        )
        info_label.setStyleSheet(StyleSheet.get_label_style())
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Update preview button
        update_btn = QPushButton("Update Preview")
        update_btn.setStyleSheet(EditorConstants.get_pushbutton_style("info"))
        update_btn.clicked.connect(self._update_preview)
        layout.addWidget(update_btn)
        
        # Statistics display
        stats_group = QGroupBox("Filtered Data Statistics")
        stats_group.setStyleSheet(EditorConstants.get_groupbox_style())
        stats_layout = QVBoxLayout(stats_group)
        
        # Create scroll area for stats
        stats_scroll = QScrollArea()
        stats_scroll.setWidgetResizable(True)
        stats_scroll.setStyleSheet(StyleSheet.get_scrollarea_style())
        stats_scroll.setMaximumHeight(300)
        
        self.preview_stats_widget = QWidget()
        self.preview_stats_layout = QVBoxLayout(self.preview_stats_widget)
        
        # Initial "no preview" message
        no_preview_label = QLabel("Click 'Update Preview' to see filtered data statistics")
        no_preview_label.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        self.preview_stats_layout.addWidget(no_preview_label)
        
        stats_scroll.setWidget(self.preview_stats_widget)
        stats_layout.addWidget(stats_scroll)
        layout.addWidget(stats_group)
        
        # Sample data table
        sample_group = QGroupBox("Sample Data (First 10 Rows)")
        sample_group.setStyleSheet(EditorConstants.get_groupbox_style())
        sample_layout = QVBoxLayout(sample_group)
        
        self.preview_table = QTableWidget()
        StyleSheet.apply_table_styling(self.preview_table)
        self.preview_table.setMaximumHeight(300)
        sample_layout.addWidget(self.preview_table)
        
        layout.addWidget(sample_group)
        layout.addStretch()
        
        return preview_widget
    
    
    def _create_controls_panel(self):
        """Create controls panel with scrollable settings"""
        controls_widget = QWidget()
        layout = QVBoxLayout(controls_widget)
        
        # Store reference for theme updates
        self.controls_widget = controls_widget
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(StyleSheet.get_scrollarea_style())
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Store reference for theme updates
        self.controls_scroll_widget = scroll_widget
        
        # Add groups
        scroll_layout.addWidget(self._create_ion_settings_info_group())
        scroll_layout.addWidget(self._create_filtering_options_group())
        scroll_layout.addWidget(self._create_processing_params_group())
        scroll_layout.addWidget(self._create_decoy_detection_group())
        scroll_layout.addWidget(self._create_migration_tracking_group())
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        return controls_widget

        
    def _create_ion_settings_info_group(self):
        """Create a group showing current ion selection settings from main app"""
        info_group = QGroupBox("Ion Selection Settings (from Annotation Tab)")
        info_group.setStyleSheet(EditorConstants.get_groupbox_style())
        info_layout = QVBoxLayout()
        
        info_text = QLabel(
            "Rescoring will use the ion types, neutral losses, diagnostic ions, and custom ion series "
            "currently selected in the Annotation tab, along with the pre-extracted spectral data from "
            "'Prepare data'. Review those settings before running rescoring."
        )
        info_text.setStyleSheet(StyleSheet.get_label_style())
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        
        # Button to show current settings
        show_settings_btn = QPushButton("Show Current Ion Settings")
        show_settings_btn.setStyleSheet(EditorConstants.get_pushbutton_style("info"))
        show_settings_btn.clicked.connect(self._show_current_ion_settings)
        info_layout.addWidget(show_settings_btn)
        
        info_group.setLayout(info_layout)
        return info_group
    
    def _show_current_ion_settings(self):
        """Display a dialog showing the current ion settings from main app"""

        dialog = QDialog(self.parent)
        dialog.setWindowTitle("Current Ion Settings")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet(StyleSheet.get_dialog_style())
        
        layout = QVBoxLayout(dialog)
        
        # Create text display
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet(EditorConstants.get_lineedit_style())
        
        # Gather current settings
        settings_text = self._get_current_ion_settings_text()
        text_edit.setPlainText(settings_text)
        
        layout.addWidget(text_edit)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()
    
    def _get_current_ion_settings_text(self):
        """Get formatted text of current ion settings"""
        lines = []
        lines.append("=== CURRENT ION SETTINGS ===\n")
        
        # Basic ion types
        lines.append("Basic Ion Types:")
        selected_basic = [ion for ion, cb in self.parent.normal_ion_checkboxes.items() if cb.isChecked()]
        if selected_basic:
            lines.append(f"  {', '.join(selected_basic)}")
        else:
            lines.append("  None selected")
        lines.append("")
        
        # Neutral loss ions
        lines.append("Neutral Loss Ion Types:")
        selected_neutral = [ion for ion, cb in self.parent.neutral_ion_checkboxes.items() if cb.isChecked()]
        if selected_neutral:
            lines.append(f"  {', '.join(selected_neutral)}")
        else:
            lines.append("  None selected")
        lines.append("")
        
        # Internal ions
        lines.append("Internal Ion Types:")
        selected_internal = [ion for ion, cb in self.parent.internal_ion_checkboxes.items() if cb.isChecked()]
        if selected_internal:
            lines.append(f"  {', '.join(selected_internal)}")
        else:
            lines.append("  None selected")
        lines.append("")
        
        # Custom ion series
        lines.append("Custom Ion Series:")
        if hasattr(self.parent, 'selected_custom_ions_data') and self.parent.selected_custom_ions_data:
            for ion in self.parent.selected_custom_ions_data:
                lines.append(f"  {ion.get('Series Name', 'Unknown')} (Base: {ion.get('Base Ion', '?')}, Offset: {ion.get('Mass Offset', 0)})")
        else:
            lines.append("  None selected")
        lines.append("")
        
        # Diagnostic ions
        lines.append("Diagnostic Ions:")
        if hasattr(self.parent, 'selected_diagnostic_ions_data') and self.parent.selected_diagnostic_ions_data:
            for ion in self.parent.selected_diagnostic_ions_data:
                lines.append(f"  {ion.get('Name', 'Unknown')} (Mass: {ion.get('Mass', 0)})")
        else:
            lines.append("  None selected")
        lines.append("")
        
        # Processing parameters
        lines.append("=== PROCESSING PARAMETERS ===\n")
        lines.append(f"PPM Tolerance: {self.parent.ppm_tolerance_input.value()}")
        lines.append(f"Max Neutral Losses: {self.parent.max_neutral_losses_input.value()}")
        lines.append(f"Max Charge: {self.parent.max_charge_input.value()}")
        scoring_mc = self.scoring_max_charge_spin.value()
        lines.append(f"Max Charge for Scoring: {scoring_mc if scoring_mc > 0 else 'No limit'}")

        # Scoring methods
        scoring = getattr(self.parent, 'scoring_methods', {})
        enabled = [k for k, v in scoring.items() if v]
        if enabled:
            lines.append(f"Enabled Scoring: X!Tandem + {', '.join(enabled)}")
        else:
            lines.append("Enabled Scoring: X!Tandem only")

        return "\n".join(lines)
    
    def _create_processing_params_group(self):
        """Create processing parameters group"""
        params_group = QGroupBox("Processing Parameters")
        params_group.setStyleSheet(EditorConstants.get_groupbox_style())
        params_layout = QGridLayout()
        
        # CPU cores
        max_cores = os.cpu_count() or 4
        cores_layout, self.cores_spin = WidgetFactory.create_labeled_spinbox(
            "CPU Cores:",
            min_value=1,
            max_value=max_cores,
            default_value=min(max_cores - 1, 4),
            parent=self.parent
        )
        self.cores_spin.setToolTip(f"Your PC has {max_cores} cores available")
        params_layout.addLayout(cores_layout, 0, 0)
        
        cores_info = QLabel(f"(Max {max_cores} cores)")
        cores_info.setStyleSheet(StyleSheet.get_label_style())
        params_layout.addWidget(cores_info, 0, 1)
        
        # REMOVED: PPM override controls - always use GUI value
        ppm_info = QLabel(f"PPM Tolerance from GUI: {self.parent.ppm_tolerance_input.value()}")
        ppm_info.setStyleSheet(StyleSheet.get_label_style())
        params_layout.addWidget(ppm_info, 1, 0, 1, 2)

        # Isotope calculation toggle
        self.calculate_isotopes_checkbox = QCheckBox("Calculate and match isotope peaks (M+1 to M+4)")
        self.calculate_isotopes_checkbox.setStyleSheet(EditorConstants.get_checkbox_style())
        self.calculate_isotopes_checkbox.setChecked(False)
        self.calculate_isotopes_checkbox.setToolTip(
            "When enabled, calculates isotope peaks M+1 through M+4 for all ions.\n"
            "Matched isotope peaks contribute to annotated TIC but NOT to ion counts or scoring.\n"
            "Note: The M-1 isotope for z+1 and c ions (used for migration tracking) "
            "is always calculated regardless of this setting."
        )
        params_layout.addWidget(self.calculate_isotopes_checkbox, 2, 0, 1, 2)

        # Max charge state for scoring
        scoring_charge_layout, self.scoring_max_charge_spin = WidgetFactory.create_labeled_spinbox(
            "Max Charge for Scoring:",
            min_value=0,
            max_value=10,
            default_value=getattr(self.parent, 'scoring_max_charge', 0),
            parent=self.parent
        )
        self.scoring_max_charge_spin.setToolTip(
            "Limit which charge states contribute to ion counts and scoring.\n"
            "0 = no limit (all charges used).\n"
            "E.g. 2 = only +1 and +2 ions are counted for\n"
            "X!Tandem, Morpheus, etc."
        )
        params_layout.addLayout(scoring_charge_layout, 3, 0)
        scoring_charge_info = QLabel("(0 = no limit)")
        scoring_charge_info.setStyleSheet(StyleSheet.get_label_style())
        params_layout.addWidget(scoring_charge_info, 3, 1)

        params_group.setLayout(params_layout)
        return params_group

        
    def _on_use_annotation_ppm_changed(self, state):
        """Handle checkbox state change for using annotation PPM"""
        use_annotation = state == Qt.CheckState.Checked.value
        self.ppm_spin.setEnabled(not use_annotation)
        
        if use_annotation:
            # Show current annotation tab PPM value
            current_ppm = self.parent.ppm_tolerance_input.value()
            self.ppm_spin.setValue(current_ppm)
    
    def _create_filtering_options_group(self):
        """Create filtering options group with dropdown menus"""
        filter_group = QGroupBox("Filtering Options")
        filter_group.setStyleSheet(EditorConstants.get_groupbox_style())
        filter_layout = QVBoxLayout()
        
        # Info label
        info = QLabel("By default, all PSMs will be rescored. Use filters below to reduce the dataset.")
        info.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        info.setWordWrap(True)
        filter_layout.addWidget(info)
        
        # Filter mode selection (dropdown)
        filter_mode_container = QWidget()
        filter_mode_layout = QHBoxLayout(filter_mode_container)
        filter_mode_layout.setContentsMargins(0, 0, 0, 0)
        
        filter_mode_label = QLabel("Filter Mode:")
        filter_mode_label.setStyleSheet(StyleSheet.get_label_style())
        filter_mode_layout.addWidget(filter_mode_label)
        
        self.filter_mode_combo = QComboBox()
        self.filter_mode_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.filter_mode_combo.addItems([
            "No Filtering (Use All PSMs)",
            "Filter by Unique Peptides",
            "Filter by Unique Modified Peptides"
        ])
        self.filter_mode_combo.currentIndexChanged.connect(self._on_filter_mode_combo_changed)
        filter_mode_layout.addWidget(self.filter_mode_combo, stretch=1)
        
        filter_layout.addWidget(filter_mode_container)
        
        # Top N option (only enabled when filtering is active)
        topn_container = QWidget()
        topn_layout = QHBoxLayout(topn_container)
        topn_layout.setContentsMargins(20, 5, 0, 0)
        
        topn_label = QLabel("Keep Top N by X!Tandem:")
        topn_label.setStyleSheet(StyleSheet.get_label_style())
        topn_layout.addWidget(topn_label)
        
        self.topN_spin = QSpinBox()
        self.topN_spin.setStyleSheet(EditorConstants.get_spinbox_style())
        self.topN_spin.setRange(1, 50)
        self.topN_spin.setValue(1)
        self.topN_spin.setEnabled(False)
        topn_layout.addWidget(self.topN_spin)
        
        topn_layout.addStretch()
        filter_layout.addWidget(topn_container)
        
        # Grouping options (checkboxes - can select both)
        grouping_label = QLabel("Apply Filters Grouped By:")
        grouping_label.setStyleSheet(StyleSheet.get_label_style())
        filter_layout.addWidget(grouping_label)
        
        grouping_container = QWidget()
        grouping_layout = QVBoxLayout(grouping_container)
        grouping_layout.setContentsMargins(20, 0, 0, 0)
        
        self.groupby_group_checkbox = QCheckBox("Group by Group")
        self.groupby_group_checkbox.setStyleSheet(EditorConstants.get_checkbox_style())
        self.groupby_group_checkbox.setEnabled(False)
        grouping_layout.addWidget(self.groupby_group_checkbox)
        
        self.groupby_replicate_checkbox = QCheckBox("Group by Replicate")
        self.groupby_replicate_checkbox.setStyleSheet(EditorConstants.get_checkbox_style())
        self.groupby_replicate_checkbox.setEnabled(False)
        grouping_layout.addWidget(self.groupby_replicate_checkbox)
        
        filter_layout.addWidget(grouping_container)
        
        # File grouping table
        grouping_table_group = QGroupBox("File Grouping (Required for Group/Replicate Filters)")
        grouping_table_group.setStyleSheet(EditorConstants.get_groupbox_style())
        grouping_table_layout = QVBoxLayout(grouping_table_group)
        
        instructions = QLabel(
            "Assign groups and replicates to files. This is required if using 'Group by Group' or 'Group by Replicate' filters.\n"
            "Supports Ctrl+C/V (copy/paste), Ctrl+D (fill down), Delete (clear). Select multiple cells with Shift+Click or Click+Drag."
        )
        instructions.setStyleSheet(StyleSheet.get_label_style())
        instructions.setWordWrap(True)
        grouping_table_layout.addWidget(instructions)

        self.grouping_table = ExcelLikeTableWidget()
        self.grouping_table.set_readonly_columns([0])  # File path column is read-only
        StyleSheet.apply_table_styling(self.grouping_table)
        self.grouping_table.setColumnCount(3)
        self.grouping_table.setHorizontalHeaderLabels(["File Path", "Group", "Replicate"])
        
        header = self.grouping_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 150)
        header.resizeSection(2, 100)
        
        self.grouping_table.setMaximumHeight(200)
        grouping_table_layout.addWidget(self.grouping_table)
        
        populate_btn = QPushButton("Populate from Loaded Data")
        populate_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        populate_btn.clicked.connect(self._populate_file_grouping_table)
        grouping_table_layout.addWidget(populate_btn)
        
        filter_layout.addWidget(grouping_table_group)
        
        filter_group.setLayout(filter_layout)
        return filter_group
        
    
    def _on_filter_mode_combo_changed(self, index):
        """Handle filter mode dropdown change"""
        if index == 0:  # No Filtering
            self.topN_spin.setEnabled(False)
            self.groupby_group_checkbox.setEnabled(False)
            self.groupby_replicate_checkbox.setEnabled(False)
            self.groupby_group_checkbox.setChecked(False)
            self.groupby_replicate_checkbox.setChecked(False)
        else:  # Filtering by unique peptides or modified peptides
            self.topN_spin.setEnabled(True)
            self.groupby_group_checkbox.setEnabled(True)
            self.groupby_replicate_checkbox.setEnabled(True)
    
    def _on_grouping_changed(self, grouping_mode, checked):
        """Handle grouping mode change (mutually exclusive)"""
        if not checked:
            return
        
        # Uncheck other grouping modes
        if grouping_mode == "none":
            self.groupby_file_checkbox.setChecked(False)
            self.groupby_group_checkbox.setChecked(False)
            self.groupby_replicate_checkbox.setChecked(False)
        elif grouping_mode == "file":
            self.no_grouping_checkbox.setChecked(False)
            self.groupby_group_checkbox.setChecked(False)
            self.groupby_replicate_checkbox.setChecked(False)
        elif grouping_mode == "group":
            self.no_grouping_checkbox.setChecked(False)
            self.groupby_file_checkbox.setChecked(False)
            self.groupby_replicate_checkbox.setChecked(False)
        elif grouping_mode == "replicate":
            self.no_grouping_checkbox.setChecked(False)
            self.groupby_file_checkbox.setChecked(False)
            self.groupby_group_checkbox.setChecked(False)
        
    def _on_topn_enabled_changed(self, checked):
        """Handle Top N checkbox change"""
        self.topN_spin.setEnabled(checked)
        
    def _on_filter_mode_changed(self, mode, checked):
        """Handle filter mode change (mutually exclusive)"""
        if not checked:
            return
        
        # Uncheck other filter modes
        if mode == "none":
            self.unique_pep_checkbox.setChecked(False)
            self.unique_mod_checkbox.setChecked(False)
            self.enable_topn_checkbox.setEnabled(False)
            self.enable_topn_checkbox.setChecked(False)
            self.topN_spin.setEnabled(False)
            # Disable grouping options
            self.no_grouping_checkbox.setEnabled(False)
            self.groupby_file_checkbox.setEnabled(False)
            self.groupby_group_checkbox.setEnabled(False)
            self.groupby_replicate_checkbox.setEnabled(False)
        elif mode == "peptide":
            self.no_filter_checkbox.setChecked(False)
            self.unique_mod_checkbox.setChecked(False)
            self.enable_topn_checkbox.setEnabled(True)
            # Enable grouping options
            self.no_grouping_checkbox.setEnabled(True)
            self.groupby_file_checkbox.setEnabled(True)
            self.groupby_group_checkbox.setEnabled(True)
            self.groupby_replicate_checkbox.setEnabled(True)
        elif mode == "modified":
            self.no_filter_checkbox.setChecked(False)
            self.unique_pep_checkbox.setChecked(False)
            self.enable_topn_checkbox.setEnabled(True)
            # Enable grouping options
            self.no_grouping_checkbox.setEnabled(True)
            self.groupby_file_checkbox.setEnabled(True)
            self.groupby_group_checkbox.setEnabled(True)
            self.groupby_replicate_checkbox.setEnabled(True)
    
    def _create_decoy_detection_group(self):
        """Create decoy detection group"""
        decoy_group = QGroupBox("Decoy Detection (Optional)")
        decoy_group.setStyleSheet(EditorConstants.get_groupbox_style())
        decoy_layout = QHBoxLayout()
        
        self.enable_decoy_detection = QCheckBox("Enable Decoy Detection")
        self.enable_decoy_detection.setStyleSheet(EditorConstants.get_checkbox_style())
        decoy_layout.addWidget(self.enable_decoy_detection)
        
        decoy_label = QLabel("Decoy String:")
        decoy_label.setStyleSheet(StyleSheet.get_label_style())
        decoy_layout.addWidget(decoy_label)
        
        self.decoy_string_input = QLineEdit()
        self.decoy_string_input.setStyleSheet(EditorConstants.get_lineedit_style())
        self.decoy_string_input.setPlaceholderText("e.g., rev_, DECOY_, ##")
        self.decoy_string_input.setToolTip("String that identifies decoy proteins")
        decoy_layout.addWidget(self.decoy_string_input)
        
        info_label = QLabel("Will add PSM_Type column (Target/Decoy)")
        info_label.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        decoy_layout.addWidget(info_label)
        
        self.enable_decoy_detection.stateChanged.connect(
            lambda state: self.decoy_string_input.setEnabled(state == Qt.CheckState.Checked.value)
        )
        self.decoy_string_input.setEnabled(False)
        
        decoy_group.setLayout(decoy_layout)
        return decoy_group

    def _create_migration_tracking_group(self):
        """Create hydrogen migration tracking group"""
        migration_group = QGroupBox("Hydrogen Migration Tracking (Optional)")
        migration_group.setStyleSheet(EditorConstants.get_groupbox_style())
        migration_layout = QVBoxLayout()

        info = QLabel(
            "Track hydrogen migration by computing isotope -1 / isotope 0 intensity ratios "
            "at each bond position. Requires z+1 ions (for z migration) or c ions "
            "(for c migration) to be selected in the Annotation tab."
        )
        info.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        info.setWordWrap(True)
        migration_layout.addWidget(info)

        self.enable_z_migration = QCheckBox("Track z+1 migration (isotope 0 / isotope -1)")
        self.enable_z_migration.setStyleSheet(EditorConstants.get_checkbox_style())
        self.enable_z_migration.setToolTip(
            "Compute isotope 0 / isotope -1 ratio for z+1 ions at each backbone position"
        )
        migration_layout.addWidget(self.enable_z_migration)

        self.enable_c_migration = QCheckBox("Track c migration (isotope -1 / isotope 0)")
        self.enable_c_migration.setStyleSheet(EditorConstants.get_checkbox_style())
        self.enable_c_migration.setToolTip(
            "Compute isotope -1 / isotope 0 ratio for c ions at each backbone position"
        )
        migration_layout.addWidget(self.enable_c_migration)

        # Charge range
        charge_range_container = QWidget()
        charge_range_layout = QHBoxLayout(charge_range_container)
        charge_range_layout.setContentsMargins(20, 5, 0, 0)

        charge_label = QLabel("Charge range:")
        charge_label.setStyleSheet(StyleSheet.get_label_style())
        charge_range_layout.addWidget(charge_label)

        self.migration_min_charge = QSpinBox()
        self.migration_min_charge.setStyleSheet(EditorConstants.get_spinbox_style())
        self.migration_min_charge.setRange(1, 10)
        self.migration_min_charge.setValue(1)
        self.migration_min_charge.setEnabled(False)
        charge_range_layout.addWidget(self.migration_min_charge)

        to_label = QLabel("to")
        to_label.setStyleSheet(StyleSheet.get_label_style())
        charge_range_layout.addWidget(to_label)

        self.migration_max_charge = QSpinBox()
        self.migration_max_charge.setStyleSheet(EditorConstants.get_spinbox_style())
        self.migration_max_charge.setRange(1, 10)
        self.migration_max_charge.setValue(3)
        self.migration_max_charge.setEnabled(False)
        charge_range_layout.addWidget(self.migration_max_charge)

        charge_range_layout.addStretch()
        migration_layout.addWidget(charge_range_container)

        def on_migration_toggle(state):
            enabled = (
                self.enable_z_migration.isChecked() or
                self.enable_c_migration.isChecked()
            )
            self.migration_min_charge.setEnabled(enabled)
            self.migration_max_charge.setEnabled(enabled)

        self.enable_z_migration.stateChanged.connect(on_migration_toggle)
        self.enable_c_migration.stateChanged.connect(on_migration_toggle)

        migration_group.setLayout(migration_layout)
        return migration_group

    def _get_display_paths(self, file_paths):
        """
        Remove common prefix from file paths for cleaner display.
        Returns a dict mapping full path to display path.
        """
        if len(file_paths) == 0:
            return {}

        if len(file_paths) == 1:
            # Single file - show basename
            return {file_paths[0]: os.path.basename(file_paths[0])}

        # Find common prefix across all paths
        # Normalize paths to use forward slashes for consistent comparison
        normalized_paths = [fp.replace('\\', '/') for fp in file_paths]

        # Find common prefix
        common_prefix = os.path.commonpath([os.path.dirname(fp) for fp in file_paths])

        if not common_prefix:
            # No common path, just show basenames
            return {fp: os.path.basename(fp) for fp in file_paths}

        # Create display paths by removing common prefix
        display_paths = {}
        for fp in file_paths:
            # Get relative path from common prefix
            try:
                rel_path = os.path.relpath(fp, common_prefix)
                # If relative path is just filename, keep it
                # Otherwise show the relative path
                display_paths[fp] = rel_path
            except ValueError:
                # Different drives on Windows, just show basename
                display_paths[fp] = os.path.basename(fp)

        return display_paths

    def _populate_file_grouping_table(self):
        """Populate file grouping table from loaded data"""
        if not hasattr(self.parent.experiment_data_manager, 'merged_df'):
            UIHelpers.show_validation_error(
                self.parent,
                "No Data",
                "Please load and prepare data first (Data > Prepare data)"
            )
            return

        merged_df = self.parent.experiment_data_manager.merged_df
        if merged_df is None or len(merged_df) == 0:
            UIHelpers.show_validation_error(
                self.parent,
                "No Data",
                "No data available. Please load and prepare data first."
            )
            return

        unique_files = merged_df['spectrum_file_path'].unique()
        self.grouping_table.setRowCount(len(unique_files))

        # Get display paths with common prefix removed
        display_paths = self._get_display_paths(unique_files)

        for i, file_path in enumerate(unique_files):
            # File path (read-only) - show shortened path but store full path
            display_path = display_paths.get(file_path, file_path)
            file_item = QTableWidgetItem(display_path)
            file_item.setFlags(file_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            # Store full path in UserRole for later retrieval
            file_item.setData(Qt.ItemDataRole.UserRole, file_path)
            # Set full path as tooltip
            file_item.setToolTip(file_path)
            self.grouping_table.setItem(i, 0, file_item)

            # Group (editable)
            group_item = QTableWidgetItem("")
            self.grouping_table.setItem(i, 1, group_item)

            # Replicate (editable)
            replicate_item = QTableWidgetItem("1")
            self.grouping_table.setItem(i, 2, replicate_item)
    
    def load_existing_rescoring(self, rescored_df):
        """Load existing rescoring data from experiment file"""
        try:
            # Store the data
            self.current_results_df = rescored_df
            
            # Load into results viewer
            self.results_viewer.load_results_dataframe(rescored_df)

            print(f"[DEBUG] Loaded existing rescoring results: {len(rescored_df)} PSMs")
            
        except Exception as e:
            print(f"[ERROR] Failed to load existing rescoring: {e}")
    
    def run_rescoring(self):
        """Run the rescoring process - UPDATED with save prompt"""
        # Validate data availability
        if self.parent.experiment_data_manager.merged_df is None or len(self.parent.experiment_data_manager.merged_df) == 0:
            UIHelpers.show_validation_error(
                self.parent,
                "No Data",
                "No prepared data found. Please prepare data first by loading search files and running 'Prepare data'."
            )
            return
        
        selected_ions = IonCollectionUtils.collect_selected_ions(
            self.parent.normal_ion_checkboxes,
            self.parent.neutral_ion_checkboxes
        )
        
        selected_internal_ions = IonCollectionUtils.collect_selected_internal_ions(
            self.parent.internal_ion_checkboxes
        )
        
        # Validate ion selection
        if not selected_ions and not selected_internal_ions:
            UIHelpers.show_validation_error(
                self.parent,
                "No Ion Types Selected",
                "Please select at least one ion type from the 'Ion Type Selection' panel."
            )
            return
        
        # Store in parent for access by other methods
        self.parent.selected_ions = selected_ions
        self.parent.selected_internal_ions = selected_internal_ions

        # Validate migration tracking ion requirements
        if self.enable_z_migration.isChecked() and 'z+1' not in selected_ions:
            UIHelpers.show_validation_error(
                self.parent,
                "Ion Type Required",
                "z+1 migration tracking requires the z+1 ion type to be selected "
                "in the Annotation tab."
            )
            return

        if self.enable_c_migration.isChecked() and 'c' not in selected_ions:
            UIHelpers.show_validation_error(
                self.parent,
                "Ion Type Required",
                "c migration tracking requires the c ion type to be selected "
                "in the Annotation tab."
            )
            return

        # Check if experiment already has rescoring data
        experiment_manager = self.parent.experiment_data_manager
        if experiment_manager.has_existing_rescoring():
            rescoring_info = experiment_manager.get_rescoring_info()
            
            overwrite_msg = f"""This experiment already has rescoring results:

    Rescored Date: {rescoring_info['rescored_date'][:19]}
    PSMs: {rescoring_info['psm_count']}

    Running rescoring again will replace the existing results.
    Would you like to continue?"""
            
            reply = QMessageBox.question(
                self.parent,
                "Existing Rescoring Found",
                overwrite_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Get rescoring options
        options = self._get_rescoring_options()
        
        # Show confirmation dialog with filter settings
        filter_info = self._get_filter_summary()
        ion_info = self._get_ion_summary()
        
        confirm_msg = f"""Ready to run rescoring with the following settings:

    {filter_info}

    {ion_info}

    Processing Parameters:
    • CPU Cores: {options['cores']}

    Do you want to proceed?"""
        
        reply = QMessageBox.question(
            self.parent,
            "Confirm Rescoring",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Disable run button during processing
        self.run_button.setEnabled(False)
        
        # CHANGED: Use consistent progress dialog style from UIHelpers
        self.progress = UIHelpers.create_progress_dialog(
            parent=self.parent,
            title="Rescoring Progress",
            text="Initializing rescoring...",
            maximum=100,
            cancelable=True
        )
        self.progress.show()
        
        try:
            original_merged_df = self.parent.experiment_data_manager.merged_df.copy()
            
            print(f"[RESCORING] Starting with original dataframe: {len(original_merged_df)} PSMs")
            
            # Get grouping data from table
            grouping_data = self._get_file_grouping_data()
            
            # Get decoy detection settings
            decoy_settings = self._get_decoy_settings()
            
            # Get extracted spectral data cache
            extracted_spectral_data = self.parent.experiment_data_manager.extracted_spectral_data
            if not extracted_spectral_data:
                UIHelpers.show_validation_error(
                    self.parent,
                    "Missing Spectral Data",
                    "No extracted spectral data found. Please run 'Prepare data' first."
                )
                self.run_button.setEnabled(True)
                self.progress.close()
                return
            
            print(f"[RESCORING] Using spectral cache with {len(extracted_spectral_data)} spectra")
            
            # Create worker thread with ORIGINAL dataframe
            self.worker = RescoringWorker(
                merged_df=original_merged_df,  # CHANGED: Use original dataframe
                options=options,
                custom_ion_series=self.parent.selected_custom_ions_data,
                diagnostic_ions=self.parent.selected_diagnostic_ions_data,
                selected_ions=selected_ions,  # Use collected ions
                selected_internal_ions=selected_internal_ions,  # Use collected internal ions
                grouping_data=grouping_data,
                decoy_settings=decoy_settings,
                max_neutral_losses=self.parent.max_neutral_losses_input.value(),
                extracted_spectral_data=extracted_spectral_data,
                scoring_methods=getattr(self.parent, 'scoring_methods', None),
                central_mod_db=getattr(self.parent, 'central_mod_db', None),
                enable_labile=getattr(self.parent, 'enable_labile_losses_cb', None)
                    and self.parent.enable_labile_losses_cb.isChecked(),
                enable_remainder=getattr(self.parent, 'enable_remainder_ions_cb', None)
                    and self.parent.enable_remainder_ions_cb.isChecked(),
                enable_mod_nl=getattr(self.parent, 'enable_mod_nl_cb', None)
                    and self.parent.enable_mod_nl_cb.isChecked(),
            )
            
            # Connect signals
            self.worker.progress_update.connect(self._on_progress_update)
            self.worker.rescoring_complete.connect(self._on_rescoring_complete)
            self.worker.rescoring_error.connect(self._on_rescoring_error)
            
            # Connect progress cancel
            self.progress.canceled.connect(self.worker.terminate)
            
            # Start worker
            self.worker.start()
            
        except Exception as e:
            self.run_button.setEnabled(True)
            if hasattr(self, 'progress'):
                self.progress.close()
            UIHelpers.show_validation_error(
                self.parent,
                "Rescoring Error",
                f"Failed to start rescoring: {str(e)}"
            )
            
    def _get_filter_summary(self):
        """Get summary of current filter settings"""
        filter_lines = ["Filtering Options:"]
        
        filter_mode_index = self.filter_mode_combo.currentIndex()
        
        if filter_mode_index == 0:
            filter_lines.append("• No filtering - all PSMs will be rescored")
        elif filter_mode_index == 1:
            filter_lines.append(f"• Top {self.topN_spin.value()} per unique peptide")
        elif filter_mode_index == 2:
            filter_lines.append(f"• Top {self.topN_spin.value()} per unique modified peptide")
        
        # Grouping information
        grouping_parts = []
        if self.groupby_group_checkbox.isChecked():
            grouping_parts.append("Group")
        if self.groupby_replicate_checkbox.isChecked():
            grouping_parts.append("Replicate")
        
        if grouping_parts:
            filter_lines.append(f"• Applied per: {' and '.join(grouping_parts)}")
        else:
            filter_lines.append("• Applied to entire dataset (no grouping)")
        
        return "\n".join(filter_lines)

    def _get_ion_summary(self):
        """Get summary of selected ion types"""
        ion_lines = ["Ion Types Selected:"]
        
        # Collect ions
        selected_ions = IonCollectionUtils.collect_selected_ions(
            self.parent.normal_ion_checkboxes,
            self.parent.neutral_ion_checkboxes
        )
        
        selected_internal_ions = IonCollectionUtils.collect_selected_internal_ions(
            self.parent.internal_ion_checkboxes
        )
        
        # Basic ions (separate by normal and neutral loss)
        basic_ions = [ion for ion, cb in self.parent.normal_ion_checkboxes.items() if cb.isChecked()]
        if basic_ions:
            ion_lines.append(f"• Basic: {', '.join(basic_ions)}")
        
        # Neutral loss ions
        nl_ions = [ion for ion, cb in self.parent.neutral_ion_checkboxes.items() if cb.isChecked()]
        if nl_ions:
            ion_lines.append(f"• Neutral Loss: {', '.join(nl_ions)}")
        
        # Internal ions
        if selected_internal_ions:
            internal_display = [ion.replace('int-', '') for ion in selected_internal_ions]
            ion_lines.append(f"• Internal: {', '.join(internal_display)}")
        
        # Custom ions
        if hasattr(self.parent, 'selected_custom_ions_data') and self.parent.selected_custom_ions_data:
            custom_count = len(self.parent.selected_custom_ions_data)
            ion_lines.append(f"• Custom Series: {custom_count} series")
        
        # Diagnostic ions
        if hasattr(self.parent, 'selected_diagnostic_ions_data') and self.parent.selected_diagnostic_ions_data:
            diag_count = len(self.parent.selected_diagnostic_ions_data)
            ion_lines.append(f"• Diagnostic Ions: {diag_count} ions")

        # Migration tracking
        if hasattr(self, 'enable_z_migration') and self.enable_z_migration.isChecked():
            ion_lines.append(f"• z+1 Migration Tracking: charges {self.migration_min_charge.value()}-{self.migration_max_charge.value()}")
        if hasattr(self, 'enable_c_migration') and self.enable_c_migration.isChecked():
            ion_lines.append(f"• c Migration Tracking: charges {self.migration_min_charge.value()}-{self.migration_max_charge.value()}")

        return "\n".join(ion_lines)
                
    def _on_progress_update(self, value, message):
        """Handle progress updates from worker"""
        if hasattr(self, 'progress'):
            self.progress.setValue(value)
            self.progress.setLabelText(message)
    
    def _on_rescoring_complete(self, results_df):
        """Handle rescoring completion - UPDATED with save prompt"""
        if hasattr(self, 'progress'):
            self.progress.close()
        
        # Store results
        self.current_results_df = results_df
        
        # Also store the full debug dataframe if available
        if hasattr(self.worker, 'debug_df'):
            self.debug_df = self.worker.debug_df
            self.debug_export_button.setEnabled(True)  # Enable debug export
            print(f"[DEBUG] Debug dataframe stored with {len(self.debug_df)} rows")

        # Store ion configuration for fragment export
        self.ion_config = {
            'selected_ions': list(self.worker.selected_ions),
            'selected_internal_ions': list(self.worker.selected_internal_ions),
            'custom_ion_series': list(self.worker.custom_ion_series) if self.worker.custom_ion_series else [],
            'diagnostic_ions': list(self.worker.diagnostic_ions) if self.worker.diagnostic_ions else [],
            'has_mod_nl': self.worker.central_mod_db is not None,
            'mod_nl_subtypes': getattr(self.worker, 'mod_nl_subtypes', []),
        }

        # Load results into viewer
        self.results_viewer.load_results_dataframe(results_df)

        # Pass fragment export data to viewer
        if hasattr(self, 'debug_df') and self.debug_df is not None:
            self.results_viewer.set_fragment_export_data(self.debug_df, self.ion_config)

        # Re-enable run button
        self.run_button.setEnabled(True)
        
        # Show success message
        success_msg = f"Rescoring completed successfully!\n{len(results_df)} PSMs processed."
        
        if 'PSM_Type' in results_df.columns:
            decoy_count = (results_df['PSM_Type'] == 'Decoy').sum()
            target_count = (results_df['PSM_Type'] == 'Target').sum()
            success_msg += f"\n\nTarget PSMs: {target_count}"
            success_msg += f"\nDecoy PSMs: {decoy_count}"
        
        UIHelpers.show_success_message(self.parent, success_msg)
        
        # Prompt to save rescoring to experiment file
        self._prompt_save_rescoring_to_experiment(results_df)

    
    
    def _prompt_save_rescoring_to_experiment(self, results_df):
        """Prompt user to save rescoring results to experiment file"""
        experiment_manager = self.parent.experiment_data_manager
        
        # Check if we have a valid experiment to save to
        if experiment_manager.merged_df is None or len(experiment_manager.merged_df) == 0:
            # No experiment loaded, offer to create new one
            reply = QMessageBox.question(
                self.parent,
                "Save Rescoring Results",
                "Would you like to save these rescoring results as a new experiment file?\n\n"
                "This will allow you to reload both the PSM data and rescoring results later.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Gather rescoring settings for metadata
                rescoring_settings = {
                    'options': self._get_rescoring_options(),
                    'ion_settings': self._get_current_ion_settings_summary(),
                    'decoy_settings': self._get_decoy_settings()
                }
                
                # Store rescoring data in experiment manager
                experiment_manager.save_rescoring_to_experiment(results_df, rescoring_settings)
                
                # Trigger save experiment dialog
                experiment_manager.save_experiment()
        else:
            # Experiment already loaded
            is_overwrite = experiment_manager.has_existing_rescoring()
            
            if is_overwrite:
                prompt_msg = """Update experiment file with new rescoring results?

    This will replace the previous rescoring data in the experiment file.

    Note: The original PSM data will remain unchanged."""
            else:
                prompt_msg = """Save rescoring results to the current experiment file?

    This will add the rescoring data to your experiment, allowing you to:
    • Reload rescoring results when opening this experiment
    • Compare original and rescored data
    • Export both datasets

    Note: The original PSM data will remain unchanged."""
            
            reply = QMessageBox.question(
                self.parent,
                "Update Experiment File" if is_overwrite else "Save Rescoring to Experiment",
                prompt_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Gather rescoring settings for metadata
                rescoring_settings = {
                    'options': self._get_rescoring_options(),
                    'ion_settings': self._get_current_ion_settings_summary(),
                    'decoy_settings': self._get_decoy_settings()
                }
                
                # Store rescoring data in experiment manager
                experiment_manager.save_rescoring_to_experiment(results_df, rescoring_settings)
                
                # Trigger save experiment dialog (will use existing path or prompt for new one)
                experiment_manager.save_experiment()
    
    
    def _get_current_ion_settings_summary(self):
        """Get summary of current ion settings as dictionary"""
        return {
            'basic_ions': [ion for ion, cb in self.parent.normal_ion_checkboxes.items() if cb.isChecked()],
            'neutral_loss_ions': [ion for ion, cb in self.parent.neutral_ion_checkboxes.items() if cb.isChecked()],
            'internal_ions': [ion for ion, cb in self.parent.internal_ion_checkboxes.items() if cb.isChecked()],
            'custom_ion_series': [ion.get('Series Name', '') for ion in self.parent.selected_custom_ions_data],
            'diagnostic_ions': [ion.get('Name', '') for ion in self.parent.selected_diagnostic_ions_data],
            'ppm_tolerance': self.parent.ppm_tolerance_input.value(),
            'max_neutral_losses': self.parent.max_neutral_losses_input.value()
        }
        
    def _on_rescoring_error(self, error_message):
        """Handle rescoring error"""
        if hasattr(self, 'progress'):
            self.progress.close()
        
        # Re-enable run button
        self.run_button.setEnabled(True)
        
        UIHelpers.show_validation_error(
            self.parent,
            "Rescoring Error",
            f"Error during rescoring: {error_message}"
        )
    
    def _get_rescoring_options(self):
        """Get rescoring options from UI"""
        ppm_tolerance = self.parent.ppm_tolerance_input.value()
        
        # Determine filter mode from dropdown
        filter_mode_index = self.filter_mode_combo.currentIndex()
        unique_pep = (filter_mode_index == 1)  # Filter by Unique Peptides
        unique_mod = (filter_mode_index == 2)  # Filter by Unique Modified Peptides
        
        # Top N is always the value from spin box (only used if filtering is enabled)
        topn = self.topN_spin.value() if filter_mode_index > 0 else 999999
        
        # Build grouping column list (can have both Group and Replicate)
        groupby_columns = []
        if self.groupby_group_checkbox.isChecked():
            groupby_columns.append('Group')
        if self.groupby_replicate_checkbox.isChecked():
            groupby_columns.append('Replicate')
        
        # If both are selected, create hierarchical grouping
        if len(groupby_columns) == 2:
            groupby_column = groupby_columns  # Pass as list for hierarchical grouping
        elif len(groupby_columns) == 1:
            groupby_column = groupby_columns[0]  # Single column
        else:
            groupby_column = None  # No grouping
        
        return {
            "topN": topn,
            "unique_pep": unique_pep,
            "unique_mod": unique_mod,
            "groupby_column": groupby_column,
            "cores": self.cores_spin.value(),
            "ppm_tolerance": ppm_tolerance,
            "calculate_isotopes": self.calculate_isotopes_checkbox.isChecked(),
            "scoring_max_charge": self.scoring_max_charge_spin.value(),
            "migration_settings": {
                "z_migration_enabled": self.enable_z_migration.isChecked(),
                "c_migration_enabled": self.enable_c_migration.isChecked(),
                "min_charge": self.migration_min_charge.value(),
                "max_charge": self.migration_max_charge.value(),
            }
        }
    
    def _get_file_grouping_data(self):
        """Extract file grouping data from table"""
        grouping_data = {}

        for i in range(self.grouping_table.rowCount()):
            file_item = self.grouping_table.item(i, 0)
            group_item = self.grouping_table.item(i, 1)
            replicate_item = self.grouping_table.item(i, 2)

            if file_item:
                # Get full path from UserRole (not displayed text)
                file_path = file_item.data(Qt.ItemDataRole.UserRole)
                if file_path is None:
                    # Fallback to text if UserRole not set (shouldn't happen)
                    file_path = file_item.text()

                group = group_item.text().strip() if group_item else "Ungrouped"
                replicate = replicate_item.text().strip() if replicate_item else "1"

                grouping_data[file_path] = {
                    "Group": group if group else "Ungrouped",
                    "Replicate": replicate if replicate else "1"
                }

        return grouping_data
    
    def _get_decoy_settings(self):
        """Get decoy detection settings"""
        return {
            "enabled": self.enable_decoy_detection.isChecked(),
            "decoy_string": self.decoy_string_input.text().strip()
        }
        
        
    def export_debug_data(self):
        """Export full debug dataframe with all intermediate columns"""
        if not hasattr(self, 'debug_df') or self.debug_df is None:
            UIHelpers.show_validation_error(
                self.parent,
                "No Debug Data",
                "No debug data available. Please run rescoring first."
            )
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Export Debug Data",
            "rescoring_debug_full.csv",
            "CSV Files (*.csv);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # Export with ALL columns
                self.debug_df.to_csv(file_path, index=False)
                
                # Create summary file
                summary_path = file_path.replace('.csv', '_summary.txt')
                with open(summary_path, 'w') as f:
                    f.write("=== RESCORING DEBUG SUMMARY ===\n\n")
                    
                    # Overall stats
                    f.write(f"Total PSMs: {len(self.debug_df)}\n")
                    f.write(f"Columns: {', '.join(self.debug_df.columns)}\n\n")
                    
                    # Zero rescore analysis
                    zero_rescore = self.debug_df[self.debug_df['Rescore'] == 0.0]
                    f.write(f"PSMs with zero rescore: {len(zero_rescore)} ({len(zero_rescore)/len(self.debug_df)*100:.1f}%)\n\n")
                    
                    if len(zero_rescore) > 0:
                        f.write("=== ZERO RESCORE DETAILS ===\n\n")
                        
                        # Check for missing theoretical fragments
                        missing_theoretical = zero_rescore[
                            zero_rescore['Theoretical_Fragments'].apply(lambda x: x is None or len(x) == 0)
                        ]
                        f.write(f"Missing theoretical fragments: {len(missing_theoretical)}\n")
                        
                        # Check for missing matched fragments
                        missing_matched = zero_rescore[
                            zero_rescore['matched_fragments'].apply(lambda x: x is None or len(x) == 0)
                        ]
                        f.write(f"Missing matched fragments: {len(missing_matched)}\n")
                        
                        # Check for missing spectral data
                        missing_mz = zero_rescore[zero_rescore['mz'].apply(lambda x: x is None or len(x) == 0)]
                        f.write(f"Missing m/z values: {len(missing_mz)}\n")
                        
                        missing_intensity = zero_rescore[
                            zero_rescore['intensity'].apply(lambda x: x is None or len(x) == 0)
                        ]
                        f.write(f"Missing intensity values: {len(missing_intensity)}\n\n")
                        
                        # Sample peptides with zero rescore
                        f.write("=== SAMPLE PEPTIDES WITH ZERO RESCORE ===\n\n")
                        for idx, row in zero_rescore.head(10).iterrows():
                            f.write(f"Row {idx}:\n")
                            f.write(f"  Peptide: {row.get('Peptide', 'N/A')}\n")
                            f.write(f"  Modified: {row.get('Modified Peptide', 'N/A')}\n")
                            f.write(f"  Charge: {row.get('Charge', 'N/A')}\n")
                            f.write(f"  File: {row.get('spectrum_file_path', 'N/A')}\n")
                            f.write(f"  Scan: {row.get('index', 'N/A')}\n")
                            
                            # Check theoretical fragments
                            theoretical = row.get('Theoretical_Fragments', [])
                            if theoretical:
                                f.write(f"  Theoretical fragments: {len(theoretical)}\n")
                            else:
                                f.write(f"  Theoretical fragments: NONE\n")
                            
                            # Check matched fragments
                            matched = row.get('matched_fragments', [])
                            if matched:
                                f.write(f"  Matched fragments: {len(matched)}\n")
                                # Count actual matches (not "No Match")
                                if isinstance(matched, list):
                                    actual_matches = sum(1 for m in matched if len(m) > 2 and m[2] != "No Match")
                                    f.write(f"  Actual matches (not 'No Match'): {actual_matches}\n")
                            else:
                                f.write(f"  Matched fragments: NONE\n")
                            
                            # Check spectral data
                            mz = row.get('mz', [])
                            intensity = row.get('intensity', [])
                            f.write(f"  Experimental peaks: {len(mz) if mz else 0}\n")
                            f.write(f"  Hyperscore: {row.get('Hyperscore', 'N/A')}\n")
                            f.write(f"  Annotated TIC %: {row.get('Annotated_TIC_%', 'N/A')}\n")
                            f.write("\n")
                    
                    # Score distribution
                    f.write("=== SCORE DISTRIBUTION ===\n\n")
                    f.write(f"Rescore Mean: {self.debug_df['Rescore'].mean():.3f}\n")
                    f.write(f"Rescore Median: {self.debug_df['Rescore'].median():.3f}\n")
                    f.write(f"Rescore Std: {self.debug_df['Rescore'].std():.3f}\n")
                    f.write(f"Rescore Min: {self.debug_df['Rescore'].min():.3f}\n")
                    f.write(f"Rescore Max: {self.debug_df['Rescore'].max():.3f}\n\n")
                    
                    # Ion count statistics
                    f.write("=== ION COUNT STATISTICS ===\n\n")
                    for col in self.debug_df.columns:
                        if col.endswith('_unique_count'):
                            ion_type = col.replace('_unique_count', '')
                            f.write(f"{ion_type.upper()} ions:\n")
                            f.write(f"  Mean: {self.debug_df[col].mean():.2f}\n")
                            f.write(f"  Median: {self.debug_df[col].median():.2f}\n")
                            f.write(f"  Max: {self.debug_df[col].max():.0f}\n\n")
                
                success_msg = f"""Debug data exported successfully!

    Data file: {file_path}
    Summary file: {summary_path}

    The full CSV contains all intermediate columns including:
    • Theoretical_Fragments
    • matched_fragments  
    • mz, intensity (spectral data)
    • Ion counts per type
    • All score columns

    Check the summary file for zero rescore analysis."""
                
                UIHelpers.show_success_message(self.parent, success_msg)
                
            except Exception as e:
                import traceback
                UIHelpers.show_validation_error(
                    self.parent,
                    "Export Error",
                    f"Failed to export debug data:\n{str(e)}\n\n{traceback.format_exc()}"
                )
                
                
    def _update_preview(self):
        """Update the preview with current filter settings"""
        # Check if data is loaded
        if not hasattr(self.parent.experiment_data_manager, 'merged_df') or self.parent.experiment_data_manager.merged_df is None:
            UIHelpers.show_validation_error(
                self.parent,
                "No Data",
                "Please load and prepare data first (Data > Prepare data)"
            )
            return
        
        try:
            # Get original dataframe
            original_df = self.parent.experiment_data_manager.merged_df.copy()
            
            # Add grouping information if needed
            grouping_data = self._get_file_grouping_data()
            if grouping_data:
                original_df['Group'] = original_df['spectrum_file_path'].map(
                    lambda x: grouping_data.get(x, {}).get('Group', 'Ungrouped')
                )
                original_df['Replicate'] = original_df['spectrum_file_path'].map(
                    lambda x: grouping_data.get(x, {}).get('Replicate', '1')
                )
            
            # Apply filters
            filtered_df = self._apply_preview_filters(original_df)
            
            # Calculate and display statistics
            self._display_preview_statistics(original_df, filtered_df)
            
            # Show sample data
            self._display_preview_sample(filtered_df)
            
        except Exception as e:
            import traceback
            UIHelpers.show_validation_error(
                self.parent,
                "Preview Error",
                f"Error generating preview:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def _apply_preview_filters(self, df):
        """Apply current filter settings to dataframe for preview"""
    
        
        # Determine filter settings from dropdown
        filter_mode_index = self.filter_mode_combo.currentIndex()
        unique_pep = (filter_mode_index == 1)
        unique_mod = (filter_mode_index == 2)
        topn = self.topN_spin.value() if filter_mode_index > 0 else 999999
        
        # Determine grouping (can be both)
        groupby_columns = []
        if self.groupby_group_checkbox.isChecked():
            groupby_columns.append('Group')
        if self.groupby_replicate_checkbox.isChecked():
            groupby_columns.append('Replicate')
        
        # Build groupby parameter
        if len(groupby_columns) == 2:
            groupby_column = groupby_columns  # Hierarchical grouping
        elif len(groupby_columns) == 1:
            groupby_column = groupby_columns[0]
        else:
            groupby_column = None
        
        # If no filtering, return original
        if filter_mode_index == 0:
            return df
        
        # Apply filtering
        filtered_df = DataProcessingUtils.filter_dataframe(
            df,
            topN=topn,
            unique_pep=unique_pep,
            unique_mod=unique_mod,
            groupby_column=groupby_column
        )
        
        return filtered_df

    def _display_preview_statistics(self, original_df, filtered_df):
        """Display statistics comparing original and filtered data"""
        # Clear existing stats
        while self.preview_stats_layout.count():
            child = self.preview_stats_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Overall statistics
        overall_stats = QLabel()
        overall_stats.setStyleSheet(StyleSheet.get_label_style())
        overall_stats.setText(f"""<b>Overall Statistics:</b><br>
        Original PSMs: {len(original_df)}<br>
        Filtered PSMs: {len(filtered_df)} ({len(filtered_df)/len(original_df)*100:.1f}%)<br>
        Removed: {len(original_df) - len(filtered_df)} ({(len(original_df)-len(filtered_df))/len(original_df)*100:.1f}%)
        """)
        self.preview_stats_layout.addWidget(overall_stats)
        
        # Unique peptides
        if 'Peptide' in filtered_df.columns:
            peptide_stats = QLabel()
            peptide_stats.setStyleSheet(StyleSheet.get_label_style())
            peptide_stats.setText(f"""<b>Peptide Statistics:</b><br>
            Original Unique Peptides: {original_df['Peptide'].nunique()}<br>
            Filtered Unique Peptides: {filtered_df['Peptide'].nunique()}<br>
            Avg PSMs per Peptide: {len(filtered_df)/filtered_df['Peptide'].nunique():.2f}
            """)
            self.preview_stats_layout.addWidget(peptide_stats)
        
        # Modified peptides
        if 'Modified Peptide' in filtered_df.columns:
            mod_stats = QLabel()
            mod_stats.setStyleSheet(StyleSheet.get_label_style())
            mod_stats.setText(f"""<b>Modified Peptide Statistics:</b><br>
            Original Unique Modified: {original_df['Modified Peptide'].nunique()}<br>
            Filtered Unique Modified: {filtered_df['Modified Peptide'].nunique()}<br>
            Avg PSMs per Modified: {len(filtered_df)/filtered_df['Modified Peptide'].nunique():.2f}
            """)
            self.preview_stats_layout.addWidget(mod_stats)
        
        # Group statistics
        if 'Group' in filtered_df.columns:
            group_stats_text = "<b>Group Statistics:</b><br>"
            for group in sorted(filtered_df['Group'].unique()):
                group_count = len(filtered_df[filtered_df['Group'] == group])
                group_stats_text += f"  {group}: {group_count} PSMs<br>"
            
            group_stats = QLabel()
            group_stats.setStyleSheet(StyleSheet.get_label_style())
            group_stats.setText(group_stats_text)
            self.preview_stats_layout.addWidget(group_stats)
        
        # Replicate statistics
        if 'Replicate' in filtered_df.columns:
            rep_stats_text = "<b>Replicate Statistics:</b><br>"
            for replicate in sorted(filtered_df['Replicate'].unique()):
                rep_count = len(filtered_df[filtered_df['Replicate'] == replicate])
                rep_stats_text += f"  Replicate {replicate}: {rep_count} PSMs<br>"
            
            rep_stats = QLabel()
            rep_stats.setStyleSheet(StyleSheet.get_label_style())
            rep_stats.setText(rep_stats_text)
            self.preview_stats_layout.addWidget(rep_stats)
        
        # File statistics
        if 'spectrum_file_path' in filtered_df.columns:
            file_stats_text = "<b>File Distribution:</b><br>"
            file_counts = filtered_df['spectrum_file_path'].value_counts()
            for file_path, count in file_counts.head(10).items():
                file_name = os.path.basename(file_path)
                file_stats_text += f"  {file_name}: {count} PSMs<br>"
            
            if len(file_counts) > 10:
                file_stats_text += f"  ... and {len(file_counts) - 10} more files<br>"
            
            file_stats = QLabel()
            file_stats.setStyleSheet(StyleSheet.get_label_style())
            file_stats.setText(file_stats_text)
            self.preview_stats_layout.addWidget(file_stats)

    def _display_preview_sample(self, filtered_df):
        """Display sample of filtered data in table"""
        if len(filtered_df) == 0:
            self.preview_table.setRowCount(1)
            self.preview_table.setColumnCount(1)
            self.preview_table.setHorizontalHeaderLabels(["No Data"])
            item = QTableWidgetItem("No data matches current filters")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.preview_table.setItem(0, 0, item)
            return

        # Show first 10 rows
        sample_df = filtered_df.head(10)

        # Select key columns to display
        display_columns = []
        for col in ['Peptide', 'Modified Peptide', 'Charge', 'Hyperscore',
                    'spectrum_file_path', 'Group', 'Replicate']:
            if col in sample_df.columns:
                display_columns.append(col)

        sample_df = sample_df[display_columns]

        # Get display paths for file paths (remove common prefix)
        display_paths = {}
        if 'spectrum_file_path' in display_columns:
            file_paths = sample_df['spectrum_file_path'].unique()
            display_paths = self._get_display_paths(file_paths)

        self.preview_table.setRowCount(len(sample_df))
        self.preview_table.setColumnCount(len(display_columns))
        self.preview_table.setHorizontalHeaderLabels(display_columns)

        for i, (_, row) in enumerate(sample_df.iterrows()):
            for j, value in enumerate(row):
                item = QTableWidgetItem()

                if pd.isna(value):
                    item.setText("")
                elif isinstance(value, (int, np.integer)):
                    item.setData(Qt.ItemDataRole.DisplayRole, int(value))
                elif isinstance(value, (float, np.floating)):
                    item.setData(Qt.ItemDataRole.DisplayRole, float(f"{value:.6f}"))
                else:
                    # For file paths, show shortened path with common prefix removed
                    if display_columns[j] == 'spectrum_file_path':
                        display_path = display_paths.get(str(value), os.path.basename(str(value)))
                        item.setText(display_path)
                        item.setToolTip(str(value))
                    else:
                        item.setText(str(value))

                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.preview_table.setItem(i, j, item)

        # Resize columns
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    
    def update_theme(self, theme_name):
        """Update rescoring tab theme"""
        print(f"[DEBUG] Updating rescoring tab theme to {theme_name}")
        
        # Update ALL QGroupBox widgets with new theme
        if hasattr(self, 'rescoring_tab'):
            # Update all groupboxes
            for groupbox in self.rescoring_tab.findChildren(QGroupBox):
                groupbox.setStyleSheet(EditorConstants.get_groupbox_style())
            
            # Find all QScrollArea children and update their styles
            for widget in self.rescoring_tab.findChildren(QScrollArea):
                widget.setStyleSheet(StyleSheet.get_scrollarea_style())
        
        # Update config widget background (main container)
        if hasattr(self, 'config_widget'):
            self.config_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
            # Force update
            self.config_widget.update()
        
        # Update controls widget background
        if hasattr(self, 'controls_widget'):
            self.controls_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
            # Force update
            self.controls_widget.update()
        
        # Update controls scroll widget background (container for all the groupboxes)
        if hasattr(self, 'controls_scroll_widget'):
            self.controls_scroll_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
            # Force update
            self.controls_scroll_widget.update()
        
        # Update preview widget background
        if hasattr(self, 'preview_widget'):
            self.preview_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
            # Force update
            self.preview_widget.update()
        
        # Update control widgets with proper backgrounds
        if hasattr(self, 'preview_stats_widget'):
            self.preview_stats_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
        
        # Update preview table
        if hasattr(self, 'preview_table'):
            StyleSheet.apply_table_styling(self.preview_table)
        
        # Update results viewer if it exists
        if hasattr(self, 'results_viewer'):
            if hasattr(self.results_viewer, 'update_theme'):
                self.results_viewer.update_theme(theme_name)
        
        print(f"[DEBUG] Rescoring tab theme updated")