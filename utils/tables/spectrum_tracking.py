import pandas as pd
import os
from datetime import datetime
import ast
import traceback
import tempfile
import time
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QLabel, QMessageBox, QApplication,
    QFileDialog,QDialog, QButtonGroup, QRadioButton,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from utils.style.style import StyleSheet, EditorConstants
import shutil
from utils.peak_matching.peptide_fragmentation import fragment_and_match_peaks_cached
from utils.utilities import DataGatherer
from utils.spectrum_graph.mass_spec_viewer_widget import MassSpecViewer
from utils.tables.relocalisation_widget import RelocalisationWidget

from pyqtgraph.exporters import ImageExporter,SVGExporter

logger = logging.getLogger(__name__)


def _get_labile_settings(app):
    """Read the labile/remainder/mod-NL checkbox states from *app*. Returns (bool, bool, bool)."""
    def _cb(attr):
        cb = getattr(app, attr, None)
        return cb.isChecked() if cb is not None else False
    return _cb('enable_labile_losses_cb'), _cb('enable_remainder_ions_cb'), _cb('enable_mod_nl_cb')


class SpectrumTrackerWidget(QWidget):
    """Widget to track spectrum quality and manage selected spectra for export"""
    
    spectrumAccepted = pyqtSignal(dict)  # Emitted when spectrum is accepted
    spectrumDeclined = pyqtSignal(dict)  # Emitted when spectrum is declined
    spectrumAddedToExport = pyqtSignal(dict)  # Emitted when added to export list
    
    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_spectrum_data = None
        self.current_settings_data = None
        self.export_list_df = pd.DataFrame()
        
        self._setup_ui()
        self._init_dataframes()
        
    def _setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)

        # Tabbed interface for export list
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(EditorConstants.get_tab_style())

        # Info tab (peptide info) - placeholder, will be set via set_peptide_info_widget
        self._info_tab_index = None

        # Export list tab
        self.export_tab = self._create_export_tab()
        self.tab_widget.addTab(self.export_tab, "Export List")

        # Relocalise tab
        self.relocalise_tab = RelocalisationWidget(self.main_app)
        self.tab_widget.addTab(self.relocalise_tab, "Relocalise")

        layout.addWidget(self.tab_widget)

    def set_peptide_info_widget(self, peptide_info_scroll):
        """Insert the peptide info scroll area as the first tab ('Info')."""
        self.tab_widget.insertTab(0, peptide_info_scroll, "Info")
        self._info_tab_index = 0
        self.tab_widget.setCurrentIndex(0)
        
    def _create_export_tab(self):
        """Create the export list tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Controls row: Accept, Decline, Export, Clear
        controls_layout = QHBoxLayout()

        # Quality assessment buttons
        self.accept_btn = QPushButton("✓ Accept")
        self.accept_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                padding: {EditorConstants.BUTTON_PADDING()};
                {EditorConstants.get_font_string("bold")}
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
            }}
            QPushButton:hover {{
                background-color: #218838;
            }}
            QPushButton:disabled {{
                background-color: {EditorConstants.DISABLED_COLOR()};
            }}
        """)
        self.accept_btn.clicked.connect(self._accept_spectrum)
        self.accept_btn.setEnabled(False)
        controls_layout.addWidget(self.accept_btn)

        self.decline_btn = QPushButton("✗ Decline")
        self.decline_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                padding: {EditorConstants.BUTTON_PADDING()};
                {EditorConstants.get_font_string("bold")}
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
            }}
            QPushButton:hover {{
                background-color: #c82333;
            }}
            QPushButton:disabled {{
                background-color: {EditorConstants.DISABLED_COLOR()};
            }}
        """)
        self.decline_btn.clicked.connect(self._decline_spectrum)
        self.decline_btn.setEnabled(False)
        controls_layout.addWidget(self.decline_btn)

        controls_layout.addStretch()

        # Export button (Excel, PDF+Excel, SVG+Excel options)
        export_btn = QPushButton("Export")
        export_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        export_btn.clicked.connect(self._export_svg_images)
        controls_layout.addWidget(export_btn)

        # Clear export list button
        clear_export_btn = QPushButton("Clear List")
        clear_export_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        clear_export_btn.clicked.connect(self._clear_export_list)
        controls_layout.addWidget(clear_export_btn)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Export list table
        self.export_table = QTableWidget()
        self.export_table.setAlternatingRowColors(False)
        self.export_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        StyleSheet.apply_table_styling(self.export_table)
        layout.addWidget(self.export_table)
        
        return tab
            
    def _init_dataframes(self):
        """Initialize the tracking dataframes"""
        # Export list columns with Quality column and peptide info data
        export_columns = [
            'Timestamp', 'Peptide', 'Modified Peptide', 'Charge', 'Observed M/Z',
            'Quality',
            'Original Modifications', 'User Modifications', 'PPM Tolerance',
            'Text Annotation Threshold', 'Max Neutral Losses',
            'Hyperscore', 'Spectrum File', 'Scan',
            'Fragmented Bonds', 'Annotated TIC',
            # Scoring metrics from peptide info widget
            'XTandem', 'Longest Consecutive',
            'Complementary Pairs', 'Morpheus Score',
            'Raw Data Path',
            #  All ion type selections
            'Selected Ion Types',           # Basic ion types (y, b, c, etc.)
            'Selected Neutral Loss Types',  # Neutral loss ions (y-H2O, b-NH3, etc.)
            'Selected Internal Ion Types',  # Internal ions (int-b, int-a, etc.)
            'Selected Custom Ions',         # Custom ion series data
            'Selected Diagnostic Ions'      # Diagnostic ions data
        ]
        self.export_list_df = pd.DataFrame(columns=export_columns)
        
    def set_current_spectrum(self, spectrum_data, settings_data=None):
        """Set the current spectrum being viewed - ENHANCED data capture"""
        self.current_spectrum_data = spectrum_data.copy() if spectrum_data else None
        self.current_settings_data = settings_data.copy() if settings_data else {}

        # Update UI
        if self.current_spectrum_data:
            # Enable buttons
            self.accept_btn.setEnabled(True)
            self.decline_btn.setEnabled(True)
        else:
            self.accept_btn.setEnabled(False)
            self.decline_btn.setEnabled(False)
            
    def _accept_spectrum(self):
        """Mark current spectrum as accepted and add to export list"""
        if not self.current_spectrum_data:
            return

        logger.debug("[DEBUG] Accepting spectrum")
        self._add_to_export_list_with_quality('Accepted')
        self.spectrumAccepted.emit(self.current_spectrum_data.copy())

    def _decline_spectrum(self):
        """Mark current spectrum as declined and add to export list"""
        if not self.current_spectrum_data:
            return

        logger.debug("[DEBUG] Declining spectrum")
        self._add_to_export_list_with_quality('Declined')
        self.spectrumDeclined.emit(self.current_spectrum_data.copy())
        
    def _add_to_export_list_with_quality(self, quality):
        """Add current spectrum to export list with quality assessment"""
        if not self.current_spectrum_data:
            return

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Get fragmented bonds and annotated TIC from settings
        fragmented_bonds = self.current_settings_data.get('fragmented_bonds', '') if self.current_settings_data else ''
        annotated_tic = self.current_settings_data.get('annotated_tic', '') if self.current_settings_data else ''

        # Get all peptide info widget data via get_export_data
        peptide_info_fields = {}
        main_window = self.get_main_window()
        if main_window and hasattr(main_window, 'annotation_tab_manager'):
            peptide_info_widget = main_window.annotation_tab_manager.peptide_info_widget
            if peptide_info_widget:
                peptide_info_fields = peptide_info_widget.get_export_data()
                if not fragmented_bonds:
                    fragmented_bonds = peptide_info_fields.get('Fragmented Bonds', '')
                if not annotated_tic:
                    annotated_tic = peptide_info_fields.get('Annotated TIC', '')

        # Start with all original PSM row data
        new_record = dict(self.current_spectrum_data)

        # Add spectrum tracking specific fields including quality and all ion types
        tracking_fields = {
            'Timestamp': timestamp,
            'Quality': quality,
            'User Modifications': str(self.current_settings_data.get('user_modifications', [])) if self.current_settings_data else '',
            'PPM Tolerance': self.current_settings_data.get('ppm_tolerance', '') if self.current_settings_data else '',
            'Text Annotation Threshold': self.current_settings_data.get('text_annotation_threshold', '') if self.current_settings_data else '',
            'Max Neutral Losses': self.current_settings_data.get('max_neutral_losses', '') if self.current_settings_data else '',
            'Fragmented Bonds': fragmented_bonds,
            'Annotated TIC': annotated_tic,
            # Scoring metrics (from peptide info export data)
            'XTandem': peptide_info_fields.get('X!Tandem', ''),
            'Longest Consecutive': peptide_info_fields.get('Longest Consecutive', ''),
            'Complementary Pairs': peptide_info_fields.get('Complementary Pairs', ''),
            'Morpheus Score': peptide_info_fields.get('Morpheus Score', ''),
            # Store all ion type selections in separate columns
            'Selected Ion Types': str(self.current_settings_data.get('selected_basic_ions', [])) if self.current_settings_data else '',
            'Selected Neutral Loss Types': str(self.current_settings_data.get('selected_neutral_loss_ions', [])) if self.current_settings_data else '',
            'Selected Internal Ion Types': str(self.current_settings_data.get('selected_internal_ions', [])) if self.current_settings_data else '',
            'Selected Custom Ions': str(self.current_settings_data.get('selected_custom_ions_data', [])) if self.current_settings_data else '',
            'Selected Diagnostic Ions': str(self.current_settings_data.get('selected_diagnostic_ions_data', [])) if self.current_settings_data else ''
        }

        # Update with tracking-specific fields
        new_record.update(tracking_fields)

        # Add all peptide info fields (ion counts, intensities, annotation summary, etc.)
        new_record.update(peptide_info_fields)

        logger.debug(f"[DEBUG] Export list record ({quality}): {len(new_record)} fields")

        # Proper DataFrame concatenation
        new_df = pd.DataFrame([new_record])
        self.export_list_df = pd.concat([self.export_list_df, new_df], ignore_index=True)

        # Update table
        self._update_export_table()

        # Switch to export tab
        export_index = self.tab_widget.indexOf(self.export_tab)
        self.tab_widget.setCurrentIndex(export_index)

        self.spectrumAddedToExport.emit(self.current_spectrum_data.copy())

    def _extract_label_value(self, label_text, prefix):
        """Extract the value portion from a label like 'Hyperscore: 1.2345'"""
        if prefix in label_text:
            value = label_text.split(prefix, 1)[1].strip()
            return value if value != '-' else ''
        return ''

    def _update_export_table(self):
        """Update the export list table display"""
        df = self.export_list_df
        if df.empty:
            self.export_table.setRowCount(0)
            self.export_table.setColumnCount(0)
            return
            
        self.export_table.setRowCount(len(df))
        self.export_table.setColumnCount(len(df.columns))
        self.export_table.setHorizontalHeaderLabels(df.columns)
        
        for row in range(len(df)):
            for col in range(len(df.columns)):
                item = QTableWidgetItem(str(df.iloc[row, col]))
                self.export_table.setItem(row, col, item)
                
        self.export_table.resizeColumnsToContents()
        
    def _export_svg_images(self):
        """Export images for all spectra in export list - SIMPLIFIED to use mass spec widget export"""
        if self.export_list_df.empty:
            QMessageBox.information(self, "No Data", "No spectra in export list.")
            return
        

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Options")
        dialog.setFixedSize(350, 200)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title_label = QLabel("Choose export format:")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        # Radio buttons for export options - REMOVED SVG options, keep only PDF and Excel
        button_group = QButtonGroup()
        
        excel_only_radio = QRadioButton("Excel data only")
        excel_only_radio.setChecked(True)
        button_group.addButton(excel_only_radio, 0)
        layout.addWidget(excel_only_radio)
        
        pdf_radio = QRadioButton("PDF with high-quality images + Excel data")
        button_group.addButton(pdf_radio, 1)
        layout.addWidget(pdf_radio)
        
        svg_radio = QRadioButton("Individual SVG files + Excel data")
        button_group.addButton(svg_radio, 2)
        layout.addWidget(svg_radio)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        ok_button = QPushButton("Export")
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        export_type = button_group.checkedId()
        
        # Get export folder
        folder_path = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not folder_path:
            return
        
        # Get reference to main window for export functionality
        main_window = self.get_main_window()
        if not main_window:
            QMessageBox.warning(self, "Error", "Cannot access main application window.")
            return
        
        try:
            if export_type == 0:  # Excel only
                excel_file = self._export_excel_only(folder_path)
                QMessageBox.information(self, "Export Complete", 
                    f"Successfully exported Excel data: {excel_file}")
            
            elif export_type == 1:  # PDF + Excel
                pdf_file, excel_file = self._export_pdf_and_excel(folder_path, main_window)
                QMessageBox.information(self, "Export Complete", 
                    f"Successfully exported:\n• PDF with images: {pdf_file}\n• Excel data: {excel_file}")
                
            elif export_type == 2:  # SVG + Excel
                svg_count, excel_file = self._export_svg_and_excel(folder_path, main_window)
                QMessageBox.information(self, "Export Complete", 
                    f"Successfully exported:\n• {svg_count} SVG files\n• Excel data: {excel_file}")
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to export files:\n{str(e)}")

    def _wait_for_render(self, cycles=20, delay=0.05):
        """Block briefly while pumping the event loop to let the viewer render."""
        for _ in range(cycles):
            time.sleep(delay)
            QApplication.processEvents()

    @staticmethod
    def _lookup_row_value(row, keys, default="Unknown"):
        """Return the first non-empty value from *row* matching one of *keys*, cleaning float-ints."""
        for key in keys:
            if key in row and row[key] and str(row[key]) != 'nan' and str(row[key]) != default:
                value = row[key]
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                return str(value)
        return default

    _SCAN_KEYS = ["index", "Scan", "scan", "Scan Number", "scan_number"]
    _SPECTRUM_FILE_KEYS = ["Spectrum file", "spectrum_file", "Raw file", "raw_file", "File", "file", "spectrum_file_path"]

    def _write_export_excel(self, folder_path):
        """Write the standard Excel export (Export_List + Metadata sheets). Returns filename."""
        excel_filename = "spectrum_tracker_export_data.xlsx"
        excel_filepath = os.path.join(folder_path, excel_filename)

        with pd.ExcelWriter(excel_filepath, engine='openpyxl') as writer:
            self.export_list_df.to_excel(writer, sheet_name='Export_List', index=False)
            metadata_df = self._create_export_metadata()
            metadata_df.to_excel(writer, sheet_name='Metadata', index=False)

        return excel_filename

    def _export_excel_only(self, folder_path):
        """Export Excel data only"""
        return self._write_export_excel(folder_path)


           
    def _generate_fragmentation_for_row(self, main_window, peptide, modifications, charge, ppm_tolerance, 
                                    max_neutral_losses, mz_values, intensity_values, row):
        """Generate fragmentation data using stored ion selections from row data"""
        try:

            # ENHANCED: Extract all ion types from stored row data
            basic_ions = self._parse_stored_list(row.get('Selected Ion Types', '[]'))
            neutral_loss_ions = self._parse_stored_list(row.get('Selected Neutral Loss Types', '[]'))
            internal_ions = self._parse_stored_list(row.get('Selected Internal Ion Types', '[]'))

            # ENHANCED: Parse stored custom and diagnostic ion data
            custom_ions_data = self._parse_stored_list(row.get('Selected Custom Ions', '[]'))
            diagnostic_ions_data = self._parse_stored_list(row.get('Selected Diagnostic Ions', '[]'))

            logger.debug(f"[DEBUG] Parsed from stored data:")
            logger.debug(f"  - Basic ions: {basic_ions}")
            logger.debug(f"  - Neutral loss ions: {neutral_loss_ions}")
            logger.debug(f"  - Internal ions: {internal_ions}")
            logger.debug(f"  - Custom ions: {len(custom_ions_data)} items")
            logger.debug(f"  - Diagnostic ions: {len(diagnostic_ions_data)} items")
            
            # Convert internal ions to proper format (remove 'int-' prefix for calculation)
            internal_ions_clean = [ion.replace('int-', '') for ion in internal_ions]
            
            # Combine all standard ion types for fragmentation calculation
            all_standard_ions = basic_ions + neutral_loss_ions
            
            # Convert custom ions data to format expected by fragmentation system
            custom_ion_series_list = []
            for custom_ion in custom_ions_data:
                if isinstance(custom_ion, dict) and 'name' in custom_ion:
                    custom_ion_series_list.append({
                        'name': custom_ion['name'],
                        'base': custom_ion.get('base', 'y'),
                        'offset': float(custom_ion.get('offset', 0)),
                        'color': custom_ion.get('color', '#CCCCCC'),
                        'restriction': custom_ion.get('restriction', '')
                    })
            
            # Convert diagnostic ions data to format expected by fragmentation system
            diagnostic_ions_list = []
            for diag_ion in diagnostic_ions_data:
                if isinstance(diag_ion, dict) and 'name' in diag_ion:
                    diagnostic_ions_list.append((
                        diag_ion['name'],
                        float(diag_ion.get('mass', 0)),
                        diag_ion.get('color', '#CCCCCC')
                    ))
            
            # Create user mz values list
            user_mz_values = list(zip(mz_values, intensity_values))

            # Build modification-specific neutral losses from central DB
            mod_neutral_losses = None
            central_mod_db = getattr(main_window, 'central_mod_db', None)
            if central_mod_db and modifications:
                enable_labile, enable_remainder, enable_mod_nl = _get_labile_settings(main_window)
                mod_neutral_losses = DataGatherer.build_mod_neutral_losses(
                    modifications, central_mod_db, enable_labile=enable_labile,
                    enable_remainder=enable_remainder, enable_mod_nl=enable_mod_nl
                )

            logger.debug(f"[DEBUG] Generating fragmentation with:")
            logger.debug(f"  - Peptide: {peptide}")
            logger.debug(f"  - Modifications: {modifications}")
            logger.debug(f"  - All standard ions: {all_standard_ions}")
            logger.debug(f"  - Internal ions: {internal_ions_clean}")
            logger.debug(f"  - Custom ion series: {len(custom_ion_series_list)} items")
            logger.debug(f"  - Diagnostic ions: {len(diagnostic_ions_list)} items")
            logger.debug(f"  - User m/z values: {len(user_mz_values)}")

            # Generate fragmentation data using your existing system
            result = fragment_and_match_peaks_cached(
                peptide=peptide,
                modifications=modifications,
                max_charge=charge,
                ppm_tolerance=ppm_tolerance,
                selected_ions=all_standard_ions,
                selected_internal_ions=internal_ions_clean,
                user_mz_values=user_mz_values,
                diagnostic_ions=diagnostic_ions_list,
                custom_ion_series_list=custom_ion_series_list,
                max_neutral_losses=max_neutral_losses,
                mod_neutral_losses=mod_neutral_losses
            )
            
            if result is None:
                logger.debug(f"[WARNING] Fragmentation returned None for {peptide}")
                return None, None

            matched_data, theoretical_data = result

            logger.debug(f"[DEBUG] Fragmentation successful: {len(matched_data)} matched, {len(theoretical_data)} theoretical")
            return matched_data, theoretical_data
            
        except Exception as e:
            logger.debug(f"[ERROR] Failed to generate fragmentation: {e}")

            traceback.print_exc()
            return None, None
        
    def _parse_stored_list(self, stored_string):
        """Parse a stored string (via ast.literal_eval) back to a list. Returns [] on failure."""
        try:
            if stored_string and stored_string != '[]' and stored_string != '':
                parsed = ast.literal_eval(stored_string)
                if isinstance(parsed, list):
                    return parsed
            return []
        except Exception as e:
            logger.debug(f"[WARNING] Failed to parse stored list: {stored_string}, error: {e}")
            return []
        

    def _get_spectral_data_for_scan(self, main_window, spectrum_file, scan_number):
        """Get spectral data for a specific scan"""
        try:
            if not main_window or not hasattr(main_window, 'extracted_spectral_data'):
                return None
            
            # Clean scan number
            scan_str = scan_number.replace('.0', '') if scan_number.endswith('.0') else scan_number
            
            # Create cache key
            cache_key = f"{spectrum_file}_{scan_str}"
            
            # Get data from cache
            extracted_data = main_window.extracted_spectral_data
            if cache_key in extracted_data:
                spectral_data = extracted_data[cache_key]
                return spectral_data['mz_values'], spectral_data['intensity_values']
            
            print(f"[WARNING] No cached data found for key: {cache_key}")
            return None

        except Exception as e:
            logger.debug(f"[ERROR] Failed to get spectral data: {e}")
            return None

    def _create_temporary_export_dialog(self, main_window):
        """Create a temporary dialog window with exact mass spec viewer dimensions for export"""
        try:
            # Get the main mass spec viewer for dimensions
            main_viewer = None
            if (hasattr(main_window, 'annotation_tab_manager') and 
                main_window.annotation_tab_manager.mass_spec_viewer):
                main_viewer = main_window.annotation_tab_manager.mass_spec_viewer
            
            if not main_viewer:
                logger.debug("[ERROR] Cannot find main mass spec viewer")
                return None, None

            logger.debug(f"[DEBUG] Creating temporary export dialog...")
            
            # Create modal dialog
            dialog = QDialog(main_window)
            dialog.setWindowTitle("Batch Export in Progress...")
            dialog.setModal(True)  # Block interaction with main window
            
            # Set exact same size as main viewer
            main_size = main_viewer.size()
            dialog.setFixedSize(main_size.width() + 20, main_size.height() + 50)  # Add padding for title bar
            
            # Center on main window
            if main_window:
                main_geo = main_window.geometry()
                x = main_geo.x() + (main_geo.width() - dialog.width()) // 2
                y = main_geo.y() + (main_geo.height() - dialog.height()) // 2
                dialog.move(x, y)
            
            # Create layout
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(10, 10, 10, 10)
            
            # Create mass spec viewer for export
            export_viewer = MassSpecViewer()
            
            # Set exact same size as main viewer
            export_viewer.setFixedSize(main_size)
            export_viewer.setMinimumSize(main_size)
            export_viewer.setMaximumSize(main_size)
            
            # Copy available modifications from main viewer
            if hasattr(main_viewer, 'available_modifications'):
                export_viewer.set_available_modifications(main_viewer.available_modifications)
            
            # Add to dialog
            layout.addWidget(export_viewer)

            # Don't show dialog yet - we'll show it during export
            logger.debug(f"[DEBUG] Temporary export dialog created with size: {dialog.size()}")
            logger.debug(f"[DEBUG] Export viewer size: {export_viewer.size()}")
            
            return dialog, export_viewer
            
        except Exception as e:
            logger.debug(f"[ERROR] Failed to create temporary export dialog: {e}")
            traceback.print_exc()
            return None, None

    def _export_svg_and_excel(self, folder_path, main_window):
        """Export SVG files using temporary dialog window + Excel data - FIXED filename generation"""
        
        total_rows = len(self.export_list_df)
        exported_count = 0
        
        # Create modal progress dialog that locks the app
        progress = self._create_modal_progress_dialog("Exporting SVG Files", total_rows)
        progress.show()
        
        # Create temporary dialog window with export viewer
        export_dialog, export_viewer = self._create_temporary_export_dialog(main_window)
        
        if not export_dialog or not export_viewer:
            progress.close()
            QMessageBox.warning(self, "Error", "Cannot create temporary export dialog.")
            return 0, None
        
        try:
            # Update progress for initialization
            self._update_progress_percentage(progress, 0, total_rows, "Initializing SVG export")
            
            # Show the export dialog (this makes the viewer visible for proper SVG export)
            export_dialog.show()
            QApplication.processEvents()
            
            for idx, row in self.export_list_df.iterrows():
                current_item = idx + 1  # 1-based counting for user display
                
                peptide = str(row.get('Peptide', 'Unknown'))
                scan = str(row.get('Scan', 'Unknown'))
                
                # Update progress for current item
                self._update_progress_percentage(progress, current_item, total_rows, f"Processing {peptide} (scan {scan})")
                
                try:
                    # Generate unique graph for this row's data in the export viewer
                    if self._generate_graph_for_row_in_export_viewer(export_viewer, row, main_window):
                        
                        # Show rendering status
                        self._update_progress_percentage(progress, current_item, total_rows, f"Rendering {peptide}")

                        # Allow proper rendering time
                        self._wait_for_render()
                        
                        # Update progress for export phase
                        self._update_progress_percentage(progress, current_item, total_rows, f"Exporting SVG for {peptide}")
                        
                        filename = self._generate_svg_filename(row, idx)
                        filepath = os.path.join(folder_path, filename)
                        
                        # Export SVG using the export viewer (which is visible in dialog)
                        if self._export_svg_using_export_viewer(export_viewer, filepath):
                            exported_count += 1
                            logger.debug(f"[DEBUG] Exported SVG {exported_count}/{total_rows}: {filename}")
                        else:
                            logger.debug(f"[ERROR] Failed to export SVG for {peptide}")
                    else:
                        logger.debug(f"[WARNING] Failed to generate graph for row {idx}")
                        
                except Exception as e:
                    logger.debug(f"[ERROR] Failed to export SVG for row {idx}: {e}")
                    traceback.print_exc()
                    continue
            
            # Final progress update
            self._update_progress_percentage(progress, total_rows, total_rows, "Creating Excel file")
            
        except Exception as e:
            logger.debug(f"[ERROR] SVG export failed: {e}")
            traceback.print_exc()

        finally:
            # Clean up dialog
            if export_dialog:
                logger.debug(f"[DEBUG] Cleaning up temporary export dialog")
                export_dialog.hide()
                export_dialog.deleteLater()
        
        # Export Excel data
        excel_filename = self._write_export_excel(folder_path)

        # Show completion
        progress.setLabelText(f"Export complete! {exported_count} SVG files + Excel data")
        progress.setValue(100)
        QApplication.processEvents()

        # Brief pause to show completion
        time.sleep(1.0)
        progress.close()

        return exported_count, excel_filename

    def _generate_svg_filename(self, row, idx):
        """Generate SVG filename using the same logic as generate_default_filename"""

        # Get peptide sequence (clean it for filename)
        peptide = str(row.get('Peptide', 'Unknown'))
        if peptide and peptide != 'Unknown':
            peptide = peptide.replace(" ", "_").replace('/', '_').replace('\\', '_').replace(':', '-')
        else:
            peptide = ""

        # Get spectrum file name (without extension)
        spectrum_file = ""
        raw_value = self._lookup_row_value(row, self._SPECTRUM_FILE_KEYS, default="")
        if raw_value:
            spectrum_file = os.path.splitext(os.path.basename(raw_value))[0]

        index = self._lookup_row_value(row, self._SCAN_KEYS, default="")

        # Build the base filename: Peptide-SpectrumFile-index
        components = [c for c in (peptide, spectrum_file, index) if c]
        base_filename = "-".join(components) if components else "spectrum_data"

        # Add index prefix and SVG extension
        filename = f"{idx:03d}_{base_filename}.svg"

        # Clean any remaining problematic characters
        filename = filename.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '-')

        logger.debug(f"[DEBUG] Generated SVG filename: {filename}")
        return filename


    def _generate_graph_for_row_in_export_viewer(self, export_viewer, row, main_window):
        """Generate graph for a specific row in the export viewer"""
        try:
            # Extract peptide and basic info
            peptide = str(row.get('Peptide', ''))
            if not peptide or peptide == 'Unknown':
                logger.debug(f"[WARNING] No valid peptide for row")
                return False
            
            # Parse modifications
            original_mods_str = str(row.get('Parsed Modifications', '[]'))
            user_mods_str = str(row.get('User Modifications', '[]'))
            
            # Use user modifications if available, otherwise use original
            mods_to_use = user_mods_str if user_mods_str and user_mods_str != '[]' else original_mods_str
            
            try:
                modifications = ast.literal_eval(mods_to_use) if mods_to_use != '[]' else []
            except:
                modifications = []
            
            # Extract settings
            charge = int(row.get('Charge', 1))
            ppm_tolerance = float(row.get('PPM Tolerance', 10)) if row.get('PPM Tolerance') else 10
            max_neutral_losses = int(row.get('Max Neutral Losses', 1)) if row.get('Max Neutral Losses') else 1
            
            # Get spectrum file path and scan number
            spectrum_file = str(row.get('spectrum_file_path', row.get('Spectrum file', '')))
            scan_number = str(row.get('index', row.get('Scan', '')))

            logger.debug(f"[DEBUG] Generating graph in EXPORT DIALOG for: {peptide}, scan: {scan_number}")

            # Extract spectral data for this scan
            spectral_data = self._get_spectral_data_for_scan(main_window, spectrum_file, scan_number)
            if not spectral_data:
                logger.debug(f"[WARNING] No spectral data found for {spectrum_file}, scan {scan_number}")
                return False
            
            mz_values, intensity_values = spectral_data
            
            # Generate fragmentation using stored ion selections from row
            matched_data, theoretical_data = self._generate_fragmentation_for_row(
                main_window, peptide, modifications, charge, ppm_tolerance, 
                max_neutral_losses, mz_values, intensity_values, row
            )
            
            if matched_data is None or matched_data.empty:
                logger.debug(f"[WARNING] No fragmentation data generated for {peptide}")
                return False

            # Set data in the export viewer
            logger.debug(f"[DEBUG] Setting data in export dialog viewer for {peptide}...")
            
            # Ensure modifications is a list (not None)
            if modifications is None:
                modifications = []
            
            # Create row data for metadata with unique scan identifier
            row_data = dict(row)
            row_data['_export_dialog_id'] = f"{peptide}_{scan_number}_{id(row)}"  # Make it truly unique
            
            # Set data in export viewer
            export_viewer.set_peptide_sequence(peptide)
            export_viewer.set_modifications(modifications)
            export_viewer.set_data(
                matched_data=matched_data,
                peptide=peptide,
                mod_positions=modifications,
                row_data=row_data,
                theoretical_data=theoretical_data
            )
            
            # Force immediate and complete UI update
            self._wait_for_render(cycles=10, delay=0.02)
            
            # Verify the data was set correctly
            if not hasattr(export_viewer, 'df') or export_viewer.df.empty:
                logger.debug(f"[WARNING] Export viewer data not set properly")
                return False

            # Verify peptide sequence was set
            if hasattr(export_viewer, 'peptide_sequence') and export_viewer.peptide_sequence != peptide:
                logger.debug(f"[WARNING] Peptide sequence not set correctly: expected {peptide}, got {export_viewer.peptide_sequence}")
                return False

            logger.debug(f"[DEBUG] Export dialog viewer data set successfully: {len(export_viewer.df)} rows for {peptide}")
            return True
            
        except Exception as e:
            logger.debug(f"[ERROR] Failed to generate graph for row in export dialog: {e}")
            traceback.print_exc()
            return False

    def _export_svg_using_export_viewer(self, export_viewer, filepath):
        """Export SVG using the export dialog viewer's built-in export method"""
        try:
            # The viewer is visible in the dialog, so we can export directly
            
            # Use the export viewer's SVG export method
            if hasattr(export_viewer, '_export_svg_to_file'):
                export_viewer._export_svg_to_file(filepath)
                logger.debug(f"[DEBUG] Used _export_svg_to_file method on export dialog viewer")
            elif hasattr(export_viewer, 'export_svg'):
                # Mock the file dialog to use our filepath
                original_get_save_filename = QFileDialog.getSaveFileName

                def mock_get_save_filename(*args, **kwargs):
                    return filepath, "SVG Files (*.svg)"

                # Temporarily replace the file dialog
                QFileDialog.getSaveFileName = mock_get_save_filename

                try:
                    export_viewer.export_svg()
                    logger.debug(f"[DEBUG] Used export_svg method with mocked dialog on export viewer")
                finally:
                    # Restore original file dialog
                    QFileDialog.getSaveFileName = original_get_save_filename
            else:
                # Fallback: Use PyQtGraph exporter directly

                if hasattr(export_viewer, 'glw') and hasattr(export_viewer.glw, 'scene'):
                    exporter = SVGExporter(export_viewer.glw.scene())
                    exporter.export(filepath)
                    logger.debug(f"[DEBUG] Used PyQtGraph SVGExporter directly on export viewer")
                else:
                    raise Exception("No suitable export method found")

            # Verify the file was created and has reasonable content
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                logger.debug(f"[DEBUG] SVG exported successfully from export dialog: {os.path.getsize(filepath)} bytes")
                return True
            else:
                logger.debug(f"[WARNING] SVG file is too small or doesn't exist")
                return False

        except Exception as e:
            logger.debug(f"[ERROR] SVG export from export dialog failed: {e}")
            return False

        
    def _export_pdf_and_excel(self, folder_path, main_window):
        """Export combined PDF and Excel data using temporary dialog window - FIXED scan number display"""
        try:
            total_rows = len(self.export_list_df)
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            # Create modal progress dialog
            progress = self._create_modal_progress_dialog("Creating PDF with High-Quality Images", total_rows)
            progress.show()
            
            # Create temporary dialog window with export viewer
            export_dialog, export_viewer = self._create_temporary_export_dialog(main_window)
            
            if not export_dialog or not export_viewer:
                progress.close()
                QMessageBox.warning(self, "Error", "Cannot create temporary export dialog.")
                return None, None
            
            # Create PDF filename
            pdf_filename = "spectrum_tracker_combined.pdf"
            pdf_filepath = os.path.join(folder_path, pdf_filename)
            
            # Update progress for initialization
            self._update_progress_percentage(progress, 0, total_rows, "Initializing PDF creation")
            
            # Show the export dialog (this makes the viewer visible for proper export)
            export_dialog.show()
            QApplication.processEvents()
            
            # Create PDF document
            doc = SimpleDocTemplate(pdf_filepath, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
            story = []
            styles = getSampleStyleSheet()
            
            # Create custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                fontSize=18,
                spaceAfter=20,
                textColor=colors.black
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=14,
                spaceAfter=10,
                textColor=colors.black
            )
            
            # Add title and metadata
            self._update_progress_percentage(progress, 0, total_rows, "Creating PDF header")
            
            title = Paragraph("Spectrum Tracking Export Report", title_style)
            story.append(title)
            
            # Add export summary
            summary_text = f"""
            <b>Export Summary:</b><br/>
            • Total Spectra: {len(self.export_list_df)}<br/>
            • Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
            """
            summary = Paragraph(summary_text, styles['Normal'])
            story.append(summary)
            story.append(Spacer(1, 20))
            
            temp_dir = tempfile.mkdtemp()
            
            try:
                for idx, row in self.export_list_df.iterrows():
                    current_item = idx + 1  # 1-based counting
                    
                    peptide = str(row.get('Peptide', 'Unknown'))
                    
                    scan = self._get_clean_scan_number(row)
                    
                    # Update progress for current spectrum
                    self._update_progress_percentage(progress, current_item, total_rows, f"Processing {peptide} (scan {scan})")
                    
                    try:
                        spectrum_info = f"""
                        <b>Spectrum {current_item}: {peptide}</b><br/>
                        Scan: {scan} | Charge: {self._get_clean_value(row, 'Charge')} | m/z: {self._get_clean_value(row, 'Observed M/Z')}<br/>
                        File: {os.path.basename(str(row.get('Spectrum file', 'Unknown')))}<br/>
                        """
                        
                        info_para = Paragraph(spectrum_info, heading_style)
                        story.append(info_para)
                        story.append(Spacer(1, 10))
                        
                        # Generate graph for this row in export dialog viewer
                        if self._generate_graph_for_row_in_export_viewer(export_viewer, row, main_window):
                            # Update progress for rendering
                            self._update_progress_percentage(progress, current_item, total_rows, f"Rendering {peptide}")

                            # Allow proper rendering time
                            self._wait_for_render()
                            
                            # Update progress for PNG creation
                            self._update_progress_percentage(progress, current_item, total_rows, f"Creating high-quality image for {peptide}")
                            
                            # Export high-quality PNG from export dialog viewer
                            temp_png = os.path.join(temp_dir, f"spectrum_{idx}.png")
                            
                            if self._export_high_quality_png(export_viewer, temp_png):
                                # Verify the file was created and has content
                                if os.path.exists(temp_png) and os.path.getsize(temp_png) > 0:
                                    # Add high-quality image to PDF
                                    img = Image(temp_png, width=7*inch, height=5*inch)
                                    story.append(img)
                                else:
                                    raise Exception("PNG file was not created or is empty")
                            else:
                                raise Exception("Failed to create high-quality PNG")
                                
                        else:
                            # Add placeholder if graph generation failed
                            placeholder = Paragraph(f"[Spectrum visualization for {peptide} - Generation failed]", styles['Normal'])
                            story.append(placeholder)
                        
                        # Add page break between spectra (except for last one)
                        if idx < len(self.export_list_df) - 1:
                            story.append(PageBreak())
                        else:
                            story.append(Spacer(1, 20))
                            
                    except Exception as e:
                        logger.debug(f"[ERROR] Failed to add spectrum {idx} to PDF: {e}")
                        # Add error message to PDF
                        error_msg = Paragraph(f"Error processing spectrum {peptide}: {str(e)}", styles['Normal'])
                        story.append(error_msg)
                        story.append(Spacer(1, 12))
                        continue
                
                # Build PDF
                self._update_progress_percentage(progress, total_rows, total_rows, "Building PDF document")
                doc.build(story)
                
            finally:
                # Clean up dialog
                if export_dialog:
                    export_dialog.hide()
                    export_dialog.deleteLater()
                
                # Clean up temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)
            
        except ImportError:
            # Fallback if reportlab is not available
            if 'progress' in locals():
                progress.close()
            QMessageBox.warning(self, "PDF Export Unavailable", 
                "PDF export requires reportlab package. Exporting Excel data only.")
            return self._export_excel_only(folder_path), None
        except Exception as e:
            if 'progress' in locals():
                progress.close()
            logger.debug(f"[ERROR] PDF export failed: {e}")
            traceback.print_exc()
            QMessageBox.warning(self, "PDF Export Failed", f"Failed to create PDF: {str(e)}")
            return None, None
        
        # Export Excel data
        self._update_progress_percentage(progress, total_rows, total_rows, "Creating Excel file")

        excel_filename = self._write_export_excel(folder_path)
        
        # Show completion
        progress.setLabelText(f"Export complete! PDF with {total_rows} spectra + Excel data - 100%")
        progress.setValue(100)
        QApplication.processEvents()
        
        # Brief pause to show completion
        time.sleep(1.0)
        progress.close()
        
        return pdf_filename, excel_filename

    def _get_clean_scan_number(self, row):
        """Get clean scan number from row data."""
        return self._lookup_row_value(row, self._SCAN_KEYS)

    def _get_clean_value(self, row, key):
        """Get clean value from row, handling NaN and None values"""
        value = row.get(key, 'Unknown')
        if value is None or str(value) == 'nan' or str(value) == 'None':
            return 'Unknown'
        
        # Handle float values that are integers
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        
        return str(value)
            
    def _export_high_quality_png(self, hidden_viewer, output_path):
        """Export high-quality PNG at 300 DPI from hidden viewer - includes modification legend"""
        legend_items = []
        try:
            # Add legend to scene before export (same as SVG export)
            if hasattr(hidden_viewer, '_add_legend_to_scene'):
                legend_items = hidden_viewer._add_legend_to_scene()
            
            # Method 1: Try PyQtGraph ImageExporter with high DPI
            if hasattr(hidden_viewer, 'glw') and hasattr(hidden_viewer.glw, 'scene'):
                try:

                    exporter = ImageExporter(hidden_viewer.glw.scene())
                    
                    # Set high-quality parameters for 300 DPI equivalent
                    # Standard size: 1000x700 pixels
                    # For 300 DPI at ~3.33 x 2.33 inches = 1000 x 700 pixels
                    # Scale up by 3 for super high quality
                    exporter.parameters()['width'] = 3000   # 3x scaling for super quality
                    exporter.parameters()['height'] = 2100  # Maintain aspect ratio
                    
                    # Export the image
                    exporter.export(output_path)
                    
                    # Verify file exists and has content
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:  # At least 1KB
                        logger.debug(f"[DEBUG] High-quality PNG exported: {os.path.getsize(output_path)} bytes")
                        return True
                    else:
                        logger.debug(f"[WARNING] PNG file is too small or doesn't exist")
                        return False

                except Exception as e:
                    logger.debug(f"[WARNING] PyQtGraph ImageExporter failed: {e}")
                    return False
            
            # Method 2: Alternative approach using widget grab
            try:

                # Grab the widget as pixmap with high DPI
                pixmap = hidden_viewer.grab()
                
                # Scale up the pixmap for higher quality
                scaled_pixmap = pixmap.scaled(
                    pixmap.width() * 3,  # 3x scaling
                    pixmap.height() * 3,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Save as PNG
                success = scaled_pixmap.save(output_path, "PNG", quality=100)
                
                if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.debug(f"[DEBUG] High-quality PNG exported via widget grab: {os.path.getsize(output_path)} bytes")
                    return True
                else:
                    logger.debug(f"[WARNING] Widget grab PNG export failed")
                    return False

            except Exception as e:
                logger.debug(f"[ERROR] Widget grab method failed: {e}")
                return False
        
        except Exception as e:
            logger.debug(f"[ERROR] High-quality PNG export completely failed: {e}")
            return False
        finally:
            # Always remove legend items after export
            if legend_items and hasattr(hidden_viewer, '_remove_legend_from_scene'):
                hidden_viewer._remove_legend_from_scene(legend_items)
                
    def _create_export_metadata(self):
        """Create metadata DataFrame for exports"""
        accepted_count = len(self.export_list_df[self.export_list_df['Quality'] == 'Accepted']) if not self.export_list_df.empty and 'Quality' in self.export_list_df.columns else 0
        declined_count = len(self.export_list_df[self.export_list_df['Quality'] == 'Declined']) if not self.export_list_df.empty and 'Quality' in self.export_list_df.columns else 0
        metadata = [
            {'Parameter': 'Export_Date', 'Value': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
            {'Parameter': 'Total_Export_List_Items', 'Value': len(self.export_list_df)},
            {'Parameter': 'Accepted_Spectra', 'Value': accepted_count},
            {'Parameter': 'Declined_Spectra', 'Value': declined_count}
        ]

        return pd.DataFrame(metadata)
            
    def _clear_export_list(self):
        """Clear the export list"""
        reply = QMessageBox.question(self, "Confirm Clear", 
            "Are you sure you want to clear the export list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            self.export_list_df = pd.DataFrame(columns=self.export_list_df.columns)
            self._update_export_table()
            
    def get_main_window(self):
        """Get reference to main application window"""
        from utils.utility_classes.widgets import get_main_window
        return get_main_window(self, 'mass_spec_viewer')
        
    
    def _create_modal_progress_dialog(self, title, total_items):
        """Create a modal progress dialog that locks the app - ENHANCED styling"""
        # Create modal progress dialog
        progress = QProgressDialog(self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)  # LOCK THE APP
        progress.setMinimumDuration(0)  # Show immediately
        progress.setCancelButton(None)  # No cancel button during export
        progress.setAutoClose(False)  # Don't auto-close
        progress.setAutoReset(False)   # Don't auto-reset
        
        # ENHANCED: Set fixed size and position
        progress.setFixedSize(450, 120)
        progress.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        
        # Center on parent
        if self.parent():
            parent_geo = self.parent().geometry()
            x = parent_geo.x() + (parent_geo.width() - 450) // 2
            y = parent_geo.y() + (parent_geo.height() - 120) // 2
            progress.move(x, y)
        
        # ENHANCED: Custom styling to match experiment loading style
        progress.setStyleSheet(f"""
            QProgressDialog {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border: 2px solid {EditorConstants.PRIMARY_BLUE()};
                border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                font-family: {EditorConstants.FONT_FAMILY()};
            }}
            QLabel {{
                color: {EditorConstants.TEXT_COLOR()};
                font-size: 12px;
                font-weight: bold;
                padding: 10px;
            }}
            QProgressBar {{
                border: 2px solid {EditorConstants.GRAY_300()};
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
                background-color: {EditorConstants.GRAY_100()};
                text-align: center;
                font-weight: bold;
                font-size: 11px;
                color: {EditorConstants.TEXT_COLOR()};
                min-height: 20px;
                max-height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {EditorConstants.PRIMARY_BLUE()}, 
                    stop:1 {EditorConstants.LIGHT_BLUE()});
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
            }}
        """)
        
        # Set up percentage-based progress (0-100)
        progress.setRange(0, 100)
        progress.setValue(0)
        
        # Custom label for status
        progress.setLabelText("Initializing export...")
        
        return progress

    def _update_progress_percentage(self, progress, current_item, total_items, current_status="Processing"):
        """Update progress as percentage with detailed status"""
        if total_items == 0:
            percentage = 100
        else:
            percentage = int((current_item / total_items) * 100)
        
        progress.setValue(percentage)
        
        # ENHANCED: Show both percentage and item count
        status_text = f"{current_status}... ({current_item}/{total_items}) - {percentage}%"
        progress.setLabelText(status_text)
        
        # Force immediate UI update
        QApplication.processEvents()

