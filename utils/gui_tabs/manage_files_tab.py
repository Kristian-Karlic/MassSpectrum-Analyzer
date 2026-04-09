"""
Manage Loaded Files Tab Manager

Provides a UI for viewing and managing the relationship between raw files
and search files. Supports automatic and manual file matching.
"""

import os
from pathlib import Path
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QComboBox, QLabel, QMessageBox, QGroupBox,
    QSizePolicy, QStyledItemDelegate, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush, QAction
from utils.style.style import EditorConstants, StyleSheet
from utils.utilities import FileTypeUtils
from utils.psm_normalizers.byonic_normalizer import ByonicNormalizer


class SearchFileDelegate(QStyledItemDelegate):
    """Custom delegate for search file dropdown cells with Excel-style appearance."""

    def createEditor(self, parent, option, index):
        """Create the dropdown combobox when cell is activated."""
        combo = QComboBox(parent)
        combo.setFixedHeight(20)
        return combo

    def setEditorData(self, editor, index):
        """Populate dropdown with search files."""
        # Get the table widget from the parent
        table = editor.parent()
        while table and not isinstance(table, QTableWidget):
            table = table.parent()

        if not table or not hasattr(table, 'manage_files_manager'):
            return

        manager = table.manage_files_manager
        row = index.row()

        # Get the raw file path from column 0
        raw_item = table.item(row, 0)
        if not raw_item:
            return
        raw_path = raw_item.data(Qt.ItemDataRole.UserRole)

        # Populate dropdown
        editor.addItem("-- Not Matched --", None)

        # Get the list of all search files from the manager
        edm = manager.main_app.experiment_data_manager
        for search_path in edm.search_files:
            search_display = manager._get_partial_path(search_path)
            editor.addItem(search_display, search_path)

        # Set current selection
        if raw_path in manager.file_matches and manager.file_matches[raw_path]:
            matched = manager.file_matches[raw_path]
            idx = editor.findData(matched)
            if idx >= 0:
                editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        """Update model with selected value."""
        selected_path = editor.currentData()

        # Get the table widget to update display
        table = editor.parent()
        while table and not isinstance(table, QTableWidget):
            table = table.parent()

        if table:
            # Update the item with the selected file path
            if selected_path:
                if hasattr(table, 'manage_files_manager'):
                    manager = table.manage_files_manager
                    display_text = manager._get_partial_path(selected_path)
                else:
                    display_text = os.path.basename(selected_path)
            else:
                display_text = "Click here to select file"

            # Update the cell display
            item = table.item(index.row(), index.column())
            if item:
                item.setText(display_text)
                item.setData(Qt.ItemDataRole.UserRole, selected_path)

            # Trigger the data changed handler
            if hasattr(table, 'manage_files_manager'):
                manager = table.manage_files_manager
                manager._on_cell_data_changed(index, index)

    def displayText(self, value, locale):
        """Show placeholder text or selected file name."""
        if value is None or value == "":
            return "Click here to select file"
        if isinstance(value, str) and len(value) > 50:
            return os.path.basename(value)
        return str(value) if value else "Click here to select file"


