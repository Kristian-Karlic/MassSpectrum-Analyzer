import pandas as pd
import ast
import json
import traceback
import logging
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLineEdit, QMessageBox, QStackedWidget, QHeaderView, QProgressDialog,
    QLabel, QApplication, QComboBox, QMenu, QScrollArea, QFrame, QSizePolicy)
from PyQt6.QtCore import pyqtSignal, Qt, QMimeData, QPoint, QTimer
from PyQt6.QtGui import QDrag, QPainter, QPixmap
from utils.utility_classes.toaster import QToaster
from utils.style.style import StyleSheet, EditorConstants
from utils.spectral_extraction.spectral_extraction import spectral_extraction
from utils.utilities import DataGatherer

logger = logging.getLogger(__name__)

class PSMSummaryWidget(QWidget):

    # Signal: user selected a row that has a Peptide, Parsed Modifications, Charge
    peptideSelected = pyqtSignal(str, list, int, dict)  # (Peptide, ParsedMods, Charge)
    rawDataExtracted = pyqtSignal(object, object)  # will carry (mz_array, intensity_array)


    def _match_details_row(self, table_row):
        """Match a visible details-table row back to the underlying DataFrame row.

        Returns (visible_row_data, row_data_dict) or (None, None) on failure.
        """
        # Build column name → table-column-index mapping
        col_name_to_idx = {}
        for col_idx in range(self.details_table.columnCount()):
            header_item = self.details_table.horizontalHeaderItem(col_idx)
            if header_item:
                col_name_to_idx[header_item.text()] = col_idx

        needed_columns = ["Modified Peptide", "Charge", "Hyperscore", "Observed M/Z", "Assigned Modifications"]
        visible_row_data = {}
        for col_name in needed_columns:
            if col_name in col_name_to_idx:
                item = self.details_table.item(table_row, col_name_to_idx[col_name])
                if item:
                    visible_row_data[col_name] = item.text()

        charge_val = int(visible_row_data.get("Charge", 1))
        hyperscore_val = float(visible_row_data.get("Hyperscore", 0))
        observed_mz_val = float(visible_row_data.get("Observed M/Z", 0))

        matching_rows = self.current_details_df[
            (self.current_details_df["Charge"] == charge_val) &
            (abs(self.current_details_df["Hyperscore"] - hyperscore_val) < 0.001) &
            (abs(self.current_details_df["Observed M/Z"] - observed_mz_val) < 0.001)
        ]

        if matching_rows.empty:
            logger.debug("[ERROR] Could not find matching row in details data")
            return None, None

        return visible_row_data, matching_rows.iloc[0].to_dict()

    def _on_details_table_singleclick(self, row, col):
        """Handle single click to populate data from pre-extracted cache"""
        logger.debug(f"[DEBUG] Single click initiated: row={row}, col={col}")

        if self.current_details_df.empty:
            logger.debug("[DEBUG] Current details DataFrame is empty, returning")
            return

        try:
            visible_row_data, row_data = self._match_details_row(row)
            if row_data is None:
                return

            # Get peptide and modifications
            peptide_str = row_data.get("Peptide", "")
            mods_str = str(row_data.get("Parsed Modifications", "[]"))

            try:
                parsed_mods = ast.literal_eval(mods_str)
                if not isinstance(parsed_mods, list):
                    parsed_mods = []
            except Exception as e:
                logger.debug(f"[ERROR] Could not parse 'Parsed Modifications': {e}")
                parsed_mods = []

            charge_val = int(visible_row_data.get("Charge", 1))

            # Emit peptide selection signal
            self.peptideSelected.emit(peptide_str, parsed_mods, charge_val, row_data)

            # Get spectral data from pre-extracted cache instead of extracting
            self.get_spectral_data_from_cache(row_data)

        except Exception as e:
            logger.debug(f"[ERROR] Unexpected exception in _on_details_table_singleclick: {e}")
            traceback.print_exc()

    def get_spectral_data_from_cache(self, row_data):
        """Get spectral data from the pre-extracted cache"""
        try:
            # Get the main window reference to access extracted data
            main_window = self.get_main_window()
            if not main_window or not hasattr(main_window, 'extracted_spectral_data'):
                logger.debug("[WARNING] No pre-extracted spectral data available")
                QMessageBox.information(self, "No Data",
                    "No pre-extracted spectral data found. Please run 'Prepare data' first.")
                return
            
            # Get file path and scan number
            raw_path_str = row_data.get("spectrum_file_path", "")
            index_str = str(row_data.get("index", ""))

            if not raw_path_str or not index_str:
                logger.debug("[WARNING] Missing raw path or index")
                return
            
            # Use index_str instead of undefined scan_str
            scan_str = DataGatherer._clean_scan_number(index_str)
            
            # Create cache key
            cache_key = f"{raw_path_str}_{scan_str}"

            # Get data from cache
            extracted_data = main_window.extracted_spectral_data
            if cache_key in extracted_data:
                spectral_data = extracted_data[cache_key]
                mz_array = spectral_data['mz_values']
                intensity_array = spectral_data['intensity_values']
                header_info = spectral_data.get('header', None)

                logger.debug(f"[DEBUG] Retrieved cached data: {len(mz_array)} peaks")
                if header_info:
                    logger.debug(f"[DEBUG] Header info: {header_info[:100]}...") 
                
                # Emit the signal with cached data
                self.rawDataExtracted.emit(mz_array, intensity_array)
                
                # Show success message with header info
                message = f"Loaded cached spectral data ({len(mz_array)} peaks)"
                if header_info:
                    message += f"\nHeader: {header_info[:50]}..."  
            
                toast = QToaster(self)
                toast.show_message(message)
                
            else:
                logger.debug(f"[WARNING] No cached data found for key: {cache_key}")
                # Fallback: offer to extract this specific scan
                reply = QMessageBox.question(self, "Data Not Found",
                    f"No cached spectral data found for scan {scan_str}.\n"
                    f"Would you like to extract it now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.extract_single_scan_fallback(raw_path_str, scan_str)
                
        except Exception as e:
            logger.debug(f"[ERROR] Error retrieving cached data: {e}")
            traceback.print_exc()

    def extract_single_scan_fallback(self, raw_path, scan_str):
        """Fallback method to extract a single scan if not in cache"""
        try:
            # Show progress
            progress = QProgressDialog("Extracting scan data...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(50)
            progress.show()
            
            QApplication.processEvents()
            
            result = spectral_extraction(raw_path, scan_str)
            
            if result is not None:
                mz_array, intensity_array = result
                progress.setValue(100)
                
                # Add to cache for future use
                main_window = self.get_main_window()
                if main_window and hasattr(main_window, 'extracted_spectral_data'):
                    cache_key = f"{raw_path}_{scan_str}"
                    main_window.extracted_spectral_data[cache_key] = {
                        'mz_values': list(mz_array),
                        'intensity_values': list(intensity_array)
                    }
                
                # Emit signal
                self.rawDataExtracted.emit(mz_array, intensity_array)
                
                progress.close()
            
                toast = QToaster(self)
                toast.show_message(f"Extracted scan data ({len(mz_array)} peaks)")
                
            else:
                progress.close()
                QMessageBox.warning(self, "Error", f"Failed to extract scan {scan_str}")
                
        except Exception as e:
            if 'progress' in locals():
                progress.close()
            QMessageBox.warning(self, "Error", f"Extraction failed: {str(e)}")

    def get_main_window(self):
        """Get reference to the main application window"""
        from utils.utility_classes.widgets import get_main_window
        return get_main_window(self, 'extracted_spectral_data')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.raw_df = pd.DataFrame()
        self.summary_df = pd.DataFrame()
        self.summary_df_unfiltered = pd.DataFrame()
        self.original_details_df = pd.DataFrame()
        self.current_details_df = pd.DataFrame()
        
        # Initialize worker references to None for safety
        self._current_worker = None
        self._current_progress = None
        
        # PERFORMANCE: Add debounce timers for filtering
        self.summary_filter_timer = QTimer()
        self.summary_filter_timer.setSingleShot(True)
        self.summary_filter_timer.timeout.connect(self._apply_summary_filter_delayed)
        
        self.details_filter_timer = QTimer()
        self.details_filter_timer.setSingleShot(True)
        self.details_filter_timer.timeout.connect(self._apply_details_filter_delayed)
        
        # PERFORMANCE: Set debounce delay (milliseconds)
        self.filter_delay_ms = 300  # Wait 300ms after user stops typing
        
        # MULTI-FILTER: Store active filters for summary and details
        self.active_summary_filters = {}  # {column_name: filter_value}
        self.active_details_filters = {}  # {column_name: filter_value}

        # Column visibility: track hidden columns by name
        self.hidden_summary_columns = set()
        self.hidden_details_columns = set()

        # Default columns to show in details view (user can add more from raw_df)
        self.default_details_columns = ["Modified Peptide", "Charge", "Hyperscore", "Observed M/Z",
                                        "Assigned Modifications", "Spectrum file", "index", "Header"]
        self.visible_details_columns = set(self.default_details_columns)
        
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # Create main horizontal layout for table and filters
        self.main_content_layout = QHBoxLayout()
        main_layout.addLayout(self.main_content_layout)

        # Left side - tables with navigation
        self.table_section_layout = QVBoxLayout()
        
        # Summary filter layout (initially visible)
        self.summary_filter_widget = QWidget()
        summary_filter_layout = QVBoxLayout(self.summary_filter_widget)
        summary_filter_layout.setContentsMargins(5, 5, 5, 5)
        summary_filter_layout.setSpacing(3)
        
        
        # MULTI-FILTER: Column selector dropdown
        self.summary_column_selector = QComboBox()
        self.summary_column_selector.addItems(["Peptide", "Protein", "Unique Modifications", "Prev AA", "Next AA"])
        self.summary_column_selector.setStyleSheet(EditorConstants.get_lineedit_style())
        summary_filter_layout.addWidget(self.summary_column_selector)

        # MULTI-FILTER: Single filter input
        self.summary_filter_input = QLineEdit()
        self.summary_filter_input.setPlaceholderText("Enter filter text...")
        self.summary_filter_input.returnPressed.connect(self.add_summary_filter)
        self.summary_filter_input.setStyleSheet(EditorConstants.get_lineedit_style())
        summary_filter_layout.addWidget(self.summary_filter_input)
        
        # MULTI-FILTER: Add filter button
        add_filter_btn = QPushButton("Add Filter")
        add_filter_btn.clicked.connect(self.add_summary_filter)
        add_filter_btn.setMaximumHeight(25)
        add_filter_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        summary_filter_layout.addWidget(add_filter_btn)
        
        
        self.summary_active_filters_list = QLabel("None")
        self.summary_active_filters_list.setWordWrap(True)
        self.summary_active_filters_list.setStyleSheet(f"""
            QLabel {{
                font-size: 9px;
                color: {EditorConstants.TEXT_COLOR()};
                padding: 3px;
                background-color: {EditorConstants.GRAY_50()};
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
            }}
        """)
        summary_filter_layout.addWidget(self.summary_active_filters_list)

        clear_summary_btn = QPushButton("Clear")
        clear_summary_btn.clicked.connect(self.clear_summary_filter)
        clear_summary_btn.setMaximumHeight(25)
        clear_summary_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        summary_filter_layout.addWidget(clear_summary_btn)

        # Details filter layout (initially hidden)
        self.details_filter_widget = QWidget()
        details_filter_layout = QVBoxLayout(self.details_filter_widget)
        details_filter_layout.setContentsMargins(5, 5, 5, 5)
        details_filter_layout.setSpacing(3)
        
        # Add filter label
        details_filter_label = QLabel("Details Filters")
        details_filter_label.setStyleSheet(f"""
            QLabel {{
                {EditorConstants.get_font_string("bold")}
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                font-size: 11px;
            }}
        """)
        details_filter_layout.addWidget(details_filter_label)
        
        # MULTI-FILTER: Column selector dropdown
        self.details_column_selector = QComboBox()
        # Will be populated with all columns from raw_df when data is loaded
        self.details_column_selector.setStyleSheet(EditorConstants.get_lineedit_style())
        details_filter_layout.addWidget(self.details_column_selector)

        # MULTI-FILTER: Single filter input
        self.details_filter_input = QLineEdit()
        self.details_filter_input.setPlaceholderText("Enter filter text...")
        self.details_filter_input.returnPressed.connect(self.add_details_filter)
        self.details_filter_input.setStyleSheet(EditorConstants.get_lineedit_style())
        details_filter_layout.addWidget(self.details_filter_input)
        
        # MULTI-FILTER: Add filter button
        add_details_filter_btn = QPushButton("Add Filter")
        add_details_filter_btn.clicked.connect(self.add_details_filter)
        add_details_filter_btn.setMaximumHeight(25)
        add_details_filter_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        details_filter_layout.addWidget(add_details_filter_btn)
        
        # MULTI-FILTER: Active filters display
        details_active_filters_label = QLabel("Active Filters:")
        details_active_filters_label.setStyleSheet(f"""
            QLabel {{
                font-size: 10px;
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                margin-top: 5px;
            }}
        """)
        details_filter_layout.addWidget(details_active_filters_label)
        
        self.details_active_filters_list = QLabel("None")
        self.details_active_filters_list.setWordWrap(True)
        self.details_active_filters_list.setStyleSheet(f"""
            QLabel {{
                font-size: 9px;
                color: {EditorConstants.TEXT_COLOR()};
                padding: 3px;
                background-color: {EditorConstants.GRAY_50()};
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 3px;
            }}
        """)
        details_filter_layout.addWidget(self.details_active_filters_list)

        # Horizontal layout for Clear and Back buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(5)
        
        clear_details_btn = QPushButton("Clear")
        clear_details_btn.clicked.connect(self.clear_details_filter)
        clear_details_btn.setMaximumHeight(25)
        clear_details_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        buttons_layout.addWidget(clear_details_btn)

        # Add back button next to clear button
        self.back_button = QPushButton("←")
        self.back_button.setToolTip("Back to Summary")
        self.back_button.clicked.connect(self._return_to_summary)
        self.back_button.setMaximumHeight(25)
        self.back_button.setMaximumWidth(35)
        self.back_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {EditorConstants.GRAY_500()};
                color: white;
                {EditorConstants.get_border_string(EditorConstants.GRAY_600(), radius=EditorConstants.BORDER_RADIUS_SMALL())}
                font-size: 14px;
                {EditorConstants.get_font_string("bold")}
                padding: {EditorConstants.PADDING_SMALL()};
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
            }}
            QPushButton:hover {{
                background-color: {EditorConstants.GRAY_600()};
            }}
            QPushButton:pressed {{
                background-color: {EditorConstants.PRESSED_COLOR()};
            }}
        """)
        buttons_layout.addWidget(self.back_button)
        
        details_filter_layout.addLayout(buttons_layout)

        # Hide details filters initially
        self.details_filter_widget.setVisible(False)

        # StackedWidget for summary vs details
        self.stacked_widget = QStackedWidget()

        # Page 0: summary
        self.summary_page = QWidget()
        summary_page_layout = QVBoxLayout(self.summary_page)
        summary_page_layout.setContentsMargins(0, 0, 0, 0)
        
        self.summary_table = QTableWidget()
        StyleSheet.apply_table_styling(self.summary_table)
        self.summary_table.setAlternatingRowColors(False)  # Disable alternating colors
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.cellDoubleClicked.connect(self.show_details_for_row)
        self.summary_table.setSortingEnabled(True)
        self.summary_table.horizontalHeader().setSectionsClickable(True)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.summary_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.summary_table.horizontalHeader().customContextMenuRequested.connect(self._show_summary_header_menu)
        summary_page_layout.addWidget(self.summary_table)
        self.stacked_widget.addWidget(self.summary_page)
        
        # Page 1: details (no longer needs the back button here)
        self.details_page = QWidget()
        details_page_layout = QVBoxLayout(self.details_page)  # Changed back to vertical
        details_page_layout.setContentsMargins(0, 0, 0, 0)
        details_page_layout.setSpacing(5)
        
        self.details_table = QTableWidget()
        StyleSheet.apply_table_styling(self.details_table)
        self.details_table.setAlternatingRowColors(False)
        self.details_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.details_table.setSortingEnabled(True)
        self.details_table.horizontalHeader().setSectionsClickable(True)
        self.details_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.details_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.details_table.horizontalHeader().customContextMenuRequested.connect(self._show_details_header_menu)
        details_page_layout.addWidget(self.details_table)
        self.stacked_widget.addWidget(self.details_page)
        self.table_section_layout.addWidget(self.stacked_widget)

        # Add table section to main content (takes all available space)
        self.main_content_layout.addLayout(self.table_section_layout, stretch=1)

        # Right side - filters (compact vertical layout) in a scroll area
        # so the filter panel's implicit minimum height doesn't prevent
        # the PSM summary widget from shrinking with the window.
        filter_container = QWidget()
        self.filter_section_layout = QVBoxLayout(filter_container)
        self.filter_section_layout.setContentsMargins(5, 5, 5, 5)

        # Add both filter widgets to the right side
        self.filter_section_layout.addWidget(self.summary_filter_widget)
        self.filter_section_layout.addWidget(self.details_filter_widget)
        self.filter_section_layout.addStretch()  # Push filters to top

        filter_scroll = QScrollArea()
        filter_scroll.setWidget(filter_container)
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filter_scroll.setFrameShape(QFrame.Shape.NoFrame)

        filter_scroll.setMaximumWidth(215)

        # Add filter section to main content (fixed compact width, no stretch)
        self.main_content_layout.addWidget(filter_scroll)

        # Apply compact styling to filter widgets
        filter_widget_style = f"""
            QWidget {{
                background-color: {EditorConstants.GRAY_50()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_LARGE())}
            }}
            QLabel {{
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                {EditorConstants.get_font_string("bold")}
                border: none;
                background: transparent;
            }}
            {EditorConstants.get_scrollbar_style()}
        """
        self.summary_filter_widget.setStyleSheet(filter_widget_style)
        self.details_filter_widget.setStyleSheet(filter_widget_style)
        
        # Set maximum width for filter section to keep it compact
        self.summary_filter_widget.setMaximumWidth(200)
        self.details_filter_widget.setMaximumWidth(200)

        # Initialize click event for filling out the peptide sequence and modifications
        self.details_table.cellClicked.connect(self._on_details_table_singleclick)

    def _return_to_summary(self):
        """Return to summary view and show/hide appropriate filters"""
        self.stacked_widget.setCurrentIndex(0)
        
        # Show summary filters, hide details filters
        self.summary_filter_widget.setVisible(True)
        self.details_filter_widget.setVisible(False)

    def setData(self, df: pd.DataFrame):
        """
        Receive the combined PSM DataFrame from the main app
        and build a summary of unique (Peptide, Protein).
        """
        self.raw_df = df.copy()
        self._make_summary_df()
        self._show_summary_table()

        # Initialize details column selector with all available columns
        if not self.raw_df.empty:
            all_columns = sorted(list(self.raw_df.columns))
            self.details_column_selector.clear()
            self.details_column_selector.addItems(all_columns)

    def _make_summary_df(self):
        if self.raw_df.empty:
            self.summary_df = pd.DataFrame()
            self.summary_df_unfiltered = pd.DataFrame()
            return

        def gather_mods(series):
            unique_mods = set()
            for val in series.dropna():
                unique_mods.add(val.strip())
            return "; ".join(unique_mods)

        required_columns = {
            "Peptide", 
            "Protein", 
            "Assigned Modifications",
            "Prev AA",
            "Next AA",
            "Peptide Length",
            "Protein Start",
            "Protein End",
            "Hyperscore"  # Added for average score calculation
        }

        if not required_columns.issubset(self.raw_df.columns):
            missing = required_columns - set(self.raw_df.columns)
            logger.debug(f"Warning: Missing columns: {missing}")
            self.summary_df = pd.DataFrame()
            self.summary_df_unfiltered = pd.DataFrame()
            return

        grp = self.raw_df.groupby(["Peptide", "Protein"], dropna=False)
        summary = grp.agg({
            "Assigned Modifications": gather_mods,
            "Prev AA": "first",
            "Next AA": "first", 
            "Peptide Length": "first",
            "Protein Start": "first",
            "Protein End": "first",
            "Hyperscore": "mean",  # Calculate average score
            # Use a different column for counting, or use size()
        }).reset_index()
        
        # Add count column separately
        count_df = grp.size().reset_index(name='Count')
        summary = summary.merge(count_df, on=["Peptide", "Protein"])
        
        # Rename columns appropriately
        summary.rename(columns={
            "Assigned Modifications": "Unique Modifications",
            "Hyperscore": "Average Score"
        }, inplace=True)
        
        # Round average score to 2 decimal places
        summary["Average Score"] = summary["Average Score"].round(2)

        self.summary_df = summary
        self.summary_df_unfiltered = summary.copy()

    def _show_summary_table(self, df=None):
        if df is None:
            df = self.summary_df

        if df.empty:
            self.summary_table.setRowCount(0)
            self.summary_table.setColumnCount(0)
            return

        # Temporarily disable sorting while updating
        self.summary_table.setSortingEnabled(False)

        # Clear existing content
        self.summary_table.clear()

        self.summary_table.setRowCount(len(df))
        self.summary_table.setColumnCount(len(df.columns))
        self.summary_table.setHorizontalHeaderLabels(df.columns)

        # Define numeric columns for proper sorting
        numeric_columns = ["Average Score", "Count", "Peptide Length", "Protein Start", "Protein End"]

        for row_idx in range(len(df)):
            for col_idx, col_name in enumerate(df.columns):
                val = df.iloc[row_idx, col_idx]
                item = QTableWidgetItem()
                
                # Handle numeric columns specially for proper sorting
                if col_name in numeric_columns:
                    try:
                        # Set numeric data for sorting
                        item.setData(Qt.ItemDataRole.DisplayRole, float(val))
                    except (ValueError, TypeError):
                        # Fallback to text if conversion fails
                        item.setText(str(val))
                else:
                    # Set full text for all non-numeric columns; tooltip for hover display
                    text = str(val)
                    item.setText(text)
                    item.setToolTip(text)
                
                self.summary_table.setItem(row_idx, col_idx, item)

        # Custom column sizing instead of resizeColumnsToContents()
        self._set_custom_column_widths()
        self._apply_summary_column_visibility()

        # Re-enable sorting
        self.summary_table.setSortingEnabled(True)
        
        # PERFORMANCE: Re-enable updates and refresh
        self.summary_table.setUpdatesEnabled(True)
        self.summary_table.viewport().update()
        
        self.stacked_widget.setCurrentIndex(0)
        
    def _set_custom_column_widths(self):
        """Set initial column widths for the summary table.

        Protein and Unique Modifications start narrow (tooltip shows full value on hover).
        All columns remain interactively resizable; last column stretches to fill space.
        """
        self.summary_table.resizeColumnsToContents()

        header = self.summary_table.horizontalHeader()
        # Re-apply Interactive mode explicitly — PyQt6 can flip per-section modes
        # to ResizeToContents internally during resizeColumnsToContents().
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        # Cap initial widths for columns that can become very wide
        narrow_caps = {"Protein": 120, "Unique Modifications": 150}
        for col_idx in range(self.summary_table.columnCount()):
            header_item = self.summary_table.horizontalHeaderItem(col_idx)
            if header_item and header_item.text() in narrow_caps:
                cap = narrow_caps[header_item.text()]
                if self.summary_table.columnWidth(col_idx) > cap:
                    self.summary_table.setColumnWidth(col_idx, cap)

        # Stretch last section so columns fill all available space
        header.setStretchLastSection(True)

    def _show_summary_header_menu(self, pos):
        """Show context menu on summary table header to toggle column visibility"""
        menu = QMenu(self)
        header = self.summary_table.horizontalHeader()

        for col_idx in range(self.summary_table.columnCount()):
            header_item = self.summary_table.horizontalHeaderItem(col_idx)
            if not header_item:
                continue
            col_name = header_item.text()
            action = menu.addAction(col_name)
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(col_idx))
            action.setData(col_idx)

        chosen = menu.exec(header.mapToGlobal(pos))
        if chosen:
            col_idx = chosen.data()
            col_name = self.summary_table.horizontalHeaderItem(col_idx).text()
            if chosen.isChecked():
                header.setSectionHidden(col_idx, False)
                self.hidden_summary_columns.discard(col_name)
            else:
                header.setSectionHidden(col_idx, True)
                self.hidden_summary_columns.add(col_name)

    def _show_details_header_menu(self, pos):
        """Show context menu on details table header to toggle column visibility.

        Shows ALL columns from raw_df, allowing user to add columns beyond defaults.
        """
        menu = QMenu(self)

        # Build the full column list from both raw_df and the current details slice.
        # Using both sources ensures engine-specific columns (e.g. MSFragger) that
        # may not be on every row still appear in the menu.
        raw_cols = list(self.raw_df.columns) if not self.raw_df.empty else []
        details_cols = (list(self.current_details_df.columns)
                        if not self.current_details_df.empty else [])
        # Deduplicate while preserving order (raw_df first)
        seen: set = set()
        all_columns: list = []
        for col in raw_cols + details_cols:
            if col not in seen:
                seen.add(col)
                all_columns.append(col)

        if not all_columns:
            return

        # Add separator and label for default columns
        default_menu = menu.addMenu("Default Columns")
        other_menu = menu.addMenu("Additional Columns")

        # Track which columns need table rebuild vs just visibility toggle
        current_table_columns = set()
        for col_idx in range(self.details_table.columnCount()):
            header_item = self.details_table.horizontalHeaderItem(col_idx)
            if header_item:
                current_table_columns.add(header_item.text())

        # Add default columns to default menu
        for col_name in self.default_details_columns:
            if col_name in all_columns:
                action = default_menu.addAction(col_name)
                action.setCheckable(True)
                is_visible = col_name in self.visible_details_columns and col_name not in self.hidden_details_columns
                action.setChecked(is_visible)
                action.setData(("default", col_name))

        # Add other columns to additional menu (sorted alphabetically)
        other_columns = sorted([col for col in all_columns if col not in self.default_details_columns])
        for col_name in other_columns:
            action = other_menu.addAction(col_name)
            action.setCheckable(True)
            is_visible = col_name in self.visible_details_columns and col_name not in self.hidden_details_columns
            action.setChecked(is_visible)
            action.setData(("other", col_name))

        chosen = menu.exec(self.details_table.horizontalHeader().mapToGlobal(pos))
        if chosen:
            col_type, col_name = chosen.data()

            if chosen.isChecked():
                # User wants to show this column
                self.visible_details_columns.add(col_name)
                self.hidden_details_columns.discard(col_name)

                # If column wasn't in the table before, need to rebuild
                if col_name not in current_table_columns:
                    self._show_details_table()
                    self._update_details_filter_dropdown()
                else:
                    # Just unhide it
                    header = self.details_table.horizontalHeader()
                    for col_idx in range(self.details_table.columnCount()):
                        header_item = self.details_table.horizontalHeaderItem(col_idx)
                        if header_item and header_item.text() == col_name:
                            header.setSectionHidden(col_idx, False)
                            break
            else:
                # User wants to hide this column
                self.hidden_details_columns.add(col_name)

                # If column is currently in table, just hide it
                if col_name in current_table_columns:
                    header = self.details_table.horizontalHeader()
                    for col_idx in range(self.details_table.columnCount()):
                        header_item = self.details_table.horizontalHeaderItem(col_idx)
                        if header_item and header_item.text() == col_name:
                            header.setSectionHidden(col_idx, True)
                            break
                else:
                    # Column was in visible set but not table yet, just remove from visible
                    self.visible_details_columns.discard(col_name)

    # ------------------------------------------------------------------ #
    #  Shared filter / column-visibility helpers
    # ------------------------------------------------------------------ #
    def _apply_column_visibility(self, table, hidden_set):
        """Re-apply hidden column state after a table rebuild."""
        header = table.horizontalHeader()
        for col_idx in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(col_idx)
            if header_item and header_item.text() in hidden_set:
                header.setSectionHidden(col_idx, True)

    def _add_filter(self, column_selector, filter_input, active_filters, display_label, apply_fn):
        """Generic add-filter used by both summary and details."""
        column = column_selector.currentText()
        filter_text = filter_input.text().strip()
        if not filter_text:
            return
        active_filters[column] = filter_text
        filter_input.clear()
        self._update_filters_display(active_filters, display_label)
        apply_fn()

    @staticmethod
    def _update_filters_display(active_filters, display_label):
        """Update an active-filters QLabel."""
        if not active_filters:
            display_label.setText("None")
        else:
            display_label.setText("\n".join(f"• {col}: {val}" for col, val in active_filters.items()))

    def _clear_filter(self, filter_input, active_filters, display_label):
        """Generic clear-filter used by both summary and details."""
        active_filters.clear()
        filter_input.clear()
        self._update_filters_display(active_filters, display_label)

    def _apply_summary_column_visibility(self):
        self._apply_column_visibility(self.summary_table, self.hidden_summary_columns)

    def _apply_details_column_visibility(self):
        self._apply_column_visibility(self.details_table, self.hidden_details_columns)

    def _update_details_filter_dropdown(self):
        """Update the details filter dropdown to include ALL columns from raw_df"""
        current_selection = self.details_column_selector.currentText()
        self.details_column_selector.clear()

        # Show ALL columns from raw_df, not just visible table columns
        # This allows filtering by any column, even if not displayed
        if not self.raw_df.empty:
            all_columns = sorted(list(self.raw_df.columns))
            self.details_column_selector.addItems(all_columns)

        # Try to restore previous selection
        idx = self.details_column_selector.findText(current_selection)
        if idx >= 0:
            self.details_column_selector.setCurrentIndex(idx)

    # Summary filtering methods
    def on_summary_filter_text_changed(self):
        self.summary_filter_timer.stop()
        self.summary_filter_timer.start(self.filter_delay_ms)

    def _apply_summary_filter_delayed(self):
        self.apply_summary_filter()

    def add_summary_filter(self):
        self._add_filter(self.summary_column_selector, self.summary_filter_input,
                         self.active_summary_filters, self.summary_active_filters_list,
                         self.apply_summary_filter)

    def update_summary_filters_display(self):
        self._update_filters_display(self.active_summary_filters, self.summary_active_filters_list)
    
    def apply_summary_filter(self):
        """Apply all active filters to summary data"""
        if self.summary_df_unfiltered.empty:
            return
        
        df_filtered = self.summary_df_unfiltered.copy()
        
        # Apply each active filter
        for column, filter_value in self.active_summary_filters.items():
            if column in df_filtered.columns:
                # Handle numeric columns differently (Hyperscore would be in details, but just in case)
                if df_filtered[column].dtype in ['int64', 'float64']:
                    try:
                        numeric_val = float(filter_value)
                        df_filtered = df_filtered[df_filtered[column] >= numeric_val]
                    except ValueError:
                        pass  # Invalid numeric input, skip
                else:
                    # Text-based filtering
                    df_filtered = df_filtered[df_filtered[column].astype(str).str.contains(filter_value, case=False, na=False)]

        self.summary_df = df_filtered
        self._show_summary_table(self.summary_df)

    def clear_summary_filter(self):
        self._clear_filter(self.summary_filter_input, self.active_summary_filters,
                           self.summary_active_filters_list)
        self.summary_df = self.summary_df_unfiltered.copy()
        self._show_summary_table(self.summary_df)

    # Details filtering methods
    def on_details_filter_text_changed(self):
        self.details_filter_timer.stop()
        self.details_filter_timer.start(self.filter_delay_ms)

    def _apply_details_filter_delayed(self):
        self.apply_details_filter()

    def add_details_filter(self):
        self._add_filter(self.details_column_selector, self.details_filter_input,
                         self.active_details_filters, self.details_active_filters_list,
                         self.apply_details_filter)

    def update_details_filters_display(self):
        self._update_filters_display(self.active_details_filters, self.details_active_filters_list)
    
    def apply_details_filter(self):
        """Apply all active filters to details data"""
        if self.original_details_df.empty:
            return
            
        df_filtered = self.original_details_df.copy()
        
        # Apply each active filter
        for column, filter_value in self.active_details_filters.items():
            if column in df_filtered.columns:
                # Handle different column types
                if column == "Charge":
                    try:
                        charge_val = int(filter_value)
                        df_filtered = df_filtered[df_filtered["Charge"] == charge_val]
                    except ValueError:
                        pass  # Invalid input, skip
                elif column in ["Hyperscore", "Observed M/Z"]:
                    try:
                        min_val = float(filter_value)
                        df_filtered = df_filtered[df_filtered[column] >= min_val]
                    except ValueError:
                        pass  # Invalid input, skip
                else:
                    # Text-based filtering (Assigned Modifications, Spectrum file, Header, etc.)
                    df_filtered = df_filtered[df_filtered[column].astype(str).str.contains(filter_value, case=False, na=False)]

        self.current_details_df = df_filtered
        self._show_details_table()

    def clear_details_filter(self):
        self._clear_filter(self.details_filter_input, self.active_details_filters,
                           self.details_active_filters_list)
        self.current_details_df = self.original_details_df.copy()
        self._show_details_table()

    # Drilldown
    def show_details_for_row(self, row, col):
        if self.summary_df.empty:
            return
        peptide = self.summary_table.item(row, 0).text()  # Peptide
        protein_id = self.summary_table.item(row, 1).text()  # Protein

        mask = (
            (self.raw_df["Peptide"] == peptide) &
            (self.raw_df["Protein"] == protein_id)
        )
        details_df = self.raw_df.loc[mask].copy()
        self.original_details_df = details_df
        self.current_details_df = details_df.copy()
        self._show_details_table()
        self._update_details_filter_dropdown()

        # Show details filters and hide summary filters
        self.summary_filter_widget.setVisible(False)
        self.details_filter_widget.setVisible(True)

        # Switch to details view
        self.stacked_widget.setCurrentIndex(1)

    def _show_details_table(self):
        df = self.current_details_df
        if df.empty:
            self.details_table.setRowCount(0)
            self.details_table.setColumnCount(0)
            return

        # Use visible_details_columns instead of hardcoded list
        # Preserve order: default columns first (in their original order), then additional columns sorted
        ordered_columns = []
        for col in self.default_details_columns:
            if col in self.visible_details_columns and col in df.columns:
                ordered_columns.append(col)

        # Add any additional visible columns (not in defaults) sorted alphabetically
        additional = sorted([col for col in self.visible_details_columns
                           if col not in self.default_details_columns and col in df.columns])
        ordered_columns.extend(additional)

        if not ordered_columns:
            logger.debug("No required columns found in details data")
            return

        display_df = df[ordered_columns].copy()

        # PERFORMANCE: Disable updates during bulk changes
        self.details_table.setUpdatesEnabled(False)

        # Temporarily disable sorting while updating
        self.details_table.setSortingEnabled(False)

        # Clear existing content
        self.details_table.clear()

        self.details_table.setRowCount(len(display_df))
        self.details_table.setColumnCount(len(display_df.columns))
        self.details_table.setHorizontalHeaderLabels(display_df.columns)

        # Known numeric columns for proper sorting
        known_numeric_columns = ["Charge", "Hyperscore", "Observed M/Z", "Calculated M/Z",
                                 "Calibrated Observed M/Z", "Peptide Length", "Retention"]

        # Fill data
        for row_idx in range(len(display_df)):
            for col_idx, col_name in enumerate(display_df.columns):
                val = display_df.iloc[row_idx, col_idx]
                item = QTableWidgetItem()

                # Handle numeric columns specially
                if col_name in known_numeric_columns:
                    try:
                        # Set numeric data for sorting
                        item.setData(Qt.ItemDataRole.DisplayRole, float(val))
                    except (ValueError, TypeError):
                        item.setText(str(val))
                else:
                    # Set full text for all non-numeric columns; tooltip for hover display
                    str_val = str(val) if val is not None else ""
                    item.setText(str_val)
                    item.setToolTip(str_val)

                self.details_table.setItem(row_idx, col_idx, item)

        # Resize columns to fit content; user can resize interactively
        self.details_table.resizeColumnsToContents()
        self._apply_details_column_visibility()

        # Re-enable sorting
        self.details_table.setSortingEnabled(True)

        # PERFORMANCE: Re-enable updates and refresh
        self.details_table.setUpdatesEnabled(True)
        self.details_table.viewport().update()

    def cleanup_worker(self):
        """Clean up any active worker threads and progress dialogs"""
        logger.debug("[DEBUG] Cleaning up worker and progress dialog...")

        try:
            if hasattr(self, '_current_worker') and self._current_worker is not None:
                logger.debug("[DEBUG] Terminating worker thread...")
                if self._current_worker.isRunning():
                    self._current_worker.terminate()
                    self._current_worker.wait(3000)  # Wait up to 3 seconds
                self._current_worker = None

            if hasattr(self, '_current_progress') and self._current_progress is not None:
                logger.debug("[DEBUG] Closing progress dialog...")
                self._current_progress.close()
                self._current_progress = None

        except Exception as e:
            logger.debug(f"[ERROR] Exception during cleanup: {e}")

    def closeEvent(self, event):
        """Handle widget close event"""
        logger.debug("[DEBUG] PSMSummaryWidget close event triggered")
        self.cleanup_worker()
        super().closeEvent(event)




class DraggablePSMSummaryWidget(PSMSummaryWidget):
    """Modified PSM Summary widget that supports dragging from details table"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.details_table.cellClicked.disconnect()  
        self.details_table.setDragEnabled(True)
        self.details_table.setDragDropMode(QTableWidget.DragDropMode.DragOnly)
        self.details_table.setDefaultDropAction(Qt.DropAction.CopyAction)
    
    def _show_details_table(self):
        """Override to setup drag functionality on the details table"""
        # Call parent method to setup table
        super()._show_details_table()
        
        # Override mouse events for drag functionality
        self.details_table.mousePressEvent = self._details_mouse_press_event
        self.details_table.mouseMoveEvent = self._details_mouse_move_event
    
    def _details_mouse_press_event(self, event):
        """Handle mouse press for drag initiation"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.details_table.drag_start_position = event.pos()
        # Call original mouse press event
        QTableWidget.mousePressEvent(self.details_table, event)
    
    def _details_mouse_move_event(self, event):
        """Handle mouse move for drag detection"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        
        if not hasattr(self.details_table, 'drag_start_position'):
            return
            
        if ((event.pos() - self.details_table.drag_start_position).manhattanLength() < 
            QApplication.startDragDistance()):
            return
        
        # Start drag operation
        self._start_details_drag(event)
    
    def _start_details_drag(self, event):
        """Start drag operation from details table"""
        # Get the row that was clicked
        row = self.details_table.rowAt(event.pos().y())
        if row < 0:
            return
        
        # Get row data from details table
        try:
            peptide_data = self._extract_peptide_data_from_row(row)
            if not peptide_data:
                return

            logger.debug(f"[DEBUG] Starting drag for peptide: {peptide_data.get('Modified Peptide', 'Unknown')}")

            # Create drag object
            drag = QDrag(self.details_table)
            mimeData = QMimeData()

            # Set display text
            display_text = f"{peptide_data.get('Modified Peptide', '')}\n(z={peptide_data.get('Charge', '')}, score={peptide_data.get('Hyperscore', '')})"
            mimeData.setText(display_text)
            
            # Set peptide data
            try:
                peptide_data_json = json.dumps(peptide_data, default=str)
                mimeData.setData("application/x-peptide-data", peptide_data_json.encode('utf-8'))
                logger.debug(f"[DEBUG] Added peptide data to mime: {len(peptide_data_json)} chars")
            except Exception as e:
                logger.debug(f"[DEBUG] Error encoding peptide data: {e}")
            
            # Set the mime data
            drag.setMimeData(mimeData)
            
            # Create drag pixmap
            try:
                pixmap = QPixmap(300, 50)
                pixmap.fill(Qt.GlobalColor.lightGray)
                painter = QPainter(pixmap)
                painter.setPen(Qt.GlobalColor.black)
                
                text = display_text.replace('\n', ' ')
                if len(text) > 40:
                    text = text[:37] + "..."
                
                painter.drawText(5, 20, text)
                painter.end()

                drag.setPixmap(pixmap)
                drag.setHotSpot(QPoint(10, 25))
            except Exception as e:
                logger.debug(f"[DEBUG] Error creating drag pixmap: {e}")

            # Execute drag
            result = drag.exec(Qt.DropAction.CopyAction)
            logger.debug(f"[DEBUG] Drag result: {result}")
            
        except Exception as e:
            logger.debug(f"[DEBUG] Error starting drag: {e}")
            traceback.print_exc()
    
    def _extract_peptide_data_from_row(self, row):
        """Extract peptide data from a details table row"""
        try:
            visible_row_data, row_data = self._match_details_row(row)
            if row_data is None:
                return None

            charge_val = int(visible_row_data.get("Charge", 1))
            hyperscore_val = float(visible_row_data.get("Hyperscore", 0))
            observed_mz_val = float(visible_row_data.get("Observed M/Z", 0))

            peptide_data = {
                # Primary field names
                'Peptide': row_data.get('Peptide', ''),
                'Modified Peptide': visible_row_data.get('Modified Peptide', ''),
                'Charge': charge_val,
                'Assigned Modifications': visible_row_data.get('Assigned Modifications', ''),
                'Parsed Modifications': row_data.get('Parsed Modifications', []),
                'Hyperscore': hyperscore_val,
                'Observed M/Z': observed_mz_val,
                'Spectrum file': row_data.get('Spectrum file', ''),
                'index': str(row_data.get('index', '')),
                'spectrum_file_path': row_data.get('spectrum_file_path', ''),
                'row_data': row_data,

                # Legacy aliases consumed by fragmentation_tab.py
                'peptide': row_data.get('Peptide', ''),
                'charge': charge_val,
                'parsed_modifications': row_data.get('Parsed Modifications', []),
            }

            return peptide_data

        except Exception as e:
            logger.debug(f"[DEBUG] Error extracting peptide data: {e}")
            traceback.print_exc()
            return None