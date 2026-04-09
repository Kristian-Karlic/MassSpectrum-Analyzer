from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer
import time
import pandas as pd
from utils.utilities import TableUtils, InputValidator, UIHelpers, IonCollectionUtils, DataGatherer, IonTypeGenerator
from utils.utilities import FileProcessingUtils
from utils.utilities import MockDataGenerator
import traceback
import logging

logger = logging.getLogger(__name__)

class EventHandlers:
    def __init__(self, main_app):
        self.main_app = main_app
        
        # Event state tracking
        self._skip_adaptive_update = False
        self._has_manual_changes = False
        self._last_change_time = None
        self._update_timer = None
        self._populating_table = False
    
    def connect_all_signals(self):
        """Connect all signals for the application"""
        self._connect_input_signals()
        self._connect_table_signals()
        self._connect_checkbox_signals()
        self._connect_manager_signals()
        self._connect_scan_selection_signals()
        self._connect_fragmentation_signals()
    
    def _connect_input_signals(self):
        """Connect input field signals"""
        # Peptide input
        self.main_app.peptide_input.textChanged.connect(self.on_peptide_changed)
        
        # Spinbox signals
        self.main_app.max_charge_input.valueChanged.connect(self.on_charge_changed)
        self.main_app.ppm_tolerance_input.valueChanged.connect(self.on_ppm_tolerance_changed)
        self.main_app.text_annotation_threshold.valueChanged.connect(self.on_text_threshold_changed)
        self.main_app.max_neutral_losses_input.valueChanged.connect(self.on_neutral_losses_changed)
        
        # Checkbox signals
        self.main_app.enable_direct_scan_checkbox.stateChanged.connect(self.on_direct_scan_toggle)
    
    def _connect_table_signals(self):
        """Connect table-related signals"""
        # m/z table changes
        self.main_app.mz_table.itemChanged.connect(self.on_mz_table_changed)
        
        # Clear button
        self.main_app.clear_mz_button.clicked.connect(self.on_clear_mz_table)
        
        # Custom ion table context menu
        if hasattr(self.main_app, 'selected_custom_ions_table'):
            self.main_app.selected_custom_ions_table.customContextMenuRequested.connect(
                self.main_app._show_custom_ion_context_menu
            )
        
        # Diagnostic ion table context menu
        if hasattr(self.main_app, 'selected_diagnostic_ions_table'):
            self.main_app.selected_diagnostic_ions_table.customContextMenuRequested.connect(
                self.main_app._show_diagnostic_ion_context_menu
            )
    
    def _connect_checkbox_signals(self):
        """Connect checkbox signals for ion types"""
        # Normal ion type checkboxes
        for checkbox in self.main_app.normal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_ion_type_changed)
        
        # Neutral loss ion type checkboxes
        for checkbox in self.main_app.neutral_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_ion_type_changed)
        
        # Internal ion type checkboxes
        for checkbox in self.main_app.internal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_ion_type_changed)
    
    def _connect_manager_signals(self):
        """Connect signals from managers"""

        # Fragmentation tab manager signals
        if hasattr(self.main_app, 'fragmentation_tab_manager'):
            # Connect comparison-related signals if they exist
            pass
        
        # Persistent fragmentation manager signals
        if self.main_app.persistent_fragmentation_manager:
            self.main_app.persistent_fragmentation_manager.finished.connect(
                self.on_adaptive_fragmentation_finished
            )
            self.main_app.persistent_fragmentation_manager.error.connect(
                self.on_fragmentation_error
            )
            self.main_app.persistent_fragmentation_manager.cacheHit.connect(
                self.on_cache_hit
            )
            self.main_app.persistent_fragmentation_manager.cacheMiss.connect(
                self.on_cache_miss
            )
    
    def _connect_scan_selection_signals(self):
        """Connect direct scan selection signals"""
        if hasattr(self.main_app, 'extract_scan_button'):
            self.main_app.extract_scan_button.clicked.connect(self.on_extract_scan_clicked)
    
    def _connect_fragmentation_signals(self):
        """Connect fragmentation-related signals"""
        # Dropdown signals for custom ions and diagnostic ions
        if hasattr(self.main_app, 'custom_ion_dropdown'):
            self.main_app.custom_ion_dropdown.item_selected.connect(
                self.on_custom_ion_selected
            )
        
        if hasattr(self.main_app, 'diagnostic_ion_dropdown'):
            self.main_app.diagnostic_ion_dropdown.item_selected.connect(
                self.on_diagnostic_ion_selected
            )
    
    # ================================================================
    # INPUT EVENT HANDLERS
    # ================================================================
    
    def on_peptide_changed(self):
        """Handle peptide sequence changes"""
        logger.info("[EVENT] Peptide sequence changed")
        
        # Update modification table
        peptide_sequence = self.main_app.peptide_input.text()
        self.main_app.annotation_tab_manager.set_peptide_sequence(peptide_sequence)
        
        # If we have parsed modifications but no interactive ones yet, use the parsed ones
        if hasattr(self.main_app, 'current_parsed_mods') and self.main_app.current_parsed_mods:
            self.main_app.annotation_tab_manager.set_modifications(self.main_app.current_parsed_mods)
        
        # Trigger adaptive update
        self.on_settings_changed()
    
    def on_charge_changed(self):
        """Handle max charge changes"""
        logger.info("[EVENT] Max charge changed")
        self.validate_fragmentation_inputs()
        self.on_settings_changed()
    
    def on_ppm_tolerance_changed(self):
        """Handle PPM tolerance changes"""
        logger.info("[EVENT] PPM tolerance changed")
        # Update mass spec viewer through annotation manager
        self.main_app.annotation_tab_manager.update_y_axis_limits()
        self.on_settings_changed()
    
    def on_text_threshold_changed(self):
        """Handle text annotation threshold changes"""
        logger.info("[EVENT] Text annotation threshold changed")
        # Update mass spec viewer through annotation manager
        self.main_app.annotation_tab_manager.update_text_annotation_threshold()
        self.on_settings_changed()
    
    def on_neutral_losses_changed(self):
        """Handle max neutral losses changes"""
        logger.info("[EVENT] Max neutral losses changed")
        self.on_settings_changed()
    
    
    def on_direct_scan_toggle(self, state):
        """Handle direct scan mode toggle"""
        logger.info(f"[EVENT] Direct scan mode toggled: {bool(state)}")
        enabled = bool(state)
        
        # Enable/disable controls
        self.main_app.raw_file_combo.setEnabled(enabled)
        self.main_app.scan_number_input.setEnabled(enabled)
        self.main_app.extract_scan_button.setEnabled(enabled)
        
        # Update raw file dropdown when enabled
        if enabled:
            
            FileProcessingUtils.update_raw_file_dropdown(
                self.main_app.raw_file_combo, 
                self.main_app.experiment_data_manager.raw_files
            )
            
            if not self.main_app.experiment_data_manager.raw_files:
                UIHelpers.show_validation_error(
                    self.main_app,
                    "No Raw Files",
                    "Please load raw files first using File -> Load Raw data"
                )
                # Disable the checkbox if no files available
                self.main_app.enable_direct_scan_checkbox.setChecked(False)
        else:
            # Clear the dropdown when disabled
            self.main_app.raw_file_combo.clear()
            self.main_app.scan_number_input.clear()
    
    # ================================================================
    # TABLE EVENT HANDLERS
    # ================================================================
    
    def on_mz_table_changed(self):
        """Handle m/z table changes"""
        if self._populating_table:
            return
            
        logger.info("[EVENT] m/z table changed")
        self.validate_fragmentation_inputs()
        self.on_settings_changed()
    
    def on_clear_mz_table(self):
        """Handle clear m/z table button"""
        logger.info("[EVENT] Clear m/z table clicked")
        self.main_app.mz_table.clearContents()
        self.main_app.mz_table.setRowCount(10)  # Reset to default rows
        UIHelpers.show_success_message(self.main_app, "m/z and intensity table cleared")
        self.validate_fragmentation_inputs()
        self.on_settings_changed()
    
    # ================================================================
    # CHECKBOX EVENT HANDLERS
    # ================================================================
    
    def on_ion_type_changed(self):
        """Handle ion type checkbox changes"""
        logger.info("[EVENT] Ion type selection changed")
        self.on_settings_changed()
    
    # ================================================================
    # MANAGER EVENT HANDLERS
    # ================================================================
    
    def on_peptide_selected(self, peptide: str, parsed_mods: list, charge: int, row_data: dict):
        """Handle peptide selection from PSM summary widget"""
        logger.info(f"[EVENT] Peptide selected: {peptide}")
        
        # Prevent adaptive updates during selection
        self._skip_adaptive_update = True
        
        # Store the selected row data for Metadata in graph
        self.main_app.selected_row_data = row_data
        self.main_app.current_parsed_mods = parsed_mods 
        self.main_app.peptide_input.setText(peptide)
        self.main_app.max_charge_input.setValue(charge)

        # Update mass spec viewer through manager
        self.main_app.annotation_tab_manager.set_peptide_sequence(peptide)
        self.main_app.annotation_tab_manager.set_modifications(parsed_mods)

        # Signal to the viewer that a brand-new scan is being loaded,
        # so the next set_data() call resets the x-axis to full range.
        viewer = self.main_app.annotation_tab_manager.mass_spec_viewer
        if viewer is not None:
            viewer._new_scan_pending = True
        
        # Store the modifications immediately
        self.main_app.current_interactive_mods = parsed_mods

        # Update other widgets through manager
        self.main_app.annotation_tab_manager.update_peptide_info(
            peptide=peptide,
            fragmented_bonds="Calculating...",
            annotated_tic="Calculating...",
            matched_data=None
        )

        # Update spectrum tracker
        self._update_spectrum_tracker()

        logger.info(f"Auto-filled peptide={peptide}, charge={charge}, modifications={parsed_mods}")
        
        # Re-enable adaptive updates
        self._skip_adaptive_update = False
        
        self.validate_fragmentation_inputs()
    
    def on_raw_data_extracted(self, mz_array, intensity_array):
        """Handle raw data extraction from PSM summary widget"""
        logger.info("[EVENT] Raw data extracted")
        self._populating_table = True
        try:
            # Populate the table using utility
            data_pairs = list(zip(mz_array, intensity_array))
            TableUtils.populate_two_column_table(self.main_app.mz_table, data_pairs)
        finally:
            self._populating_table = False
        
        self.validate_fragmentation_inputs()
        self.on_settings_changed()
    
    def on_interactive_modifications_changed(self, modifications: list):
        """Handle changes from the interactive peptide widget"""
        logger.info(f"[EVENT] Interactive modifications changed: {modifications}")
        
        # Check if we're currently updating data to prevent recursion
        if getattr(self.main_app.annotation_tab_manager.mass_spec_viewer, '_updating_data', False):
            logger.debug("[DEBUG] Skipping modification update - data is being updated")
            return
        
        # Store the modifications for use in fragmentation
        self.main_app.current_interactive_mods = modifications
        
        # Update the spectrum tracker with new modifications
        self._update_spectrum_tracker()
        
        # Only trigger adaptive update if not in data update mode
        if not self._skip_adaptive_update:
            self.on_settings_changed()
    
    def on_spectrum_accepted(self, spectrum_data):
        """Handle spectrum acceptance from spectrum tracker"""
        logger.info("[EVENT] Spectrum accepted")
        self.main_app.experiment_data_manager.update_spectrum_quality_in_dataframe(
            spectrum_data, "Accepted"
        )
    
    def on_spectrum_declined(self, spectrum_data):
        """Handle spectrum decline from spectrum tracker"""
        logger.info("[EVENT] Spectrum declined")
        self.main_app.experiment_data_manager.update_spectrum_quality_in_dataframe(
            spectrum_data, "Declined"
        )
    
    def on_analysis_requested(self, matched_data):
        """Handle analysis request from peptide info widget - IMPROVED data passing"""
        logger.debug(f"[DEBUG] Analysis requested with matched data type: {type(matched_data)}")
        
        # Get the current matched data from annotation tab if not provided
        if matched_data is None or (hasattr(matched_data, 'empty') and matched_data.empty):
            logger.debug(f"[DEBUG] No matched data provided, getting from annotation tab")
            matched_data = self.main_app.annotation_tab_manager.get_current_matched_data()
        
        if matched_data is None or (hasattr(matched_data, 'empty') and matched_data.empty):
            logger.debug(f"[DEBUG] Still no matched data available")
            # Show message to user
            
            QMessageBox.information(
                self.main_app, 
                "No Data", 
                "No matched spectrum data available for analysis. Please select a peptide first."
            )
            return
        
        logger.debug(f"[DEBUG] Opening analysis dialog with {len(matched_data)} matched peaks")
    
    # ================================================================
    # FRAGMENTATION EVENT HANDLERS
    # ================================================================
    
    def on_adaptive_fragmentation_finished(self, result):
        """Handle completion of adaptive fragmentation calculation"""
        logger.info("[EVENT] Adaptive fragmentation finished")
        try:
            # Hide loading indicator through manager
            self.main_app.annotation_tab_manager.hide_loading_indicator()
            
            if result is None:
                logger.error("[ERROR] Fragmentation result is None")
                return
                
            matched_data, theoretical_data = result
            logger.info(f"[ADAPTIVE] Fragmentation completed - Matched: {len(matched_data)}, Theoretical: {len(theoretical_data)}")
            
            # Get current settings
            peptide = self.main_app.peptide_input.text().strip()
            parsed_mods = self._get_modifications_from_table()
            
            # Add diagnostic ions to both DataFrames
            extra_rows = self._create_diagnostic_ion_rows()
            if extra_rows:
                
                # Add to matched data
                df_custom = pd.DataFrame(extra_rows)
                matched_data = pd.concat([matched_data, df_custom], ignore_index=True)
                
                # Add to theoretical data  
                theoretical_custom = df_custom.copy()
                theoretical_custom["Theoretical Mass"] = theoretical_custom["m/z"]
                theoretical_data = pd.concat([theoretical_data, theoretical_custom], ignore_index=True)

            # Update the mass spec viewer through manager
            self.main_app.annotation_tab_manager.set_mass_spec_data(
                matched_data=matched_data,
                peptide=peptide,
                mod_positions=parsed_mods,
                row_data=self.main_app.selected_row_data or {},
                theoretical_data=theoretical_data
            )
            
            # Update info widget through manager
            if self.main_app.annotation_tab_manager.peptide_info_widget:
                fragmented_bonds = self.main_app.annotation_tab_manager.peptide_info_widget.calculate_fragmented_bonds(peptide, matched_data)
                annotated_tic = self.main_app.annotation_tab_manager.peptide_info_widget.calculate_annotated_percentage(matched_data)
                
                self.main_app.annotation_tab_manager.update_peptide_info(
                    peptide=peptide,
                    fragmented_bonds=fragmented_bonds,
                    annotated_tic=annotated_tic,
                    matched_data=matched_data,
                    theoretical_data=theoretical_data
                )
            
            # Update spectrum tracker
            self._update_spectrum_tracker()
            
            #  Notify analysis tab that new annotation data is available
            if (hasattr(self.main_app, 'analysis_tab_manager') and 
                hasattr(self.main_app.analysis_tab_manager, 'on_annotation_data_changed')):
                self.main_app.analysis_tab_manager.on_annotation_data_changed()
                logger.debug("[DEBUG] Notified analysis tab of new annotation data")
            
            # ENHANCED: Force analysis update if analysis tab is active
            current_tab_index = self.main_app.main_tab_widget.currentIndex()
            current_tab = self.main_app.main_tab_widget.widget(current_tab_index)
            
            if current_tab and current_tab.objectName() == "analysis_tab":
                logger.debug("[DEBUG] Analysis tab is active, forcing immediate analysis update")
                # Small delay to ensure data is fully set before analysis
                
                QTimer.singleShot(100, self.main_app.analysis_tab_manager.refresh_all_analysis)
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to handle fragmentation result: {e}")

            traceback.print_exc()
            
            # Make sure to hide loading indicator even on error
            self.main_app.annotation_tab_manager.hide_loading_indicator()
        
    def on_fragmentation_error(self, error_message):
        """Handle fragmentation errors from persistent worker"""
        logger.info(f"[EVENT] Fragmentation error: {error_message}")
        
        # Hide loading indicator
        self.main_app.annotation_tab_manager.hide_loading_indicator()
        
        # Show error message to user
        QMessageBox.warning(
            self.main_app,
            "Fragmentation Error",
            f"An error occurred during fragmentation:\n{error_message}",
            QMessageBox.StandardButton.Ok
        )
    
    def on_cache_hit(self):
        """Handle cache hit signal from worker"""
        self.main_app.cache_hit_count += 1
    
    def on_cache_miss(self):
        """Handle cache miss signal from worker"""
        self.main_app.cache_miss_count += 1
    
    # ================================================================
    # SCAN SELECTION EVENT HANDLERS
    # ================================================================
    
    def on_extract_scan_clicked(self):
        """Handle extract scan button click"""
        logger.info("[EVENT] Extract scan clicked")
        selected_file = self.main_app.raw_file_combo.currentText()
        scan_number = self.main_app.scan_number_input.text()
        
        # Validate inputs
        if not selected_file:
            UIHelpers.show_validation_error(
                self.main_app, 
                "Input Error", 
                "Please select a raw file from the dropdown."
            )
            return
        
        if not scan_number.strip():
            UIHelpers.show_validation_error(
                self.main_app, 
                "Input Error", 
                "Please enter a scan number."
            )
            return
        
        # Extract the scan data
        result = self.main_app.experiment_data_manager.extract_scan_data(selected_file, scan_number)
        
        if result:
            mz_array, intensity_array = result
            
            # Use utility for table population
            data_pairs = list(zip(mz_array, intensity_array))
            
            # Set populating flag to prevent cascading events
            self.set_populating_table(True)
            try:
                TableUtils.populate_two_column_table(self.main_app.mz_table, data_pairs)
            finally:
                self.set_populating_table(False)
            
            # Set default row data using utility
            self.main_app.selected_row_data = UIHelpers.create_default_row_data(
                charge=self.main_app.max_charge_input.value(),
                scan_number=scan_number,
                filename=selected_file
            )
            
            # Trigger validation and adaptive update
            self.validate_fragmentation_inputs()
            self.on_settings_changed()
            
            logger.debug(f"[DEBUG] Successfully populated m/z table with {len(data_pairs)} data points")
        
    # ================================================================
    # DROPDOWN EVENT HANDLERS
    # ================================================================
    
    def on_custom_ion_selected(self, selected_row_dict):
        """Handle custom ion selection from dropdown"""
        logger.info(f"[EVENT] Custom ion selected: {selected_row_dict.get('Series Name', 'Unknown')}")
        
        if not selected_row_dict:
            return
        
        # Check for duplicates
        for existing in self.main_app.selected_custom_ions_data:
            if (existing.get('Series Name') == selected_row_dict.get('Series Name') and
                existing.get('Base Ion') == selected_row_dict.get('Base Ion')):
                self.main_app.show_toast_message(f"'{selected_row_dict.get('Series Name')}' is already in the list.")
                return
        
        # Add ion data
        ion_data = {
            'Base Ion': selected_row_dict.get('Base Ion'),
            'Series Name': selected_row_dict.get('Series Name'),
            'Mass Offset': selected_row_dict.get('Mass Offset'),
            'Color': selected_row_dict.get('Color', "#CCCCCC"),
            'Restriction': selected_row_dict.get('Restriction', '')
        }
        self.main_app.selected_custom_ions_data.append(ion_data)
        self.main_app._update_selected_custom_ions_table()
        self.on_settings_changed()
        self.main_app.show_toast_message(f"Added '{ion_data['Series Name']}' to selected custom ions.")
    
    def on_diagnostic_ion_selected(self, selected_row_dict):
        """Handle diagnostic ion selection from dropdown"""
        logger.info(f"[EVENT] Diagnostic ion selected: {selected_row_dict.get('Name', 'Unknown')}")
        
        if not selected_row_dict:
            return
        
        # Check for duplicates
        for existing in self.main_app.selected_diagnostic_ions_data:
            if existing.get('Name') == selected_row_dict.get('Name'):
                self.main_app.show_toast_message(f"'{selected_row_dict.get('Name')}' is already in the list.")
                return
        
        # Add ion data
        ion_data = {
            'Name': selected_row_dict.get('Name'),
            'HTML Name': selected_row_dict.get('HTML Name'),
            'Mass': selected_row_dict.get('Mass'),
            'Color': selected_row_dict.get('Color', "#CCCCCC")
        }
        self.main_app.selected_diagnostic_ions_data.append(ion_data)
        self.main_app._update_selected_diagnostic_ions_table()
        self.on_settings_changed()
        self.main_app.show_toast_message(f"Added '{ion_data['Name']}' to selected diagnostic ions.")
    
    # ================================================================
    # ADAPTIVE UPDATE SYSTEM
    # ================================================================
    
    def on_settings_changed(self):
        """Called whenever any setting that affects fragmentation changes"""
        if not self._populating_table:
            logger.info("[EVENT] Settings changed - triggering adaptive update")
        
        # Check if we have manual annotation changes that shouldn't be overridden
        if self._has_manual_changes:
            return
        
        # Check if adaptive updates are temporarily disabled
        if self._skip_adaptive_update:
            return
        
        if self._populating_table:
            return
        
        # Smarter debouncing - shorter delay for simple changes
        if self._update_timer:
            self._update_timer.stop()
        
        # Determine delay based on change type
        delay = self._calculate_optimal_delay()
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self.perform_adaptive_update)
        self._update_timer.setSingleShot(True)
        self._update_timer.start(delay)

    def set_populating_table(self, populating: bool):
        """Set the table population flag to prevent cascading events"""
        self._populating_table = populating

    def _calculate_optimal_delay(self):
        """Calculate optimal delay based on recent activity"""
        current_time = time.time()
        
        # Track when last change occurred
        if self._last_change_time is None:
            self._last_change_time = current_time
            return 500  # First change - quick response
        
        time_since_last = current_time - self._last_change_time
        self._last_change_time = current_time
        
        # If user is actively changing things, use longer delay
        if time_since_last < 1.0:  # Rapid changes
            return 1000
        else:  # Isolated change
            return 400
    
    def perform_adaptive_update(self):
        """Perform the actual fragmentation and matching update"""
        logger.info("[EVENT] Performing adaptive update")
        
        # Check if we have the minimum required data
        peptide = self.main_app.peptide_input.text().strip()
        mz_data = TableUtils.extract_mz_intensity_from_table(self.main_app.mz_table)
        
        if not peptide or not mz_data:
            # If insufficient data, show mock data
            logger.debug("[DEBUG] Insufficient data for update - loading mock data")
            self._load_mock_data()
            return
        
        # Validate inputs
        max_charge = self.main_app.max_charge_input.value()
        is_valid, error_msg = InputValidator.validate_fragmentation_inputs(
            peptide, max_charge, mz_data
        )
        
        if not is_valid:
            # If invalid, keep current state or show mock data
            logger.debug(f"[DEBUG] Invalid inputs for update: {error_msg}")
            return
        
        logger.debug(f"[DEBUG] Starting fragmentation for peptide: {peptide} with {len(mz_data)} m/z values")
        
        # Perform fragmentation in background thread
        self._run_fragmentation_adaptive()
    
    def _run_fragmentation_adaptive(self):
        """Run adaptive fragmentation calculation"""
        logger.info("[EVENT] Running adaptive fragmentation")
        
        # Show loading indicator through manager
        self.main_app.annotation_tab_manager.show_loading_indicator()
        
        # Gather all the fragmentation parameters
        peptide = self.main_app.peptide_input.text().strip()
        max_charge = self.main_app.max_charge_input.value()
        user_mz_values = TableUtils.extract_mz_intensity_from_table(self.main_app.mz_table)
        modifications = self._get_modifications_from_table()
        ppm_tolerance = self.main_app.ppm_tolerance_input.value()
        max_neutral_losses = self.main_app.max_neutral_losses_input.value()
        calculate_isotopes = self.main_app.calculate_isotopes_checkbox.isChecked()

        # Use dynamic ion types
        selected_ions = IonTypeGenerator.generate_dynamic_ion_types(
            self.main_app.normal_ion_checkboxes,
            self.main_app.neutral_ion_checkboxes,
            max_neutral_losses
        )
        selected_internal_ions = IonCollectionUtils.collect_selected_internal_ions(
            self.main_app.internal_ion_checkboxes
        )

        # Use the new selected ions data for both diagnostic and custom ions
        diagnostic_ions = DataGatherer.gather_diagnostic_ions(self.main_app.selected_diagnostic_ions_data)
        custom_ion_series_list = DataGatherer.gather_custom_ion_series(self.main_app.selected_custom_ions_data)

        # Build modification-specific neutral losses from central DB
        enable_labile = getattr(self.main_app, 'enable_labile_losses_cb', None)
        enable_labile = enable_labile.isChecked() if enable_labile else False
        enable_remainder = getattr(self.main_app, 'enable_remainder_ions_cb', None)
        enable_remainder = enable_remainder.isChecked() if enable_remainder else False
        enable_mod_nl = getattr(self.main_app, 'enable_mod_nl_cb', None)
        enable_mod_nl = enable_mod_nl.isChecked() if enable_mod_nl else False
        mod_neutral_losses = DataGatherer.build_mod_neutral_losses(
            modifications,
            getattr(self.main_app, 'central_mod_db', None),
            enable_labile=enable_labile,
            enable_remainder=enable_remainder,
            enable_mod_nl=enable_mod_nl,
        )

        # Build NL/labile/remainder symbol legend entries so the Modification
        # Legend bar can show e.g.  "* = -97.977 Da (Phospho, NL1)"
        try:
            from utils.peak_matching.peptide_fragmentation import _nl_tag, _rm_tag
            nl_symbol_entries = []
            central_db = getattr(self.main_app, 'central_mod_db', None)
            if mod_neutral_losses and modifications:
                seen = set()
                for mod_idx, (mod_mass, _pos) in enumerate(modifications):
                    nl_cfg = (mod_neutral_losses[mod_idx]
                              if mod_idx < len(mod_neutral_losses) else None)
                    if nl_cfg is None:
                        continue
                    mod_name = (central_db.find_by_mass(mod_mass)
                                if central_db is not None else None) or f"{mod_mass:.4f} Da"
                    for nl_i, nl_mass in enumerate(nl_cfg.get("neutral_losses", [])):
                        if nl_mass <= 0:
                            continue
                        sym = _nl_tag(nl_i)
                        key = (sym, mod_name)
                        if key not in seen:
                            seen.add(key)
                            nl_symbol_entries.append((sym, f"NL{nl_i + 1}", -nl_mass, mod_name))
                    if nl_cfg.get("labile_loss", False):
                        labile = nl_cfg.get("mod_mass", mod_mass)
                        key = ("~", mod_name)
                        if key not in seen:
                            seen.add(key)
                            nl_symbol_entries.append(("~", "Labile loss", -labile, mod_name))
                        for rm_i, rm_mass in enumerate(nl_cfg.get("remainder_ions", [])):
                            if rm_mass <= 0:
                                continue
                            sym = _rm_tag(rm_i)
                            key = (sym, mod_name)
                            if key not in seen:
                                seen.add(key)
                                nl_symbol_entries.append(
                                    (sym, f"Remainder {rm_i + 1}", -labile + rm_mass, mod_name)
                                )
            viewer = getattr(
                getattr(self.main_app, 'annotation_tab_manager', None),
                'mass_spec_viewer', None
            )
            if viewer and hasattr(viewer, 'set_nl_legend_info'):
                viewer.set_nl_legend_info(nl_symbol_entries)
        except Exception as e:
            logger.debug(f"[DEBUG] NL legend update skipped: {e}")

        # Submit task to persistent manager (which has the cache)
        if self.main_app.persistent_fragmentation_manager:
            self.main_app.persistent_fragmentation_manager.submit_task(
                peptide=peptide,
                modifications=modifications,
                max_charge=max_charge,
                ppm_tolerance=ppm_tolerance,
                selected_ions=selected_ions,
                selected_internal_ions=selected_internal_ions,
                user_mz_values=user_mz_values,
                diagnostic_ions=diagnostic_ions,
                custom_ion_series_list=custom_ion_series_list,
                max_neutral_losses=max_neutral_losses,
                calculate_isotopes=calculate_isotopes,
                mod_neutral_losses=mod_neutral_losses,
            )
        else:
            logger.error("[ERROR] Persistent fragmentation manager not available")
    
    # ================================================================
    # VALIDATION AND UTILITY METHODS
    # ================================================================
    
    def validate_fragmentation_inputs(self):
        """Validate all required inputs and update run button appearance"""
        peptide = self.main_app.peptide_input.text().strip()
        max_charge = self.main_app.max_charge_input.value()
        # Check if m/z table has valid data
        mz_data = TableUtils.extract_mz_intensity_from_table(self.main_app.mz_table)
        # Validate using existing utility
        is_valid, _ = InputValidator.validate_fragmentation_inputs(
            peptide, max_charge, mz_data
        )
        
        return is_valid
    
    def _get_modifications_from_table(self) -> list[tuple[float, int]]:
        """Get modifications from interactive peptide widget"""
        if hasattr(self.main_app, 'current_interactive_mods') and self.main_app.current_interactive_mods:
            return self.main_app.current_interactive_mods
        return []
    
    def _create_diagnostic_ion_rows(self):
        """Create diagnostic ion rows for fragmentation results"""
        extra_rows = []
        for _, row in self.main_app.diagnostic_ions.iterrows():
            if row.get('Include', False):  # Only include checked ions
                ion_name = row.get('Name', '')
                mass_val = row.get('Mass', 0)
                color = row.get('Color', 'black')
                
                extra_rows.append({
                    "m/z": mass_val,
                    "intensity": 0,  # Will be updated if matched
                    "Matched": "No Match",
                    "error_ppm": None,
                    "Ion Number": "",
                    "Ion Type": ion_name,
                    "Fragment Sequence": "",
                    "Neutral Loss": "None",
                    "Charge": 1,
                    "Isotope": 0,
                    "Color": color,
                    "Base Type": None,
                    "Ion Series Type": "Diagnostic-Ion"  # New designation for diagnostic ions
                })
        
        return extra_rows
    
    def _load_mock_data(self):
        """Load mock data using utility"""

        matched_data, mock_row_data = MockDataGenerator.generate_mock_spectrum_data()
        
        # Use annotation manager to set data
        self.main_app.annotation_tab_manager.set_mass_spec_data(
            matched_data=matched_data,
            peptide="SAMPLE",
            mod_positions=[],
            row_data=mock_row_data
        )
    
    def _update_spectrum_tracker(self):
        """Update the spectrum tracker with current spectrum and settings - ENHANCED with all ion data"""
        if not hasattr(self.main_app, 'selected_row_data') or not self.main_app.selected_row_data:
            return
        
        # Get current peptide info widget data for fragmented bonds and annotated TIC
        fragmented_bonds = ''
        annotated_tic = ''
        
        if (self.main_app.annotation_tab_manager.peptide_info_widget and 
            hasattr(self.main_app.annotation_tab_manager.peptide_info_widget, 'current_matched_data') and
            self.main_app.annotation_tab_manager.peptide_info_widget.current_matched_data is not None):
            
            peptide_widget = self.main_app.annotation_tab_manager.peptide_info_widget
            peptide = self.main_app.peptide_input.text().strip()
            matched_data = peptide_widget.current_matched_data
            
            # Calculate current values
            fragmented_bonds = peptide_widget.calculate_fragmented_bonds(peptide, matched_data)
            annotated_tic = peptide_widget.calculate_annotated_percentage(matched_data)
            
            # Store in widget for later access
            peptide_widget.current_fragmented_bonds = fragmented_bonds
            peptide_widget.current_annotated_tic = annotated_tic
        
        # ENHANCED: Get comprehensive ion selection data
        all_ion_data = self._get_all_selected_ion_data_for_tracking()
        
        # Gather comprehensive settings data
        settings_data = {
            'user_modifications': getattr(self.main_app, 'current_interactive_mods', []),
            'ppm_tolerance': self.main_app.ppm_tolerance_input.value(),
            'text_annotation_threshold': self.main_app.text_annotation_threshold.value(),
            'max_neutral_losses': self.main_app.max_neutral_losses_input.value(),
            'fragmented_bonds': fragmented_bonds,
            'annotated_tic': annotated_tic,
            # ENHANCED: All ion type data
            'selected_basic_ions': all_ion_data['basic_ions'],
            'selected_neutral_loss_ions': all_ion_data['neutral_loss_ions'],
            'selected_internal_ions': all_ion_data['internal_ions'],
            'selected_custom_ions_data': all_ion_data['custom_ions_data'],
            'selected_diagnostic_ions_data': all_ion_data['diagnostic_ions_data']
        }
        
        # Update spectrum tracker through annotation manager
        self.main_app.annotation_tab_manager.set_current_spectrum(self.main_app.selected_row_data, settings_data)
            
    
    def _get_all_selected_ion_data_for_tracking(self):
        """Get comprehensive ion selection data for spectrum tracking"""
        
        # Basic ion types (y, b, c, etc.)
        selected_basic_ions = []
        for ion_type, checkbox in self.main_app.normal_ion_checkboxes.items():
            if checkbox.isChecked():
                selected_basic_ions.append(ion_type)
        
        # Neutral loss ion types (y-H2O, b-NH3, etc.)
        selected_neutral_loss_ions = []
        for ion_type, checkbox in self.main_app.neutral_ion_checkboxes.items():
            if checkbox.isChecked():
                selected_neutral_loss_ions.append(ion_type)
        
        # Internal ion types (int-b, int-y, etc.)
        selected_internal_ions = []
        for ion_type, checkbox in self.main_app.internal_ion_checkboxes.items():
            if checkbox.isChecked():
                selected_internal_ions.append('int-' + ion_type)
        
        # Custom ion series - FULL DATA CAPTURE
        selected_custom_ions_data = []
        if hasattr(self.main_app, 'selected_custom_ions_data'):
            # Store the complete custom ion data, not just names
            selected_custom_ions_data = [
                {
                    'name': ion.get('Series Name', ''),
                    'base': ion.get('Base Ion', ''),
                    'offset': float(ion.get('Mass Offset', 0)),
                    'color': ion.get('Color', '#CCCCCC'),
                    'restriction': ion.get('Restriction', '')
                }
                for ion in self.main_app.selected_custom_ions_data
            ]
        
        # Diagnostic ions - FULL DATA CAPTURE
        selected_diagnostic_ions_data = []
        if hasattr(self.main_app, 'selected_diagnostic_ions_data'):
            # Store the complete diagnostic ion data, not just names
            selected_diagnostic_ions_data = [
                {
                    'name': ion.get('Name', ''),
                    'mass': float(ion.get('Mass', 0)),
                    'color': ion.get('Color', '#CCCCCC')
                }
                for ion in self.main_app.selected_diagnostic_ions_data
            ]
        
        return {
            'basic_ions': selected_basic_ions,
            'neutral_loss_ions': selected_neutral_loss_ions,
            'internal_ions': selected_internal_ions,
            'custom_ions_data': selected_custom_ions_data,
            'diagnostic_ions_data': selected_diagnostic_ions_data
        }
    
    # ================================================================
    # STATE MANAGEMENT
    # ================================================================
    
    def set_skip_adaptive_update(self, skip: bool):
        """Set the skip adaptive update flag"""
        self._skip_adaptive_update = skip
    
    def set_has_manual_changes(self, has_changes: bool):
        """Set the manual changes flag"""
        self._has_manual_changes = has_changes
    
    def get_skip_adaptive_update(self) -> bool:
        """Get the skip adaptive update flag"""
        return self._skip_adaptive_update
    
    def get_has_manual_changes(self) -> bool:
        """Get the manual changes flag"""
        return self._has_manual_changes