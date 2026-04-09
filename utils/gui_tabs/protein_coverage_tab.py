"""
Protein Coverage Tab Manager
Handles the protein coverage analysis and visualization tab in the GUI
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableWidget, QTableWidgetItem, QLineEdit, QSpinBox,
    QHeaderView, QSplitter, QFileDialog, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from pathlib import Path
import pandas as pd
import traceback

# Import the protein coverage analysis classes
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from utils.protein_coverage.protein_coverage import (
    FastaParser, 
    PeptideMapper, 
    ProteinCoverageAnalyzer,
    CoverageHTMLGenerator
)

from utils.style.style import EditorConstants


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom table item that sorts numerically instead of alphabetically"""
    
    def __init__(self, text, numeric_value):
        super().__init__(text)
        self.numeric_value = numeric_value
    
    def __lt__(self, other):
        """Enable proper numeric sorting"""
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class CoverageAnalysisWorker(QThread):
    """Worker thread for running protein coverage analysis"""
    finished = pyqtSignal(object)  # Emits coverage DataFrame
    error = pyqtSignal(str)
    
    def __init__(self, fasta_path, psm_df):
        super().__init__()
        self.fasta_path = fasta_path
        self.psm_df = psm_df
        
    def run(self):
        """Run the analysis in background thread"""
        try:
            # ProteinCoverageAnalyzer expects a FASTA path, not a proteins dict
            # It will parse the FASTA internally
            analyzer = ProteinCoverageAnalyzer(self.fasta_path)
            coverage_df = analyzer.analyze_psm_data(self.psm_df)
            
            self.finished.emit(coverage_df)
            
        except Exception as e:
            self.error.emit(f"Error during analysis: {str(e)}\n{traceback.format_exc()}")