class ManageFilesTabManager:
    """Manager for the Manage Loaded Files tab.

    Provides functionality to:
    - Load raw and search files via buttons
    - View all loaded raw files with their matched search files
    - Automatically match search files to raw files based on spectrum file names
    - Manually match files via dropdown selection
    - Display validation indicators (green/red/yellow)
    """

    def __init__(self, main_app):
        self.main_app = main_app
        self.file_table = None
        self.status_label = None
        self.tab_widget = None
        # Mapping: raw_file_path -> search_file_path (or None if unmatched)
        self.file_matches = {}

    def setup_manage_files_tab(self):
        """Create and setup the Manage Files tab."""
        self.tab_widget = QWidget()
        layout = QVBoxLayout(self.tab_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ================================================================
        # Load Files Section
        # ================================================================
        load_group = QGroupBox("Load Files")
        load_layout = QHBoxLayout(load_group)
        load_layout.setContentsMargins(10, 10, 10, 10)

        load_raw_btn = QPushButton("Load Raw Data")
        load_raw_btn.clicked.connect(self._on_load_raw_data)
        load_raw_btn.setToolTip("Load .raw or .mzML files")
        load_layout.addWidget(load_raw_btn)

        load_search_btn = QPushButton("Load Search Files")
        load_search_btn.clicked.connect(self._on_load_search_data)
        load_search_btn.setToolTip("Load search result files (MSFragger, MaxQuant, MetaMorpheus, Byonic)")
        load_layout.addWidget(load_search_btn)

        load_folder_btn = QPushButton("Add MSFragger Folder")
        load_folder_btn.clicked.connect(self._on_add_msfragger_folder)
        load_folder_btn.setToolTip("Load all psm.tsv files from an MSFragger search folder")
        load_layout.addWidget(load_folder_btn)

        load_layout.addStretch()
        layout.addWidget(load_group)

        # ================================================================
        # File Matching Section
        # ================================================================
        match_group = QGroupBox("File Matching")
        match_layout = QHBoxLayout(match_group)
        match_layout.setContentsMargins(10, 10, 10, 10)

        auto_match_btn = QPushButton("Auto-Match Files")
        auto_match_btn.clicked.connect(self.auto_match_files)
        auto_match_btn.setToolTip("Automatically match search files to raw files based on spectrum file names")
        match_layout.addWidget(auto_match_btn)

        clear_matches_btn = QPushButton("Clear All Matches")
        clear_matches_btn.clicked.connect(self.clear_matches)
        clear_matches_btn.setToolTip("Clear all file matches")
        match_layout.addWidget(clear_matches_btn)

        clear_raw_btn = QPushButton("Clear All Raw Files")
        clear_raw_btn.clicked.connect(self._clear_all_raw_files)
        clear_raw_btn.setToolTip("Remove all loaded raw files")
        match_layout.addWidget(clear_raw_btn)

        clear_search_btn = QPushButton("Clear All Search Files")
        clear_search_btn.clicked.connect(self._clear_all_search_files)
        clear_search_btn.setToolTip("Remove all loaded search files")
        match_layout.addWidget(clear_search_btn)

        match_layout.addStretch()

        # Status label
        self.status_label = QLabel("No files loaded")
        match_layout.addWidget(self.status_label)

        layout.addWidget(match_group)

        # ================================================================
        # Main File Table
        # ================================================================
        # Info label
        info_label = QLabel(
            "Each row represents a loaded raw file. Select the corresponding search file from the dropdown."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(info_label)

        self.file_table = QTableWidget()
        self._setup_table()
        layout.addWidget(self.file_table, stretch=1)

        # Apply styling
        StyleSheet.apply_table_styling(self.file_table)

        # ================================================================
        # Prepare Data Section
        # ================================================================
        prepare_group = QGroupBox("Data Preparation")
        prepare_layout = QHBoxLayout(prepare_group)
        prepare_layout.setContentsMargins(10, 10, 10, 10)

        prepare_btn = QPushButton("Prepare Data")
        prepare_btn.clicked.connect(self._on_prepare_data)
        prepare_btn.setToolTip("Combine and process all matched PSM files for analysis")
        prepare_btn.setMinimumWidth(150)
        prepare_layout.addWidget(prepare_btn)

        prepare_layout.addStretch()

        prepare_info = QLabel("Combines all matched files and prepares data for analysis")
        prepare_info.setStyleSheet("color: gray; font-style: italic;")
        prepare_layout.addWidget(prepare_info)

        layout.addWidget(prepare_group)

        # Add tab to main widget (will be moved to first position in GUI.py)
        self.main_app.main_tab_widget.addTab(self.tab_widget, "Manage Files")

        return self.tab_widget

    def _setup_table(self):
        """Configure the file table columns and appearance."""
        headers = [
            "Raw File", "Raw Type", "Search File", "Search Type", "Validation"
        ]
        self.file_table.setColumnCount(len(headers))
        self.file_table.setHorizontalHeaderLabels(headers)

        # Set custom delegate for Search File column
        self.file_table.setItemDelegateForColumn(2, SearchFileDelegate())

        # Store reference to manager in table for delegate access
        self.file_table.manage_files_manager = self

        # Column sizing
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Raw File
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Raw Type
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Search File
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Search Type
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Validation

        # Set row height to accommodate dropdown combobox
        self.file_table.verticalHeader().setDefaultSectionSize(28)

        # Enable editing for delegate cells only
        self.file_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)

        self.file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_table.setAlternatingRowColors(True)

        # Enable context menu for file removal
        self.file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._show_file_context_menu)

    def _on_load_raw_data(self):
        """Delegate to experiment manager's load_raw_data."""
        self.main_app.experiment_data_manager.load_raw_data()

    def _on_load_search_data(self):
        """Delegate to experiment manager's load_search_data."""
        self.main_app.experiment_data_manager.load_search_data()

    def _on_add_msfragger_folder(self):
        """Delegate to experiment manager's add_msfragger_search_folder."""
        self.main_app.experiment_data_manager.add_msfragger_search_folder()

    def _on_prepare_data(self):
        """Delegate to experiment manager's combine_and_process_psm_files."""
        self.main_app.experiment_data_manager.combine_and_process_psm_files()

    def refresh_file_list(self):
        """Populate table with one row per loaded raw file."""
        edm = self.main_app.experiment_data_manager

        # Clear existing
        self.file_table.setRowCount(0)

        # Get all files
        search_files = edm.search_files
        raw_files = edm.raw_files

        if not raw_files:
            self.status_label.setText("No raw files loaded")
            return

        # Create one row per raw file
        for raw_path in raw_files:
            self._add_raw_file_row(raw_path, search_files)

        self._update_status()

    def _add_raw_file_row(self, raw_path, available_search_files):
        """Add a row for a raw file with search file dropdown."""
        row = self.file_table.rowCount()
        self.file_table.insertRow(row)

        # Make items read-only by setting appropriate flags
        read_only_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        # Column 0: Raw File (partial path)
        raw_display = self._get_partial_path(raw_path)
        raw_item = QTableWidgetItem(raw_display)
        raw_item.setData(Qt.ItemDataRole.UserRole, raw_path)
        raw_item.setToolTip(raw_path)
        raw_item.setFlags(read_only_flags)
        self.file_table.setItem(row, 0, raw_item)

        # Column 1: Raw Type
        raw_type = FileTypeUtils.determine_raw_file_type(os.path.basename(raw_path))
        raw_type_item = QTableWidgetItem(raw_type)
        raw_type_item.setFlags(read_only_flags)
        self.file_table.setItem(row, 1, raw_type_item)

        # Column 2: Search File (using delegate - store data in UserRole)
        search_item = QTableWidgetItem()

        # Display text shows selected file or placeholder
        matched = self.file_matches.get(raw_path)
        if matched:
            display_text = self._get_partial_path(matched)
            search_item.setData(Qt.ItemDataRole.UserRole, matched)  # Store search_path
        else:
            display_text = "Click here to select file"
            search_item.setData(Qt.ItemDataRole.UserRole, None)  # No match yet
        search_item.setText(display_text)

        # Enable editing for this item
        editable_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
        search_item.setFlags(editable_flags)
        self.file_table.setItem(row, 2, search_item)

        # Column 3: Search Type
        search_path = self.file_matches.get(raw_path)
        search_type = ""
        if search_path:
            search_type = FileTypeUtils.determine_search_file_type(search_path)
        search_type_item = QTableWidgetItem(search_type)
        search_type_item.setFlags(read_only_flags)
        self.file_table.setItem(row, 3, search_type_item)

        # Column 4: Validation indicator
        self._update_validation_cell(row, raw_path)

        # Connect delegate data change to update handler
        # We'll need to handle this differently - update via model changed signals
        # For now, we'll handle it by connecting to the table's model changes
        if not hasattr(self, '_delegate_connected'):
            self.file_table.model().dataChanged.connect(self._on_cell_data_changed)
            self._delegate_connected = True

    def _get_partial_path(self, full_path, depth=3):
        """Get filename + up to 3 parent directories for display."""
        try:
            path = Path(full_path)
            parts = path.parts[-(depth + 1):]  # Get last N parts
            return os.path.join(*parts)
        except Exception:
            return os.path.basename(full_path)

    def _on_cell_data_changed(self, index_from, index_to, _roles=None):
        """Handle data change from delegate (search file selection)."""
        # Only process Search File column (column 2)
        if index_from.column() != 2:
            return

        row = index_from.row()
        item = self.file_table.item(row, 0)
        if not item:
            return

        raw_path = item.data(Qt.ItemDataRole.UserRole)
        search_item = self.file_table.item(row, 2)
        if not search_item:
            return

        # Get the selected search file path from UserRole
        search_path = search_item.data(Qt.ItemDataRole.UserRole)
        self.file_matches[raw_path] = search_path

        # Make items read-only
        read_only_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        # Update search type column
        search_type = ""
        if search_path:
            search_type = FileTypeUtils.determine_search_file_type(search_path)
        search_type_item = QTableWidgetItem(search_type)
        search_type_item.setFlags(read_only_flags)
        self.file_table.setItem(row, 3, search_type_item)

        # Update validation
        self._update_validation_cell(row, raw_path)
        self._update_status()

    def _update_validation_cell(self, row, raw_path):
        """Update validation indicator (green/red/yellow) for a row."""
        # Make items read-only
        read_only_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        matched = self.file_matches.get(raw_path)

        if matched:
            # Check if search file exists and has valid columns
            if os.path.exists(matched):
                item = QTableWidgetItem("OK")
                item.setBackground(QBrush(QColor(144, 238, 144)))  # Light green
            else:
                item = QTableWidgetItem("Missing")
                item.setBackground(QBrush(QColor(255, 182, 193)))  # Light red
        else:
            item = QTableWidgetItem("No Match")
            item.setBackground(QBrush(QColor(255, 255, 200)))  # Light yellow

        item.setFlags(read_only_flags)
        self.file_table.setItem(row, 4, item)

    def auto_match_files(self):
        """Automatically match search files to raw files based on spectrum file names."""
        from utils.utility_classes.filetypedetector import FileTypeDetector
        from utils.psm_normalizers import NormalizerFactory

        edm = self.main_app.experiment_data_manager
        raw_files = edm.raw_files
        search_files = edm.search_files

        if not raw_files or not search_files:
            QMessageBox.information(
                self.main_app,
                "Auto-Match",
                "Please load both raw files and search files first."
            )
            return

        # Build raw file lookup: base_name (lowercase) -> full_path
        raw_lookup = {}
        for raw_path in raw_files:
            base = os.path.splitext(os.path.basename(raw_path))[0]
            raw_lookup[base.lower()] = raw_path

        matched_count = 0

        for search_path in search_files:
            file_type = FileTypeDetector.detect_search_file_type(search_path)
            if not file_type:
                continue

            try:
                # Read first few rows to extract spectrum file names
                # Use custom Byonic reader for Byonic files
                if file_type == "Byonic":
                    df_sample = ByonicNormalizer.read_byonic_csv(search_path)
                    # Limit to 100 rows if the file is larger
                    if len(df_sample) > 100:
                        df_sample = df_sample.iloc[:100]
                else:
                    df_sample = pd.read_csv(search_path, sep='\t', nrows=100)
                normalizer = NormalizerFactory.create(
                    file_type,
                    source_file_path=search_path
                )
                spectrum_files = normalizer.extract_spectrum_files(df_sample)

                # Try to match each spectrum file to a raw file
                for spec_file in spectrum_files:
                    spec_base = spec_file.lower()
                    if spec_base in raw_lookup:
                        raw_path = raw_lookup[spec_base]
                        self.file_matches[raw_path] = search_path
                        matched_count += 1
                        break
            except Exception as e:
                print(f"[WARNING] Could not auto-match {search_path}: {e}")

        self.refresh_file_list()
        QMessageBox.information(
            self.main_app,
            "Auto-Match Complete",
            f"Matched {matched_count} of {len(raw_files)} raw files."
        )

    def clear_matches(self):
        """Clear all file matches."""
        self.file_matches.clear()
        self.refresh_file_list()

    def _update_status(self):
        """Update status label with match statistics."""
        edm = self.main_app.experiment_data_manager
        total_search = len(edm.search_files)
        total_raw = len(edm.raw_files)
        matched = sum(1 for v in self.file_matches.values() if v)
        self.status_label.setText(
            f"Raw files: {total_raw}, Search files: {total_search}, Matched: {matched}"
        )

    def _show_file_context_menu(self, position):
        """Show context menu for file removal."""
        item = self.file_table.itemAt(position)
        if item is None:
            return

        row = item.row()
        raw_item = self.file_table.item(row, 0)
        if not raw_item:
            return

        raw_path = raw_item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self.main_app)
        remove_action = QAction("Remove this file", self.main_app)
        remove_action.triggered.connect(lambda: self._remove_raw_file(raw_path))
        menu.addAction(remove_action)

        menu.exec(self.file_table.mapToGlobal(position))

    def _remove_raw_file(self, raw_path):
        """Remove a single raw file and clean up associated data."""
        reply = QMessageBox.question(
            self.main_app,
            "Confirm Removal",
            f"Remove {os.path.basename(raw_path)} from the loaded files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        edm = self.main_app.experiment_data_manager

        # Remove from raw files list
        if raw_path in edm.raw_files:
            edm.raw_files.remove(raw_path)

        # Remove from file matches
        if raw_path in self.file_matches:
            del self.file_matches[raw_path]

        # Remove from extracted spectral data
        if raw_path in edm.extracted_spectral_data:
            del edm.extracted_spectral_data[raw_path]

        # Update dataframe and refresh UI
        edm._create_and_save_dataframe()
        self.refresh_file_list()

        # Update raw file dropdown if direct scan mode is enabled
        if (hasattr(self.main_app, 'enable_direct_scan_checkbox') and
            self.main_app.enable_direct_scan_checkbox.isChecked()):
            from utils.utilities import FileProcessingUtils
            FileProcessingUtils.update_raw_file_dropdown(
                self.main_app.raw_file_combo, edm.raw_files
            )

        self.main_app.show_toast_message(f"Removed {os.path.basename(raw_path)}")

    def _clear_all_raw_files(self):
        """Clear all loaded raw files."""
        edm = self.main_app.experiment_data_manager

        if not edm.raw_files:
            QMessageBox.information(
                self.main_app,
                "No Files",
                "No raw files are currently loaded."
            )
            return

        reply = QMessageBox.question(
            self.main_app,
            "Confirm Clear All",
            f"Remove all {len(edm.raw_files)} raw file(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Clear all raw files and associated data
        edm.raw_files.clear()
        self.file_matches.clear()
        edm.extracted_spectral_data.clear()

        # Update dataframe and refresh UI
        edm._create_and_save_dataframe()
        self.refresh_file_list()

        # Update raw file dropdown if direct scan mode is enabled
        if (hasattr(self.main_app, 'enable_direct_scan_checkbox') and
            self.main_app.enable_direct_scan_checkbox.isChecked()):
            from utils.utilities import FileProcessingUtils
            FileProcessingUtils.update_raw_file_dropdown(
                self.main_app.raw_file_combo, edm.raw_files
            )

        self.main_app.show_toast_message("All raw files removed")

    def _clear_all_search_files(self):
        """Clear all loaded search files."""
        edm = self.main_app.experiment_data_manager

        if not edm.search_files:
            QMessageBox.information(
                self.main_app,
                "No Files",
                "No search files are currently loaded."
            )
            return

        reply = QMessageBox.question(
            self.main_app,
            "Confirm Clear All",
            f"Remove all {len(edm.search_files)} search file(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Clear all search files and associated data
        edm.search_files.clear()
        self.file_matches.clear()

        # Clear merged dataframe if it exists
        if not edm.merged_df.empty:
            edm.merged_df = pd.DataFrame()

        # Update dataframe and refresh UI
        edm._create_and_save_dataframe()
        self.refresh_file_list()

        self.main_app.show_toast_message("All search files removed")

    def update_theme(self, theme_name):
        """Update tab theme for dark/light mode support."""
        if self.file_table:
            StyleSheet.apply_table_styling(self.file_table)

    def get_file_matches(self) -> dict:
        """Get the current file matches dictionary.

        Returns:
            dict: Mapping of raw_file_path -> search_file_path (or None)
        """
        return self.file_matches.copy()
