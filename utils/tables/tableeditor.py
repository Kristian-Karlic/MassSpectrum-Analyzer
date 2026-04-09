import pandas as pd
import os
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidgetItem, QMessageBox, QHeaderView, QAbstractItemView,  QFileDialog)

from PyQt6.QtGui import QKeySequence, QShortcut
from utils.style.style import EditorConstants
from utils.tables.Color_selection import ColorDelegate
from utils.tables.Custom_ion_series import BaseIonComboDelegate, RestrictionDelegate
from utils.tables.excel_table import ExcelLikeTableWidget, create_search_bar
import shutil
from PyQt6.QtCore import QTimer, pyqtSignal

logger = logging.getLogger(__name__)

class TableEditorDialog(QDialog):
    data_changed = pyqtSignal()
    def __init__(self, data_type, data_df, file_path, parent=None):
        """
        Create a table editor dialog
        
        Args:
            data_type: "modifications", "diagnostic_ions", or "custom_ion_series"
            data_df: DataFrame with the current data
            file_path: Path to the CSV file for saving
            parent: Parent widget
        """
        super().__init__(parent)
        self.data_type = data_type
        self.original_df = data_df.copy()
        self.current_df = data_df.copy()
        self.file_path = file_path
        
        self.setWindowTitle(f"Edit {data_type.replace('_', ' ').title()}")
        self.resize(600, 500)
        
        # Apply dialog styling
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
        """)
        self._setup_ui()
        self._populate_table()
        self._setup_shortcuts()

        # Debounce timer for data_changed signal
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self.data_changed.emit)

        # Connect after initial population so _populate_table doesn't trigger it
        self.table.itemChanged.connect(self._on_item_changed)
            
    def _setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)
        
        # Create table
        self.table = ExcelLikeTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setAlternatingRowColors(False)

        # Set proper column sizing using constants
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            
        # Set up columns based on data type 
        if self.data_type == "modifications":
            self.table.setColumnCount(2)
            self.table.setHorizontalHeaderLabels(["Name", "Mass"])
            self.table.setColumnWidth(0, EditorConstants.NAME_COLUMN_WIDTH())
            self.table.setColumnWidth(1, EditorConstants.MASS_COLUMN_WIDTH())  
        elif self.data_type == "diagnostic_ions":
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["Name", "HTML Name", "Mass", "Color"])
            self.table.setColumnWidth(0, EditorConstants.NAME_COLUMN_WIDTH())  
            self.table.setColumnWidth(1, EditorConstants.HTML_NAME_COLUMN_WIDTH())  
            self.table.setColumnWidth(2, EditorConstants.MASS_COLUMN_WIDTH()) 
            self.table.setColumnWidth(3, EditorConstants.COLOR_COLUMN_WIDTH()) 
            
            # Set up color delegate for diagnostic ions
            self.color_delegate = ColorDelegate()
            self.table.setItemDelegateForColumn(3, self.color_delegate)
            
        elif self.data_type == "custom_ion_series":
            self.table.setColumnCount(5)
            self.table.setHorizontalHeaderLabels(["Base Ion", "Series Name", "Mass Offset", "Color", "Restriction"])
            self.table.setColumnWidth(0, EditorConstants.BASE_ION_COLUMN_WIDTH()) 
            self.table.setColumnWidth(1, EditorConstants.SERIES_NAME_COLUMN_WIDTH())  
            self.table.setColumnWidth(2, EditorConstants.MASS_OFFSET_COLUMN_WIDTH()) 
            self.table.setColumnWidth(3, EditorConstants.COLOR_COLUMN_WIDTH()) 
            self.table.setColumnWidth(4, 140)
            
            # Set up delegates for custom ion series
            self.base_ion_delegate = BaseIonComboDelegate(["b","y","a","c","x","z","z+1","c-1","MH","d","w","v"], self)
            self.table.setItemDelegateForColumn(0, self.base_ion_delegate)
            
            self.color_delegate = ColorDelegate()
            self.table.setItemDelegateForColumn(3, self.color_delegate)
            
            self.restriction_delegate = RestrictionDelegate()
            self.table.setItemDelegateForColumn(4, self.restriction_delegate)
                
        # Apply styling with constants
        self.table.setStyleSheet(EditorConstants.get_table_style())

        # Search bar
        self.search_input = create_search_bar(self.table, self, "Search entries...")
        self.search_input.setStyleSheet(EditorConstants.get_table_style())
        layout.addWidget(self.search_input)

        layout.addWidget(self.table)

        # Create buttons
        button_layout = QHBoxLayout()
        
        self.add_row_btn = QPushButton("Add Row")
        self.add_row_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        self.add_row_btn.clicked.connect(self.add_row)
        button_layout.addWidget(self.add_row_btn)
        
        self.delete_row_btn = QPushButton("Delete Row")
        self.delete_row_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        self.delete_row_btn.clicked.connect(self.delete_row)
        button_layout.addWidget(self.delete_row_btn)
        
        self.duplicate_row_btn = QPushButton("Duplicate Row")
        self.duplicate_row_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.duplicate_row_btn.clicked.connect(self.duplicate_row)
        button_layout.addWidget(self.duplicate_row_btn)

        button_layout.addStretch()
        
        self.import_btn = QPushButton("Import CSV")
        self.import_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.import_btn.clicked.connect(self.import_csv)
        button_layout.addWidget(self.import_btn)
        
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.export_btn.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_btn)
        
        layout.addLayout(button_layout)
        
        # Save/Cancel buttons
        save_cancel_layout = QHBoxLayout()
        save_cancel_layout.addStretch()
        
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        self.save_btn.clicked.connect(self.save_changes)
        save_cancel_layout.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.cancel_btn.clicked.connect(self.reject)
        save_cancel_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(save_cancel_layout)
        
        try:
            large_spacing = int(EditorConstants.PADDING_LARGE().replace('px', ''))
            medium_spacing = int(EditorConstants.PADDING_MEDIUM().replace('px', ''))
            
            layout.setSpacing(large_spacing)
            button_layout.setSpacing(medium_spacing)
            save_cancel_layout.setSpacing(medium_spacing)
        except (ValueError, AttributeError):
            # Fallback to default values if conversion fails
            layout.setSpacing(8)
            button_layout.setSpacing(6)
            save_cancel_layout.setSpacing(6)

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # Ctrl+N for new row
        new_shortcut = QShortcut(QKeySequence.StandardKey.New, self)
        new_shortcut.activated.connect(self.add_row)
        
    def _refilter(self):
        """Re-apply the current search filter after row changes."""
        if hasattr(self, 'search_input'):
            self.search_input._filter_func(self.search_input.text())

    def _populate_table(self):
        """Populate the table with current data"""
        self.table.setRowCount(len(self.current_df))

        for row in range(len(self.current_df)):
            for col in range(len(self.current_df.columns)):
                value = self.current_df.iloc[row, col]

                # Standard text items for all columns (no more checkbox handling)
                item = QTableWidgetItem(str(value))
                self.table.setItem(row, col, item)
        self._refilter()
                
    def add_row(self):
        """Add a new empty row"""
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        
        # Add default values based on data type
        if self.data_type == "modifications":
            self.table.setItem(row_count, 0, QTableWidgetItem("New Modification"))
            self.table.setItem(row_count, 1, QTableWidgetItem("0.0"))
        elif self.data_type == "diagnostic_ions":
            self.table.setItem(row_count, 0, QTableWidgetItem("New Ion"))       # Name
            self.table.setItem(row_count, 1, QTableWidgetItem(""))              # HTML Name (empty)
            self.table.setItem(row_count, 2, QTableWidgetItem("0.0"))           # Mass
            self.table.setItem(row_count, 3, QTableWidgetItem("#000000"))       # Color (black)
        elif self.data_type == "custom_ion_series":
            self.table.setItem(row_count, 0, QTableWidgetItem("b"))             # Base Ion (default to b)
            self.table.setItem(row_count, 1, QTableWidgetItem("New Series"))    # Series Name
            self.table.setItem(row_count, 2, QTableWidgetItem("0.0"))           # Mass Offset
            self.table.setItem(row_count, 3, QTableWidgetItem("#000000"))       # Color (black)
            self.table.setItem(row_count, 4, QTableWidgetItem(""))              # Restriction (none)
            
        # Select the new row
        self.table.selectRow(row_count)
        self._refilter()

    def delete_row(self):
        """Delete the selected row(s)"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
            
        if not selected_rows:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select a row to delete.",
                QMessageBox.StandardButton.Ok
            )
            return
            
        # Confirm deletion
        if len(selected_rows) == 1:
            message = "Are you sure you want to delete the selected row?"
        else:
            message = f"Are you sure you want to delete {len(selected_rows)} rows?"
            
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Remove rows in reverse order to maintain indices
            for row in sorted(selected_rows, reverse=True):
                self.table.removeRow(row)
            self._refilter()
                
    def duplicate_row(self):
        """Duplicate the selected row"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select a row to duplicate.",
                QMessageBox.StandardButton.Ok
            )
            return
            
        # Insert new row after current
        self.table.insertRow(current_row + 1)
        
        # Copy data from current row
        for col in range(self.table.columnCount()):
            original_item = self.table.item(current_row, col)
            if original_item:
                new_item = QTableWidgetItem(original_item.text())
                self.table.setItem(current_row + 1, col, new_item)
                
        # Select the new row
        self.table.selectRow(current_row + 1)
        
    def import_csv(self):
        """Import data from a CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import {self.data_type.replace('_', ' ').title()}",
            "",
            "CSV files (*.csv);;All files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            # Load the CSV
            imported_df = pd.read_csv(file_path)
            
            # Validate columns
            expected_columns = list(self.current_df.columns)
            if list(imported_df.columns) != expected_columns:
                QMessageBox.warning(
                    self,
                    "Invalid Format",
                    f"CSV must have columns: {', '.join(expected_columns)}",
                    QMessageBox.StandardButton.Ok
                )
                return
                
            # Ask if user wants to replace or append
            reply = QMessageBox.question(
                self,
                "Import Mode",
                "Do you want to replace the current data?\n"
                "Click 'No' to append to current data.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                # Replace
                self.current_df = imported_df.copy()
            else:
                # Append
                self.current_df = pd.concat([self.current_df, imported_df], ignore_index=True)
                
            # Refresh table
            self._populate_table()
            QMessageBox.information(
                self,
                "Success",
                f"Successfully imported {len(imported_df)} rows.",
                QMessageBox.StandardButton.Ok
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import CSV file:\n{str(e)}",
                QMessageBox.StandardButton.Ok
            )
            
    def export_csv(self):
        """Export current table data to CSV"""
        data = self._get_table_data()
        if data.empty:
            QMessageBox.information(
                self,
                "No Data",
                "No data to export.",
                QMessageBox.StandardButton.Ok
            )
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.data_type.replace('_', ' ').title()}",
            f"{self.data_type}.csv",
            "CSV files (*.csv);;All files (*.*)"
        )
        
        if file_path:
            try:
                data.to_csv(file_path, index=False)
                QMessageBox.information(
                    self,
                    "Success",
                    f"Data exported to {file_path}",
                    QMessageBox.StandardButton.Ok
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Failed to export data:\n{str(e)}",
                    QMessageBox.StandardButton.Ok
                )
                
    def _get_table_data(self):
        """Get current table data as DataFrame"""
        rows = []
        for row in range(self.table.rowCount()):
            row_data = []
            has_data = False
            
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                
                # All columns are now standard text items
                value = item.text().strip() if item else ""
                row_data.append(value)
                    
                if value:
                    has_data = True
                    
            if has_data:  # Only include rows with data
                # For diagnostic ions, auto-fill HTML Name if empty
                if self.data_type == "diagnostic_ions" and len(row_data) >= 4:
                    if not row_data[1] and row_data[0]:  # HTML Name empty but Name exists
                        row_data[1] = row_data[0]  # Copy Name to HTML Name
                rows.append(row_data)
                
        if not rows:
            return pd.DataFrame(columns=self.current_df.columns)
            
        # Ensure we're creating DataFrame with the correct number of columns
        expected_columns = list(self.current_df.columns)
        
        # Pad or trim rows to match expected column count
        for i, row in enumerate(rows):
            if len(row) < len(expected_columns):
                # Pad with empty strings
                padding = ["" for j in range(len(row), len(expected_columns))]
                rows[i] = row + padding
            elif len(row) > len(expected_columns):
                # Trim to expected length
                rows[i] = row[:len(expected_columns)]
        
        df = pd.DataFrame(rows, columns=expected_columns)
        
        # Convert numeric columns
        try:
            if 'Mass' in df.columns:
                df['Mass'] = pd.to_numeric(df['Mass'], errors='coerce')
            if 'Mass Offset' in df.columns:
                df['Mass Offset'] = pd.to_numeric(df['Mass Offset'], errors='coerce')
        except Exception as e:
            logger.debug(f"Warning: Could not convert numeric column: {e}")
            
        return df

            
    def save_changes(self):
        """Save changes to the CSV file"""
        try:
            # Get current table data
            updated_df = self._get_table_data()
            
            # Validate data
            if updated_df.empty:
                reply = QMessageBox.question(
                    self,
                    "Empty Data",
                    "The table is empty. Do you want to save an empty file?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
                    
            # Check for duplicate names - SKIP for custom_ion_series
            if self.data_type != "custom_ion_series":  # Don't check duplicates for custom ion series
                name_column = None
                if 'Name' in updated_df.columns:
                    name_column = 'Name'

                if name_column:
                    duplicates = updated_df[updated_df[name_column].duplicated()]
                    if not duplicates.empty:
                        QMessageBox.warning(
                            self,
                            "Duplicate Names",
                            f"Found duplicate {name_column.lower()}s:\n{', '.join(duplicates[name_column].tolist())}\n"
                            f"Please ensure all {name_column.lower()}s are unique.",
                            QMessageBox.StandardButton.Ok
                        )
                        return

            # Validate custom ion series names don't use reserved characters
            if self.data_type == "custom_ion_series" and 'Series Name' in updated_df.columns:
                reserved_chars = {'*', '~', '^'}
                bad_names = []
                for name in updated_df['Series Name']:
                    if any(ch in str(name) for ch in reserved_chars):
                        bad_names.append(str(name))
                if bad_names:
                    QMessageBox.warning(
                        self,
                        "Reserved Characters",
                        f"Series names cannot contain *, ~ or ^ (reserved for modification neutral/remainder ions):\n"
                        f"{', '.join(bad_names)}\n\nPlease rename these series.",
                        QMessageBox.StandardButton.Ok
                    )
                    return
                        
            # Create backup of original file if it exists
            if os.path.exists(self.file_path):
                backup_path = f"{self.file_path}.backup"

                shutil.copy2(self.file_path, backup_path)
                
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            
            # Save to CSV
            updated_df.to_csv(self.file_path, index=False)
            
            QMessageBox.information(
                self,
                "Success",
                f"Changes saved successfully to {self.file_path}",
                QMessageBox.StandardButton.Ok
            )
            
            # Update the parent's data
            self.current_df = updated_df
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save changes:\n{str(e)}",
                QMessageBox.StandardButton.Ok
            )
            
    def get_updated_data(self):
        """Return the updated DataFrame"""
        return self.current_df

    def get_data(self):
        """Alias for get_updated_data for compatibility"""
        return self.get_updated_data()
    
    def _on_item_changed(self):
        """Emit signal when table data changes"""
        self._update_timer.stop()
        self._update_timer.start(500)