class ProteinCoverageTable(QTableWidget):
    """Custom table widget for displaying protein coverage results"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_table()
        
    def _setup_table(self):
        """Setup table appearance and behavior"""
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        
        # Set headers
        headers = ["Protein", "Description", "Length", "Coverage %", 
                   "Covered AA", "Unique Peptides", "Modified Sites"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        
        # Column resize behavior
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Protein
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Description
        for i in range(2, len(headers)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        
        # Apply styling
        from utils.style.style import StyleSheet
        StyleSheet.apply_table_styling(self)
        
    def populate_data(self, coverage_df):
        """Populate table with coverage data"""
        if coverage_df.empty:
            self.setRowCount(0)
            return
            
        self.setSortingEnabled(False)
        self.setRowCount(len(coverage_df))
        
        for row_idx, (_, row) in enumerate(coverage_df.iterrows()):
            # Protein
            item = QTableWidgetItem(str(row.get('Protein', '')))
            self.setItem(row_idx, 0, item)
            
            # Description
            item = QTableWidgetItem(str(row.get('Description', '')))
            self.setItem(row_idx, 1, item)
            
            # Length - use numeric sorting
            length = int(row.get('Length', 0))
            item = NumericTableWidgetItem(str(length), length)
            self.setItem(row_idx, 2, item)
            
            # Coverage % - use numeric sorting
            coverage = float(row.get('Coverage_Percent', 0.0))
            item = NumericTableWidgetItem(f"{coverage:.2f}", coverage)
            self.setItem(row_idx, 3, item)
            
            # Covered AA - use numeric sorting based on covered count
            covered = int(row.get('Covered_AAs', 0))
            total = int(row.get('Length', 0))
            item = NumericTableWidgetItem(f"{covered} / {total}", covered)
            self.setItem(row_idx, 4, item)
            
            # Unique Peptides - use numeric sorting
            peptides = int(row.get('Unique_Peptides', 0))
            item = NumericTableWidgetItem(str(peptides), peptides)
            self.setItem(row_idx, 5, item)
            
            # Modified Sites - use numeric sorting
            mod_sites = row.get('Modification_Sites', {})
            num_mod_sites = len(mod_sites) if isinstance(mod_sites, dict) else 0
            item = NumericTableWidgetItem(str(num_mod_sites), num_mod_sites)
            self.setItem(row_idx, 6, item)
        
        self.setSortingEnabled(True)
        # Sort by coverage % descending by default
        self.sortItems(3, Qt.SortOrder.DescendingOrder)
    
    def get_selected_protein_data(self, coverage_df):
        """Get the full protein data for the selected row"""
        selected_rows = self.selectedIndexes()
        if not selected_rows:
            return None
            
        row = selected_rows[0].row()
        protein_accession = self.item(row, 0).text()
        
        # Find matching row in DataFrame
        matching = coverage_df[coverage_df['Protein'] == protein_accession]
        if matching.empty:
            return None
            
        return matching.iloc[0].to_dict()


class ProteinCoverageTabManager:
    """Manager for the protein coverage analysis tab"""
    
    def __init__(self, main_app):
        self.main_app = main_app
        self.fasta_path = None
        self.coverage_df = pd.DataFrame()
        self.current_psm_df = pd.DataFrame()
        self.worker = None
        self.is_analyzing = False  # Flag to prevent concurrent analyses
        self.progress_dialog = None  # Progress dialog for analysis
        
    def setup_protein_coverage_tab(self):
        """Setup the protein coverage tab UI"""
        # Create main tab widget
        self.tab_widget = QWidget()
        main_layout = QVBoxLayout(self.tab_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create stacked layout for switching between placeholder and actual content
        from PyQt6.QtWidgets import QStackedWidget
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)
        
        # Page 0: Placeholder (no FASTA loaded)
        self.placeholder_widget = self._create_placeholder_widget()
        self.stacked_widget.addWidget(self.placeholder_widget)
        
        # Page 1: Actual coverage interface
        self.coverage_widget = self._create_coverage_widget()
        self.stacked_widget.addWidget(self.coverage_widget)
        
        # Start with placeholder
        self.stacked_widget.setCurrentIndex(0)
        
        # Add tab to main GUI
        self.main_app.main_tab_widget.addTab(self.tab_widget, "Protein Coverage")
        
        return self.tab_widget
    
    def _create_placeholder_widget(self):
        """Create placeholder widget shown when no FASTA is loaded"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Icon or image (optional)
        message_label = QLabel("📊 Protein Coverage Analysis")
        message_label.setStyleSheet(f"""
            QLabel {{
                {EditorConstants.get_font_string("bold")}
                font-size: 24px;
                color: {EditorConstants.GRAY_700()};
                padding: 20px;
            }}
        """)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label)
        
        # Instruction text
        instruction_label = QLabel(
            "Please load a FASTA file to analyze protein coverage.\n\n"
            "Go to: File → Load FASTA File"
        )
        instruction_label.setStyleSheet(f"""
            QLabel {{
                {EditorConstants.get_font_string("normal")}
                font-size: 14px;
                color: {EditorConstants.GRAY_600()};
                padding: 10px;
            }}
        """)
        instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(instruction_label)
        
        # Load button
        load_button = QPushButton("Load FASTA File")
        load_button.setMinimumHeight(40)
        load_button.setMaximumWidth(200)
        load_button.clicked.connect(self.load_fasta_file)
        load_button.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.addStretch()
        button_layout.addWidget(load_button)
        button_layout.addStretch()
        layout.addWidget(button_container)
        
        layout.addStretch()
        
        return widget
    
    def _create_coverage_widget(self):
        """Create the actual protein coverage analysis widget"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Top control bar
        control_bar = QWidget()
        control_layout = QHBoxLayout(control_bar)
        control_layout.setContentsMargins(5, 5, 5, 5)
        
        # FASTA info label
        self.fasta_info_label = QLabel("No FASTA loaded")
        self.fasta_info_label.setStyleSheet(f"""
            QLabel {{
                {EditorConstants.get_font_string("normal")}
                color: {EditorConstants.GRAY_700()};
                padding: 5px;
            }}
        """)
        control_layout.addWidget(self.fasta_info_label)
        
        control_layout.addStretch()
        
        # Reload button
        reload_button = QPushButton("Reload FASTA")
        reload_button.clicked.connect(self.load_fasta_file)
        reload_button.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        control_layout.addWidget(reload_button)
        
        layout.addWidget(control_bar)
        
        # Filter controls
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(5, 5, 5, 5)
        
        filter_layout.addWidget(QLabel("Filter:"))
        
        self.protein_filter = QLineEdit()
        self.protein_filter.setPlaceholderText("Protein accession...")
        self.protein_filter.textChanged.connect(self.apply_filters)
        self.protein_filter.setStyleSheet(EditorConstants.get_lineedit_style())
        filter_layout.addWidget(self.protein_filter)
        
        clear_filter_btn = QPushButton("Clear Filters")
        clear_filter_btn.clicked.connect(self.clear_filters)
        clear_filter_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        filter_layout.addWidget(clear_filter_btn)
        
        layout.addWidget(filter_bar)
        
        # Splitter for table and HTML viewer
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Protein coverage table
        self.coverage_table = ProteinCoverageTable()
        self.coverage_table.itemSelectionChanged.connect(self._on_protein_selected)
        splitter.addWidget(self.coverage_table)
        
        # HTML viewer for coverage visualization
        self.html_viewer = QWebEngineView()
        splitter.addWidget(self.html_viewer)
        
        # Set initial sizes (60% table, 40% viewer)
        splitter.setSizes([600, 400])
        
        layout.addWidget(splitter)
        
        return widget
    
    def load_fasta_file(self):
        """Load a FASTA file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self.main_app,
            "Select FASTA File",
            "",
            "FASTA Files (*.fasta *.fa *.faa);;All Files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            # Clear previous results when loading new FASTA
            self.coverage_df = pd.DataFrame()
            self.coverage_table.setRowCount(0)
            self.html_viewer.setHtml("")
            
            # Verify it's a valid FASTA file by trying to parse it
            proteins_dict = FastaParser.parse_fasta(file_path)
            
            if not proteins_dict:
                QMessageBox.warning(
                    self.main_app,
                    "Invalid FASTA",
                    "No protein sequences found in the selected file."
                )
                return
            
            self.fasta_path = file_path
            self.fasta_info_label.setText(
                f"FASTA: {Path(file_path).name} ({len(proteins_dict)} proteins)"
            )
            
            # Switch to coverage interface
            self.stacked_widget.setCurrentIndex(1)
            
            # Show success message
            self.main_app.show_toast_message(
                f"✓ Loaded {len(proteins_dict)} proteins from FASTA",
                3000
            )
            
            # Check if PSM data exists and trigger analysis with slight delay
            # This allows the UI to fully update before showing progress dialog
            if (hasattr(self.main_app, 'experiment_data_manager') and
                hasattr(self.main_app.experiment_data_manager, 'merged_df') and
                not self.main_app.experiment_data_manager.merged_df.empty):
                
                print("[DEBUG] Found existing PSM data, will trigger analysis")
                self.current_psm_df = self.main_app.experiment_data_manager.merged_df.copy()
                
                # Use QTimer to defer analysis slightly, allowing UI to update
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.run_analysis)
            else:
                print(f"[DEBUG] No PSM data available yet for automatic analysis")
                
        except Exception as e:
            QMessageBox.critical(
                self.main_app,
                "Error Loading FASTA",
                f"Failed to load FASTA file:\n{str(e)}"
            )
    
    def set_psm_data(self, psm_df):
        """Update PSM data from main app and run analysis if FASTA is loaded"""
        print(f"[DEBUG] protein_coverage_tab.set_psm_data called with {len(psm_df) if not psm_df.empty else 0} records")
        self.current_psm_df = psm_df.copy() if not psm_df.empty else pd.DataFrame()
        
        # Auto-analyze if we have both FASTA and PSM data (and not already analyzing)
        if self.fasta_path is not None and not self.current_psm_df.empty and not self.is_analyzing:
            print(f"[DEBUG] Triggering analysis from set_psm_data (FASTA: loaded, PSM records: {len(self.current_psm_df)})")
            # Use QTimer to defer analysis slightly, preventing window flash
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self.run_analysis)
        elif self.is_analyzing:
            print(f"[DEBUG] Skipping analysis trigger - already analyzing")
    
    def run_analysis(self):
        """Run protein coverage analysis"""
        # Check if already analyzing
        if self.is_analyzing:
            print("[DEBUG] Analysis already in progress, skipping")
            return
            
        if not self.fasta_path:
            print("[DEBUG] Cannot run analysis: No FASTA file loaded")
            return
            
        if self.current_psm_df.empty:
            print("[DEBUG] Cannot run analysis: No PSM data available")
            return
        
        # Check if previous worker is still running
        if self.worker is not None and self.worker.isRunning():
            print("[DEBUG] Previous worker still running, queuing new analysis request...")
            # Don't block! Just disconnect old worker and let it finish
            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
            except:
                pass
            # Worker will be garbage collected when done
            self.worker = None
        
        # Set analyzing flag
        self.is_analyzing = True
        print(f"[DEBUG] Starting protein coverage analysis...")
        
        # Create progress dialog (modal but non-blocking)
        self.progress_dialog = QProgressDialog(
            "Analyzing protein coverage...",
            "Cancel",
            0,
            0,  # 0 = indeterminate/busy indicator
            self.main_app
        )
        self.progress_dialog.setWindowTitle("Protein Coverage Analysis")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)  # Show immediately
        self.progress_dialog.setCancelButton(None)  # No cancel button (can't safely cancel)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.setAutoReset(True)
        
        # Show the dialog
        self.progress_dialog.show()
        
        # Force process events to ensure dialog is visible
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        
        # Create and start worker thread
        self.worker = CoverageAnalysisWorker(self.fasta_path, self.current_psm_df)
        self.worker.finished.connect(self._on_analysis_complete)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.start()
    
    def _on_analysis_complete(self, coverage_df):
        """Handle completed analysis"""
        # Close progress dialog first
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        
        self.coverage_df = coverage_df
        self.coverage_table.populate_data(coverage_df)
        
        # Clear analyzing flag
        self.is_analyzing = False
        
        # Show summary
        num_proteins = len(coverage_df)
        avg_coverage = coverage_df['Coverage_Percent'].mean() if not coverage_df.empty else 0
        
        print(f"[DEBUG] Analysis complete: {num_proteins} proteins analyzed")
        
        self.main_app.show_toast_message(
            f"✓ Analyzed {num_proteins} proteins (Avg coverage: {avg_coverage:.1f}%)",
            4000
        )
        
        # Clean up worker reference
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
    
    def _on_analysis_error(self, error_msg):
        """Handle analysis error"""
        # Close progress dialog first
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        
        # Clear analyzing flag
        self.is_analyzing = False
        
        print(f"[DEBUG] Analysis error: {error_msg}")
        
        QMessageBox.critical(
            self.main_app,
            "Analysis Error",
            f"Failed to analyze protein coverage:\n\n{error_msg}"
        )
        
        # Clean up worker reference
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
    
    def _on_protein_selected(self):
        """Handle protein selection in table"""
        # Safety checks to prevent crashes
        if self.coverage_df.empty:
            print("[DEBUG] Coverage DataFrame is empty, skipping protein selection")
            return
        
        # Additional safety: check if we're in the middle of an analysis
        if self.is_analyzing:
            print("[DEBUG] Analysis in progress, deferring protein selection")
            return
            
        protein_data = self.coverage_table.get_selected_protein_data(self.coverage_df)
        if not protein_data:
            print("[DEBUG] No protein data found for selected row")
            return
        
        try:
            # Validate that all required keys exist
            required_keys = ['Protein', 'Description', 'Sequence', 
                           'Covered_Positions', 'Peptide_Mappings', 'Coverage_Percent']
            
            for key in required_keys:
                if key not in protein_data:
                    print(f"[DEBUG] Missing required key '{key}' in protein data")
                    return
            
            # Generate HTML visualization with description parameter
            html = CoverageHTMLGenerator.generate_coverage_html(
                protein_accession=protein_data['Protein'],
                description=protein_data['Description'],
                sequence=protein_data['Sequence'],
                covered_positions=protein_data['Covered_Positions'],
                peptide_mappings=protein_data['Peptide_Mappings'],
                coverage_percent=protein_data['Coverage_Percent'],
                modification_sites=protein_data.get('Modification_Sites', {})
            )
            
            self.html_viewer.setHtml(html)
            
        except Exception as e:
            print(f"[ERROR] Error generating coverage HTML: {e}")
            traceback.print_exc()
            # Show error message to user
            QMessageBox.warning(
                self.main_app,
                "Visualization Error",
                f"Failed to generate protein coverage visualization:\n{str(e)}"
            )
    
    def apply_filters(self):
        """Apply filters to coverage table"""
        if self.coverage_df.empty:
            return
        
        filtered_df = self.coverage_df.copy()
        
        # Protein filter
        protein_text = self.protein_filter.text().strip()
        if protein_text:
            filtered_df = filtered_df[
                filtered_df['Protein'].str.contains(protein_text, case=False, na=False) |
                filtered_df['Description'].str.contains(protein_text, case=False, na=False)
            ]
        
        # Update table
        self.coverage_table.populate_data(filtered_df)
    
    def clear_filters(self):
        """Clear all filters"""
        self.protein_filter.clear()
        self.apply_filters()
    
    def cleanup(self):
        """Cleanup resources when closing"""
        print("[DEBUG] Cleaning up protein coverage tab resources...")
        
        # Close progress dialog if it exists
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        
        # Stop any running worker thread (non-blocking)
        if self.worker is not None:
            if self.worker.isRunning():
                print("[DEBUG] Requesting stop for protein coverage worker thread...")
                # Disconnect signals to prevent callbacks during shutdown
                try:
                    self.worker.finished.disconnect()
                    self.worker.error.disconnect()
                except:
                    pass
                # Request termination but don't wait (non-blocking)
                self.worker.requestInterruption()
                self.worker.quit()
            
            self.worker = None
        
        self.is_analyzing = False
        print("[DEBUG] Protein coverage tab cleanup complete")
    
    def update_theme(self, theme_name):
        """Update protein coverage tab theme"""
        print(f"[DEBUG] Updating protein coverage tab theme to {theme_name}")
        
        # Update table styling
        if hasattr(self, 'coverage_table'):
            from utils.style.style import StyleSheet
            StyleSheet.apply_table_styling(self.coverage_table)
        
        # Update HTML viewer background
        if hasattr(self, 'html_viewer'):
            # Set the background color for QWebEngineView
            page = self.html_viewer.page()
            if page:
                page.setBackgroundColor(QColor(EditorConstants.BACKGROUND_COLOR()))
        
        # Update filter widgets
        if hasattr(self, 'protein_filter'):
            self.protein_filter.setStyleSheet(EditorConstants.get_lineedit_style())
        
        # Update info labels
        if hasattr(self, 'fasta_info_label'):
            self.fasta_info_label.setStyleSheet(f"""
                QLabel {{
                    {EditorConstants.get_font_string("normal")}
                    color: {EditorConstants.GRAY_700()};
                    padding: 5px;
                }}
            """)
        
        print(f"[DEBUG] Protein coverage tab theme updated")
