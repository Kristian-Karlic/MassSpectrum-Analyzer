"""
Utilities module - re-exports from focused submodules for backward compatibility.

Classes are organized into:
  utility_classes/csv_loader.py       - CSVLoader, DataGatherer
  utility_classes/input_validation.py - InputValidator
  utility_classes/experiment_manager.py - ExperimentManager
  utility_classes/cache_manager.py    - CacheManager
  utility_classes/data_processing.py  - DataProcessingUtils, IonTypeGenerator, IonCollectionUtils
  utility_classes/window_manager.py   - WindowSizeManager

Classes still defined here:
  TableUtils, FileTypeUtils, DataLoader, UIHelpers, FileProcessingUtils,
  MockDataGenerator, SimplePasteTable
"""

import logging
import pandas as pd
import os
import numpy as np
from typing import List, Tuple
from PyQt6.QtWidgets import (
    QTableWidget, QMessageBox, QProgressDialog,
    QTableWidgetItem, QHeaderView, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt
from utils.utility_classes.filetypedetector import FileTypeDetector
from utils.utility_classes.toaster import QToaster
from utils.style.style import StyleSheet, EditorConstants

# Re-exports from split modules
from utils.utility_classes.csv_loader import CSVLoader, DataGatherer
from utils.utility_classes.input_validation import InputValidator
from utils.utility_classes.experiment_manager import ExperimentManager
from utils.utility_classes.cache_manager import CacheManager
from utils.utility_classes.data_processing import DataProcessingUtils, IonTypeGenerator, IonCollectionUtils
from utils.utility_classes.window_manager import WindowSizeManager

logger = logging.getLogger(__name__)


class TableUtils:
    """Utility class for common table operations"""

    @staticmethod
    def populate_two_column_table(table, data_pairs, block_signals=True):
        """
        Populate a two-column table with data pairs.

        Args:
            table: QTableWidget to populate
            data_pairs: List of (col1_value, col2_value) tuples
            block_signals: If True, block itemChanged signals during population
        """
        if not data_pairs:
            return

        if block_signals:
            table.blockSignals(True)

        try:
            required_rows = len(data_pairs)
            if table.rowCount() < required_rows:
                table.setRowCount(required_rows)

            table.clearContents()

            for row, (col1_val, col2_val) in enumerate(data_pairs):
                item1 = QTableWidgetItem(str(col1_val))
                table.setItem(row, 0, item1)

                item2 = QTableWidgetItem(str(col2_val))
                table.setItem(row, 1, item2)

            logger.debug(f"[DEBUG] Populated table with {len(data_pairs)} data pairs")

        finally:
            if block_signals:
                table.blockSignals(False)

    @staticmethod
    def extract_mz_intensity_from_table(table: QTableWidget) -> List[Tuple[float, float]]:
        """Extract m/z and intensity values from table"""
        values = []
        for row in range(table.rowCount()):
            mz_item = table.item(row, 0)
            int_item = table.item(row, 1)
            if mz_item and int_item:
                try:
                    mz = float(mz_item.text())
                    intensity = float(int_item.text())
                    values.append((mz, intensity))
                except ValueError:
                    continue
        return values

    @staticmethod
    def create_basic_table(row_count, col_count, headers, min_width, parent=None, max_width=None):
        """Create a basic table widget with consistent sizing that fits container"""
        table = QTableWidget(row_count, col_count, parent)
        table.setHorizontalHeaderLabels(headers)

        table.setMinimumWidth(min_width)
        if max_width:
            table.setMaximumWidth(max_width)

        table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setAlternatingRowColors(False)

        StyleSheet.apply_table_styling(table)

        return table


class FileTypeUtils:
    """Utility class for file type detection and validation"""

    _DISPLAY_LABELS = {
        'MSFragger': 'MSFragger (psm.tsv)',
        'MSFragger_PreValidation': 'MSFragger (pre-validation)',
        'MaxQuant': 'MaxQuant',
        'MetaMorpheus': 'MetaMorpheus',
        'Byonic': 'Byonic',
        'PEAKS': 'PEAKS',
        'Sage': 'Sage',
        'Percolator': 'Percolator',
        'mzIdentML': 'mzIdentML',
        'XTandem': 'X!Tandem',
        'IdXML': 'IdXML',
        'pepXML': 'pepXML',
    }

    @staticmethod
    def determine_raw_file_type(filename: str) -> str:
        """Determine raw file type from filename"""
        if filename.lower().endswith('.raw'):
            return ".raw"
        elif filename.lower().endswith('.mzml'):
            return ".mzML"
        return ""

    @staticmethod
    def determine_search_file_type(file_path: str) -> str:
        """Determine search file type by examining headers.

        Delegates to FileTypeDetector and maps the result to a UI-friendly label.
        """
        raw_key = FileTypeDetector.detect_search_file_type(file_path)
        if raw_key is None:
            return "Unknown"
        return FileTypeUtils._DISPLAY_LABELS.get(raw_key, raw_key)

    @staticmethod
    def strip_file_extension(filename: str) -> str:
        """Strip file extension from filename"""
        base, _ = os.path.splitext(filename)
        return base


class DataLoader:
    """Utility class for loading data with fallbacks"""

    @staticmethod
    def load_csv_with_fallback(file_path: str, columns: List[str], data_type_name: str) -> pd.DataFrame:
        """Load CSV with fallback to empty DataFrame"""
        try:
            if file_path.endswith('.csv'):
                data = pd.read_csv(file_path)
            else:
                data = CSVLoader.load_csv_with_conversion(file_path, [(col, str) for col in columns])
            logger.info(f"Loaded {len(data)} {data_type_name}")
            return data
        except Exception as e:
            logger.warning(f"Could not load {data_type_name}, using empty structure: {e}")
            return pd.DataFrame(columns=columns)

    @staticmethod
    def create_file_paths_dataframe(raw_files: List[str], search_files: List[str],
                                    columns: List[str]) -> pd.DataFrame:
        """Create file paths DataFrame from raw and search files"""
        max_count = max(len(raw_files), len(search_files))
        data = []

        for i in range(max_count):
            raw_dir_path, raw_fname, raw_file_type = ("", "", "")
            search_dir_path, search_fname, search_file_type = ("", "", "")

            if i < len(raw_files):
                raw_dir_path, raw_fname = os.path.split(raw_files[i])
                raw_file_type = FileTypeUtils.determine_raw_file_type(raw_fname)

            if i < len(search_files):
                search_dir_path, search_fname = os.path.split(search_files[i])
                search_file_type = FileTypeUtils.determine_search_file_type(search_files[i])

            data.append([
                raw_dir_path, raw_fname, raw_file_type,
                search_dir_path, search_fname, search_file_type
            ])

        return pd.DataFrame(data, columns=columns)


class UIHelpers:
    """Utility class for common UI operations"""

    @staticmethod
    def show_validation_error(parent, title: str, message: str):
        """Show a standardized validation error message"""
        QMessageBox.warning(parent, title, message, QMessageBox.StandardButton.Ok)

    @staticmethod
    def show_success_message(parent, message: str):
        """Show a success toast message"""
        QToaster(parent).show_message(message)

    @staticmethod
    def create_default_row_data(charge: int, scan_number: str = "", filename: str = "") -> dict:
        """Create default row data for metadata"""
        if scan_number and filename:
            protein_text = f"Direct scan {scan_number} from {filename}"
        else:
            protein_text = "N/A"

        return {
            "Observed M/Z": 0.0,
            "Charge": charge,
            "Protein": protein_text,
            "Hyperscore": 0.0,
            "Scan": scan_number,
            "File": filename
        }

    @staticmethod
    def create_progress_dialog(parent, title, text, maximum, cancelable=True):
        """Create a styled progress dialog"""
        progress = QProgressDialog(text, "Cancel" if cancelable else None, 0, maximum, parent)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        try:
            progress.setStyleSheet(EditorConstants.get_progress_bar_style())
        except AttributeError:
            progress.setStyleSheet(f"""
                QProgressDialog {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                    color: {EditorConstants.TEXT_COLOR()};
                }}
                QProgressBar {{
                    background-color: {EditorConstants.GRAY_100()};
                    border: 1px solid {EditorConstants.GRAY_200()};
                    border-radius: 4px;
                    text-align: center;
                    min-height: 20px;
                }}
                QProgressBar::chunk {{
                    background-color: {EditorConstants.PRIMARY_BLUE()};
                    border-radius: 3px;
                    margin: 1px;
                }}
            """)

        if not cancelable:
            progress.setCancelButton(None)

        return progress


class FileProcessingUtils:
    """Utility class for file processing operations"""

    MSFRAGGER_COLUMNS = FileTypeDetector.MSFRAGGER_COLUMNS

    @staticmethod
    def process_search_files(files: List[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
        """Process search files and return valid/invalid files"""
        valid_files = []
        invalid_files = []

        for file in files:
            file_type = FileTypeDetector.detect_search_file_type(file)
            if file_type is None:
                invalid_files.append(os.path.basename(file))
            else:
                valid_files.append((file_type, file))

        return valid_files, invalid_files

    @staticmethod
    def process_msfragger_folder(folder_path: str) -> Tuple[List[str], List[str]]:
        """Process MSFragger folder and return valid/invalid PSM files"""
        matched_psm_files = []
        invalid_files = []

        for root, dirs, files in os.walk(folder_path):
            if "psm.tsv" in files:
                file_path = os.path.join(root, "psm.tsv")
                try:
                    df = pd.read_csv(file_path, sep='\t', nrows=0)
                    if df.columns.tolist()[:11] == FileProcessingUtils.MSFRAGGER_COLUMNS:
                        matched_psm_files.append(file_path)
                    else:
                        invalid_files.append(os.path.basename(file_path))
                except Exception:
                    invalid_files.append(os.path.basename(file_path))

        return matched_psm_files, invalid_files

    @staticmethod
    def create_file_type_summary(valid_files: List[Tuple[str, str]]) -> str:
        """Create a summary message for loaded file types"""
        file_type_counts = {}
        for file_type, _ in valid_files:
            file_type_counts[file_type] = file_type_counts.get(file_type, 0) + 1

        message_parts = [f"{count} {ftype.capitalize()} file(s)"
                         for ftype, count in file_type_counts.items()]
        return f"Successfully loaded {', '.join(message_parts)}."

    @staticmethod
    def validate_and_load_raw_files(files: List[str]) -> Tuple[List[str], List[str]]:
        """Validate and load raw files, returning valid and invalid lists"""
        return FileTypeDetector.filter_raw_files(files)

    @staticmethod
    def update_raw_file_dropdown(combo_box, raw_files: List[str], current_text: str = ""):
        """Update raw file dropdown with available files"""
        combo_box.clear()

        if not raw_files:
            combo_box.addItem("No raw files loaded")
            combo_box.setEnabled(False)
            return

        for file_path in raw_files:
            filename = os.path.basename(file_path)
            combo_box.addItem(filename)

        combo_box.setEnabled(True)

        if current_text:
            index = combo_box.findText(current_text)
            if index >= 0:
                combo_box.setCurrentIndex(index)

        logger.debug(f"[DEBUG] Updated raw file dropdown with {len(raw_files)} files")


class MockDataGenerator:
    """Utility class for generating mock data"""

    @staticmethod
    def generate_mock_spectrum_data() -> Tuple[pd.DataFrame, dict]:
        """Generate mock spectrum data for initial display"""

        np.random.seed(42)

        mz_values = np.array([
            159.0764, 290.1169, 387.1697, 500.2537,
            560.2749, 489.2377, 358.1973, 261.1445, 148.0604
        ])

        intensities = np.array([
            12500, 8900, 15600, 22100, 7800,
            18900, 5400, 11200, 16700
        ])

        matched_data = pd.DataFrame({
            'm/z': mz_values,
            'intensity': intensities,
            'Matched': ['No Match'] * len(mz_values),
            'Ion Number': [None] * len(mz_values),
            'Ion Type': [None] * len(mz_values),
            'Fragment Sequence': [None] * len(mz_values),
            'Neutral Loss': ['None'] * len(mz_values),
            'Charge': [1] * len(mz_values),
            'Isotope': [0] * len(mz_values),
            'Color': ['grey'] * len(mz_values),
            'Base Type': [None] * len(mz_values),
            'error_ppm': [None] * len(mz_values)
        })

        mock_row_data = {
            "Observed M/Z": 647.7727,
            "Charge": 2,
            "Protein": "Sample Protein",
            "Hyperscore": 20
        }

        return matched_data, mock_row_data


class SimplePasteTable(QTableWidget):
    """Minimal table with just Ctrl+V paste support"""

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.paste_data()
        else:
            super().keyPressEvent(event)

    def paste_data(self):
        """Paste clipboard data into table"""
        clipboard = QApplication.clipboard()
        text = clipboard.text()

        if not text:
            return

        lines = [line for line in text.strip().split('\n') if line.strip()]

        if self.rowCount() < len(lines):
            self.setRowCount(len(lines))

        for row, line in enumerate(lines):
            parts = line.replace(',', '\t').split('\t')
            for col, value in enumerate(parts[:self.columnCount()]):
                item = QTableWidgetItem(value.strip())
                self.setItem(row, col, item)
