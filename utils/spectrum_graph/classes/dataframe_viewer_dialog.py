import pandas as pd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QTabWidget, QCheckBox,
    QHeaderView, QSizePolicy
)
from PyQt6.QtCore import Qt
from utils.style.style import StyleSheet, EditorConstants
from PyQt6.QtGui import QColor

class DataframeViewerDialog(QDialog):
    def __init__(self, matched_df, theoretical_df=None, details_df=None, parent=None, default_filename="fragment_data"):
        super().__init__(parent)
        self.setWindowTitle("Fragment Data Viewer")
        self.resize(1200, 800)
        
        # Apply the new GUI styling
        self.setStyleSheet(StyleSheet.build_gui_style())
        
        # Store original dataframes (unfiltered) FIRST before any other setup
        self.original_matched_df = matched_df.copy() if matched_df is not None else pd.DataFrame()
        self.original_theoretical_df = theoretical_df.copy() if theoretical_df is not None else pd.DataFrame()
        self.original_details_df = details_df.copy() if details_df is not None else pd.DataFrame()

        # Store current filtered dataframes (what's displayed)
        self.current_matched_df = self.original_matched_df.copy()
        self.current_theoretical_df = self.original_theoretical_df.copy()
        
        self.default_filename = default_filename
        
        # Now setup UI
        self._setup_ui()
        self._apply_initial_filters()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Add filter controls with updated styling
        filter_layout = QHBoxLayout()
        
        # Matched fragments filter
        self.matched_filter_checkbox = QCheckBox("Show only matched fragments")
        self.matched_filter_checkbox.setChecked(False)
        self.matched_filter_checkbox.stateChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.matched_filter_checkbox)
        
        # Theoretical fragments filter (only if theoretical data exists)
        if not self.original_theoretical_df.empty:
            self.theoretical_filter_checkbox = QCheckBox("Show only Isotope = 0 (Theoretical)")
            self.theoretical_filter_checkbox.setChecked(True)  # Default to filtered
            self.theoretical_filter_checkbox.stateChanged.connect(self._apply_filters)
            filter_layout.addWidget(self.theoretical_filter_checkbox)
        
        filter_layout.addStretch()  # Push filters to the left
        layout.addLayout(filter_layout)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        # Connect tab change event to update filter availability
        self.tab_widget.currentChanged.connect(lambda _: self._update_filter_states())
        layout.addWidget(self.tab_widget)
        
        # Use the styling method to create tables
        self.matched_table = self._create_table_for_dataframe(self.current_matched_df, "Matched Fragments")
        self.tab_widget.addTab(self.matched_table, "Matched Fragments")
        
        if not self.original_theoretical_df.empty:
            self.theoretical_table = self._create_table_for_dataframe(self.current_theoretical_df, "Theoretical Fragments")
            self.tab_widget.addTab(self.theoretical_table, "Theoretical Fragments")

        # Update filter states based on initial tab
        self._update_filter_states()
        
        # Simple buttons layout - only Close button now
        button_layout = QHBoxLayout()
        
        # Add note about export location
        export_note = QLabel("Use File → Export menu to save data")
        export_note.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
        button_layout.addWidget(export_note)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)

    def _update_filter_states(self):
        """Update which filters are enabled based on current tab"""
        current_tab = self.tab_widget.currentIndex()
        
        # Enable/disable matched fragments filter based on current tab
        if current_tab == 0:  # Matched Fragments tab
            self.matched_filter_checkbox.setEnabled(True)
            if hasattr(self, 'theoretical_filter_checkbox'):
                self.theoretical_filter_checkbox.setEnabled(False)
        elif current_tab == 1 and hasattr(self, 'theoretical_filter_checkbox'):  # Theoretical Fragments tab
            self.matched_filter_checkbox.setEnabled(False)
            self.theoretical_filter_checkbox.setEnabled(True)

    def _apply_initial_filters(self):
        """Apply initial filters when dialog opens"""
        # Apply theoretical filter by default (Isotope = 0 only)
        if not self.original_theoretical_df.empty and hasattr(self, 'theoretical_filter_checkbox'):
            if self.theoretical_filter_checkbox.isChecked():
                self._filter_theoretical_data()
        
        # Update tables
        self._populate_tables()

    def _apply_filters(self):
        """Apply current filter settings"""
        current_tab = self.tab_widget.currentIndex()
        
        # Reset to original data
        self.current_matched_df = self.original_matched_df.copy()
        self.current_theoretical_df = self.original_theoretical_df.copy()
        
        # Apply matched fragments filter - only when on matched fragments tab
        if (current_tab == 0 and 
            hasattr(self, 'matched_filter_checkbox') and 
            self.matched_filter_checkbox.isChecked()):
            self._filter_matched_data()
        
        # Apply theoretical fragments filter - only when on theoretical fragments tab
        if (current_tab == 1 and
            hasattr(self, 'theoretical_filter_checkbox') and 
            self.theoretical_filter_checkbox.isChecked() and 
            not self.original_theoretical_df.empty):
            self._filter_theoretical_data()
        
        # Update only the current tab's table
        if current_tab == 0:
            self._populate_table(self.matched_table, self.current_matched_df)
        elif current_tab == 1 and hasattr(self, 'theoretical_table'):
            self._populate_table(self.theoretical_table, self.current_theoretical_df)

    def _filter_matched_data(self):
        """Filter matched fragments to show only matched peaks"""
        if 'Matched' in self.current_matched_df.columns:
            # Filter out 'No Match' entries
            mask = (
                self.current_matched_df['Matched'].notna() & 
                (self.current_matched_df['Matched'] != 'No Match') &
                (pd.to_numeric(self.current_matched_df['Matched'], errors='coerce').notna())
            )
            self.current_matched_df = self.current_matched_df[mask].copy()

    def _filter_theoretical_data(self):
        """Filter theoretical fragments to show only Isotope = 0"""
        if 'Isotope' in self.current_theoretical_df.columns:
            # Convert Isotope column to numeric and filter for 0
            isotope_numeric = pd.to_numeric(self.current_theoretical_df['Isotope'], errors='coerce')
            mask = (isotope_numeric == 0)
            self.current_theoretical_df = self.current_theoretical_df[mask].copy()

    def _populate_tables(self):
        """Populate both tables with current (filtered) data"""
        # Populate matched fragments table
        self._populate_table(self.matched_table, self.current_matched_df)
        
        # Populate theoretical fragments table if it exists
        if hasattr(self, 'theoretical_table') and not self.original_theoretical_df.empty:
            self._populate_table(self.theoretical_table, self.current_theoretical_df)

    def _populate_table(self, table_widget, dataframe):
        """Populate a table widget with dataframe data"""
        if dataframe.empty:
            table_widget.setRowCount(0)
            table_widget.setColumnCount(0)
            return
        
        # Set table dimensions
        table_widget.setRowCount(len(dataframe))
        table_widget.setColumnCount(len(dataframe.columns))
        table_widget.setHorizontalHeaderLabels(dataframe.columns.tolist())
        
        # Populate table with data
        for row in range(len(dataframe)):
            for col in range(len(dataframe.columns)):
                value = dataframe.iloc[row, col]
                # Handle different data types
                if pd.isna(value):
                    item_text = ""
                elif isinstance(value, (int, float)):
                    if isinstance(value, float):
                        item_text = f"{value:.6f}" if abs(value) < 1000 else f"{value:.2f}"
                    else:
                        item_text = str(value)
                else:
                    item_text = str(value)
                
                item = QTableWidgetItem(item_text)
                table_widget.setItem(row, col, item)
        
        # Auto-resize columns to content
        table_widget.resizeColumnsToContents()
        
        table_widget.setAlternatingRowColors(False)


    def _create_table_for_dataframe(self, df, tab_name):
        """Create a table widget for displaying a dataframe with new consistent styling"""
        table_widget = QTableWidget()
        
        # Apply the updated table styling
        StyleSheet.apply_table_styling(table_widget)
        
        if df.empty:
            table_widget.setRowCount(1)
            table_widget.setColumnCount(1)
            table_widget.setHorizontalHeaderLabels(["No Data"])
            empty_item = QTableWidgetItem("No data available")
            empty_item.setForeground(QColor(EditorConstants.TEXT_COLOR()))
            table_widget.setItem(0, 0, empty_item)
        else:
            # Reorder columns to put Ion Series Type near the beginning for better visibility
            column_order = []
            if 'Ion Series Type' in df.columns:
                # Put Ion Series Type after Ion Type for logical grouping
                for col in df.columns:
                    if col == 'Ion Type':
                        column_order.append(col)
                        if 'Ion Series Type' not in column_order:
                            column_order.append('Ion Series Type')
                    elif col != 'Ion Series Type':
                        column_order.append(col)
                df_reordered = df[column_order]
            else:
                df_reordered = df
            
            table_widget.setRowCount(len(df_reordered))
            table_widget.setColumnCount(len(df_reordered.columns))
            table_widget.setHorizontalHeaderLabels(df_reordered.columns.tolist())
            
            # Populate table data with theme-aware text colors
            for row_idx, (_, row) in enumerate(df_reordered.iterrows()):
                for col_idx, value in enumerate(row):
                    # Handle different data types appropriately
                    if pd.isna(value):
                        display_value = ""
                    elif isinstance(value, float):
                        display_value = f"{value:.4f}" if abs(value) < 1000 else f"{value:.2e}"
                    else:
                        display_value = str(value)
                    
                    item = QTableWidgetItem(display_value)
                    item.setForeground(QColor(EditorConstants.TEXT_COLOR()))
                    table_widget.setItem(row_idx, col_idx, item)
        
        # Configure table appearance
        header = table_widget.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        # Set size policy
        table_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        return table_widget
    
