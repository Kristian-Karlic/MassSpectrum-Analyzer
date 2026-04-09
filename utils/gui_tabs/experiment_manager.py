import os
import sys
import time
import tempfile
import shutil
import traceback
import pandas as pd
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QApplication
from utils.utilities import DataProcessingUtils
from utils.utilities import (
    DataLoader, FileProcessingUtils, UIHelpers,
    FileTypeUtils, InputValidator
)
from utils.spectral_extraction.batch_spectral_extraction import ultra_fast_extract_lightweight
from utils.spectral_extraction.spectral_extraction import spectral_extraction
import pickle
from datetime import datetime
from utils.utilities import TableUtils
from utils.spectral_extraction.batch_spectral_extraction import extract_multiple_scans_from_file_lightweight
from utils.psm_normalizers.byonic_normalizer import ByonicNormalizer
import traceback

class ExperimentDataManager:
    def __init__(self, main_app):
        self.main_app = main_app
        
        # Data structures that the manager owns
        self.raw_files = []
        self.search_files = []
        self.df_file_paths = pd.DataFrame()
        self.merged_df = pd.DataFrame()
        self.extracted_spectral_data = {}
        self.rescored_df = None  
        self.rescoring_metadata = None  
        # File paths columns
        self.FILE_PATHS_COLUMNS = [
            "Raw data directory path", "Raw data file name", "Raw file type",
            "Search data directory path", "Search data file name", "Search file type"
        ]
    
    def load_raw_data(self):
        """Load raw data files (.raw, .mzML)"""
        files, _ = QFileDialog.getOpenFileNames(
            self.main_app, "Select Raw Data Files", "", "Raw Files (*.raw *.mzML);;All Files (*.*)"
        )
        
        if files:
            valid_files, invalid_files = FileProcessingUtils.validate_and_load_raw_files(files)
            
            if valid_files:
                self.raw_files.extend(valid_files)
                self._create_and_save_dataframe()
                
                # Update UI if direct scan mode is enabled
                if (hasattr(self.main_app, 'enable_direct_scan_checkbox') and 
                    self.main_app.enable_direct_scan_checkbox.isChecked()):
                    FileProcessingUtils.update_raw_file_dropdown(
                        self.main_app.raw_file_combo, self.raw_files
                    )
                
                UIHelpers.show_success_message(
                    self.main_app, f"Successfully loaded {len(valid_files)} file(s)."
                )

            if invalid_files:
                UIHelpers.show_validation_error(
                    self.main_app, "Invalid Files",
                    "The following files were skipped because they are not .raw or .mzML:\n\n" + 
                    ", ".join(invalid_files)
                )
    
    def load_search_data(self):
        """Load search data files from any supported search engine."""
        from utils.utility_classes.filetypedetector import FileTypeDetector
        files, _ = QFileDialog.getOpenFileNames(
            self.main_app,
            "Select Search Data Files",
            "",
            FileTypeDetector.search_file_dialog_filter()
        )
        if not files:
            return
        
        # Use utility function instead of manual processing
        valid_files, invalid_files = FileProcessingUtils.process_search_files(files)
        
        if valid_files:
            for file_type, file_path in valid_files:
                self.search_files.append(file_path)
            self._create_and_save_dataframe()
            
            # Use utility for message creation
            message = FileProcessingUtils.create_file_type_summary(valid_files)
            UIHelpers.show_success_message(self.main_app, message)
        
        if invalid_files:
            UIHelpers.show_validation_error(
                self.main_app, 
                "Invalid Files",
                "The following files were skipped because they are not recognized:\n\n"
                + ", ".join(invalid_files)
            )
    
    def add_msfragger_search_folder(self):
        """Add entire MSFragger search folder"""
        folder = QFileDialog.getExistingDirectory(
            self.main_app, "Select MSFragger Search Folder", ""
        )
        if not folder:
            return
        
        # Use utility function instead of manual processing
        matched_psm_files, invalid_files = FileProcessingUtils.process_msfragger_folder(folder)
        
        if matched_psm_files:
            self.search_files.extend(matched_psm_files)
            self._create_and_save_dataframe()
            UIHelpers.show_success_message(
                self.main_app, 
                f"Successfully loaded {len(matched_psm_files)} MSFragger file(s)."
            )
        
        if invalid_files:
            UIHelpers.show_validation_error(
                self.main_app,
                "Invalid Files",
                f"The following files were skipped because they are not valid MSFragger files:\n\n"
                f"{', '.join(invalid_files)}"
            )
    
    def _create_and_save_dataframe(self):
        """Create and save the file paths dataframe"""
        self.df_file_paths = DataLoader.create_file_paths_dataframe(
            self.raw_files, self.search_files, self.FILE_PATHS_COLUMNS
        )
        print("File paths CSV updated:\n", self.df_file_paths)

        # Refresh the Manage Files tab if it exists
        if hasattr(self.main_app, 'manage_files_tab_manager'):
            self.main_app.manage_files_tab_manager.refresh_file_list()
    
    def combine_and_process_psm_files(self):
        """Combine and process PSM files from any supported search engine."""
        from utils.psm_normalizers import NormalizerFactory
        from utils.mod_database import ModificationMassDatabase, UnknownModificationsDialog
        from utils.utility_classes.filetypedetector import FileTypeDetector
        from PyQt6.QtWidgets import QDialog

        if not self.search_files:
            print("No search files loaded.")
            return

        # ---------------------------------------------------------------
        # Step 1: Detect file types and group by engine
        # ---------------------------------------------------------------
        file_groups: dict[str, list[str]] = {}
        unrecognised_paths: list[str] = []
        for path in self.search_files:
            file_type = FileTypeDetector.detect_search_file_type(path)
            if file_type:
                file_groups.setdefault(file_type, []).append(path)
            else:
                unrecognised_paths.append(path)

        # If any files were not auto-detected, ask the user to pick a format
        if unrecognised_paths:
            from utils.psm_normalizers.psm_utils_format_dialog import PSMUtilsFormatDialog
            from PyQt6.QtWidgets import QDialog as _QDialog
            fnames = [os.path.basename(p) for p in unrecognised_paths]
            fmt_dialog = PSMUtilsFormatDialog(fnames, parent=self.main_app)
            if fmt_dialog.exec() == _QDialog.DialogCode.Accepted:
                selections = fmt_dialog.get_selections()  # {basename: format_key | None}
                for path in unrecognised_paths:
                    chosen = selections.get(os.path.basename(path))
                    if chosen:
                        file_groups.setdefault(chosen, []).append(path)
                        print(f"[INFO] User assigned '{chosen}' to {os.path.basename(path)}")
                    else:
                        print(f"[WARNING] Skipping {os.path.basename(path)} (no format selected)")
            else:
                # User cancelled the dialog — skip all unrecognised files
                print(f"[WARNING] Format dialog cancelled; "
                      f"{len(unrecognised_paths)} file(s) skipped.")

        if not file_groups:
            UIHelpers.show_validation_error(
                self.main_app, "Error",
                "No valid search files found. Supported formats:\n"
                "- MSFragger (psm.tsv / pre-validation TSV)\n"
                "- MaxQuant (msms.txt)\n"
                "- MetaMorpheus (AllPSMs.psmtsv / AllPeptides.psmtsv)\n"
                "- Byonic (CSV)\n"
                "- PEAKS (CSV)\n"
                "- Sage (TSV)\n"
                "- Percolator (.pin / .pout)\n"
                "- mzIdentML (.mzid)\n"
                "- X!Tandem (XML)\n"
                "- OpenMS idXML\n"
                "- pepXML (.pepxml / .pep.xml)"
            )
            return

        engines_used = ", ".join(file_groups.keys())
        total_files = sum(len(p) for p in file_groups.values())
        print(f"[DEBUG] Detected engines: {engines_used}  ({total_files} files)")

        # ---------------------------------------------------------------
        # Step 2: Initialise modification databases
        # ---------------------------------------------------------------
        from utils.resource_path import get_data_file_path
        maxquant_db = ModificationMassDatabase(get_data_file_path("maxquant_mods.json"))
        metamorpheus_db = ModificationMassDatabase(get_data_file_path("metamorpheus_mods.json"))

        # Store references for the Databases menu
        self.maxquant_mod_db = maxquant_db
        self.metamorpheus_mod_db = metamorpheus_db

        # ---------------------------------------------------------------
        # Step 3: Pre-scan for unknown modifications (MaxQuant / MetaMorpheus / psm_utils)
        # ---------------------------------------------------------------
        for engine, paths in file_groups.items():
            if engine not in ("MaxQuant", "MetaMorpheus", "Byonic") and \
               not NormalizerFactory.is_psm_utils_format(engine):
                continue
            if engine == "MaxQuant":
                db = maxquant_db
            elif engine == "MetaMorpheus":
                db = metamorpheus_db
            else:
                db = maxquant_db  # Use same database for modification lookups
            normalizer = NormalizerFactory.create(engine, mod_database=db,
                                                  source_file_path=paths[0] if paths else None)

            all_unknown: set[str] = set()
            for path in paths:
                try:
                    if NormalizerFactory.is_psm_utils_format(engine):
                        # PSMUtils normalizer reads the file itself
                        normalizer_path = NormalizerFactory.create(
                            engine, source_file_path=path
                        )
                        unknown = normalizer_path.get_unknown_modifications()
                    else:
                        df_scan = pd.read_csv(path, sep="\t", low_memory=False)
                        unknown = normalizer.get_unknown_modifications(df_scan)
                    all_unknown.update(unknown)
                except Exception as e:
                    print(f"[WARNING] Could not pre-scan {path}: {e}")

            if all_unknown:
                dialog = UnknownModificationsDialog(
                    all_unknown, engine, parent=self.main_app
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    masses = dialog.get_masses()
                    db.update_batch(masses)
                    # Also register resolved masses in central mod database
                    central_db = getattr(self.main_app, 'central_mod_db', None)
                    if central_db:
                        for name, mass in masses.items():
                            central_db.ensure_mass_exists(mass, default_name=name)
                else:
                    UIHelpers.show_validation_error(
                        self.main_app, "Cancelled",
                        f"Data preparation cancelled.\n"
                        f"Modification masses are required for {engine} data."
                    )
                    return

        # ---------------------------------------------------------------
        # Step 4: Progress dialog
        # ---------------------------------------------------------------
        progress = UIHelpers.create_progress_dialog(
            self.main_app, "Please wait", "Combining data...",
            total_files + 1  # +1 for extraction
        )

        try:
            # -----------------------------------------------------------
            # Step 5: Normalise each file
            # -----------------------------------------------------------
            all_normalised: list[pd.DataFrame] = []
            file_count = 0

            for engine, paths in file_groups.items():
                db = (maxquant_db if engine == "MaxQuant"
                      else metamorpheus_db if engine == "MetaMorpheus"
                      else None)

                for path in paths:
                    if progress.wasCanceled():
                        print("User canceled operation.")
                        return

                    progress.setValue(file_count)
                    progress.setLabelText(
                        f"Processing {engine}: {os.path.basename(path)}"
                    )
                    QApplication.processEvents()

                    try:
                        # Create normalizer with source_file_path for pre-validation format
                        normalizer = NormalizerFactory.create(
                            engine, mod_database=db, source_file_path=path
                        )
                        # Use custom Byonic reader for Byonic files,
                        # None for psm_utils formats (they read internally),
                        # standard pandas for all others
                        if engine == "Byonic":
                            df_raw = ByonicNormalizer.read_byonic_csv(path)
                        elif NormalizerFactory.is_psm_utils_format(engine):
                            df_raw = None
                        else:
                            df_raw = pd.read_csv(path, sep="\t", low_memory=False)
                        df_norm = normalizer.normalize(df_raw)
                        all_normalised.append(df_norm)
                        print(f"[DEBUG] Normalised {os.path.basename(path)}: "
                              f"{len(df_norm)} rows ({engine})")
                    except Exception as e:
                        print(f"[ERROR] Could not process {path}: {e}")
                        traceback.print_exc()

                    file_count += 1

            if not all_normalised:
                print("No valid PSM data to combine.")
                progress.close()
                return

            combined_df = pd.concat(all_normalised, ignore_index=True)
            print(f"[DEBUG] Combined dataframe has {len(combined_df)} rows "
                  "before duplicate removal")

            # -----------------------------------------------------------
            # Step 5b: Register modification masses in central database
            # -----------------------------------------------------------
            central_db = getattr(self.main_app, 'central_mod_db', None)
            if central_db:
                self._register_modifications_in_central_db(combined_df, central_db)

            # -----------------------------------------------------------
            # Step 6: Remove duplicates
            # -----------------------------------------------------------
            initial_row_count = len(combined_df)
            dup_cols = ["Spectrum file", "index", "Peptide"]
            if all(c in combined_df.columns for c in dup_cols):
                combined_df = combined_df.drop_duplicates(
                    subset=dup_cols, keep="first"
                )
                duplicates_removed = initial_row_count - len(combined_df)
                print(f"[DEBUG] Removed {duplicates_removed} duplicate PSMs")
                if duplicates_removed > 0:
                    progress.setLabelText(
                        f"Removed {duplicates_removed} duplicate PSMs..."
                    )
                    QApplication.processEvents()
            else:
                print("[WARNING] Cannot remove duplicates – missing columns")

            # -----------------------------------------------------------
            # Step 7: Merge with raw file paths
            # -----------------------------------------------------------
            df_file_paths = self.df_file_paths.copy()
            df_file_paths["spectrum_file_path"] = (
                df_file_paths["Raw data directory path"]
                + os.sep
                + df_file_paths["Raw data file name"]
            )
            df_file_paths["raw_file_base"] = df_file_paths[
                "Raw data file name"
            ].apply(FileTypeUtils.strip_file_extension)

            merged_df = pd.merge(
                combined_df, df_file_paths,
                how="left",
                left_on="Spectrum file",
                right_on="raw_file_base",
                indicator=True,
            )
            merged_df.drop(
                columns=["_merge", "raw_file_base"],
                inplace=True, errors="ignore",
            )
            merged_df["index"] = (
                merged_df["index"].astype(str).str.lstrip("0")
            )

            self.merged_df = merged_df

            # -----------------------------------------------------------
            # Step 8: Extract spectral data
            # -----------------------------------------------------------
            progress.setValue(total_files)
            progress.setLabelText(
                "Extracting spectral data from raw files..."
            )
            QApplication.processEvents()

            self._extract_all_spectral_data(progress)

            # -----------------------------------------------------------
            # Step 9: Update UI
            # -----------------------------------------------------------
            self.main_app.annotation_tab_manager.set_data(self.merged_df)
            self.main_app.frag_psm_summary_widget.setData(self.merged_df)

            print("Combine & Process PSM done.")

            progress.close()

            final_message = (
                f"Data preparation completed successfully!\n\n"
                f"Engines: {engines_used}\n"
                f"Combined {len(self.merged_df)} PSMs from {total_files} files.\n"
            )
            if initial_row_count != len(self.merged_df):
                final_message += (
                    f"Removed {initial_row_count - len(self.merged_df)} "
                    f"duplicate PSMs.\n"
                )
            final_message += (
                f"Extracted spectral data for analysis.\n\n"
                f"Would you like to save this as an experiment file "
                f"for quick reloading?"
            )

            reply = QMessageBox.question(
                self.main_app,
                "Save Experiment?",
                final_message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.save_experiment()

        except Exception as e:
            print(f"Error in combine_and_process_psm_files: {e}")
            traceback.print_exc()
            if progress:
                progress.close()
            UIHelpers.show_validation_error(
                self.main_app, "Error",
                f"An error occurred during data preparation:\n{str(e)}"
            )

    def _extract_all_spectral_data(self, progress=None):
        """Optimized extraction method that skips unnecessary steps"""
        print("Starting optimized batch spectral data extraction...")
        
        # Prepare data for batch extraction
        required_columns = ['spectrum_file_path', 'index']
        if not all(col in self.merged_df.columns for col in required_columns):
            print(f"Missing required columns for extraction: {required_columns}")
            if progress:
                progress.setValue(progress.maximum())
            return
        
        # Filter to only rows with valid file paths
        valid_rows = self.merged_df.dropna(subset=['spectrum_file_path', 'index'])
        if valid_rows.empty:
            print("No valid rows found for extraction")
            if progress:
                progress.setValue(progress.maximum())
            return
        
        print(f"Extracting spectral data for {len(valid_rows)} PSMs...")
        
        # Create temporary input file for batch extraction
        temp_dir = tempfile.mkdtemp()
        temp_input = os.path.join(temp_dir, "batch_input.tsv")
        
        try:
            # Update progress to 60%
            if progress:
                progress.setValue(60)
                progress.setLabelText("Preparing batch extraction input...")
                QApplication.processEvents()
            
            # Prepare input file for batch extraction
            batch_input = valid_rows[['index', 'spectrum_file_path']].copy()
            batch_input.columns = ['index', 'file_path']  # Match expected column names
            batch_input.to_csv(temp_input, sep='\t', index=False)
            
            # Update progress to 70%
            if progress:
                progress.setValue(70)
                progress.setLabelText("Running optimized batch extraction...")
                QApplication.processEvents()
            
            # Run lightweight extraction (no structured array)
            results_df = ultra_fast_extract_lightweight(
                input_file=temp_input,
                max_workers=6
            )
            
            # Update progress to 85%
            if progress:
                progress.setValue(85)
                progress.setLabelText("Processing extracted data...")
                QApplication.processEvents()
            
            if results_df is not None and not results_df.empty:
                # Use optimized merge method
                self._merge_extracted_data(results_df)
            
            # Update progress to 95%
            if progress:
                progress.setValue(95)
                progress.setLabelText("Finalizing extraction...")
                QApplication.processEvents()
                
        except Exception as e:
            print(f"Error during optimized batch extraction: {e}")
            traceback.print_exc()
            
            # Still complete the progress bar even on error
            if progress:
                progress.setValue(progress.maximum())
                progress.setLabelText("Extraction completed with errors")
                QApplication.processEvents()
                
        finally:
            # Clean up temporary files
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                print(f"Warning: Could not clean up temp directory: {cleanup_error}")
            
            # Always complete the progress bar
            if progress:
                progress.setValue(progress.maximum())
                progress.setLabelText("Extraction complete")
                QApplication.processEvents()
    
    def _merge_extracted_data(self, extracted_df):
        """Optimized version of merge_extracted_data with header information"""
        print("Starting optimized data merging with header information...")
        start_time = time.time()
        
        # Pre-allocate dictionary for better performance
        grouped_data = {}
        
        # Filter out failed extractions early
        successful_rows = extracted_df[extracted_df['status'] == 'success']
        
        if successful_rows.empty:
            print("No successful extractions to merge")
            return
        
        # Vectorized processing using itertuples for speed
        for row in successful_rows.itertuples(index=False):
            file_path = row.file_path
            scan_number = str(row.scan_number)
            mz_values = row.mz
            intensity_values = row.intensity
            header_info = getattr(row, 'header', None)  # Get header info
            
            # Create cache key
            cache_key = f"{file_path}_{scan_number}"
            
            # Store the grouped data including header
            grouped_data[cache_key] = {
                'mz_values': mz_values,
                'intensity_values': intensity_values,
                'header': header_info
            }
        
        # Store the grouped data for quick access
        self.extracted_spectral_data = grouped_data
        
        # Add header information to merged_df
        if not self.merged_df.empty:
            self._add_header_column_to_merged_df(successful_rows)
        
        elapsed_time = time.time() - start_time
        print(f"Optimized merging with headers completed for {len(grouped_data)} unique scans in {elapsed_time:.2f}s")
    
    def _add_header_column_to_merged_df(self, extracted_df):
        """Add header information as a new column to merged_df"""
        try:
            # Create a mapping from scan info to header
            header_mapping = {}
            
            for row in extracted_df.itertuples(index=False):
                file_path = row.file_path
                scan_number = str(row.scan_number)
                header_info = getattr(row, 'header', None)
                
                # Create key to match with merged_df
                cache_key = f"{file_path}_{scan_number}"
                header_mapping[cache_key] = header_info
            
            # Add header column to merged_df
            def get_header_for_row(row):
                spectrum_file_path = row.get('spectrum_file_path', '')
                index_str = str(row.get('index', ''))
                cache_key = f"{spectrum_file_path}_{index_str}"
                return header_mapping.get(cache_key, None)
            
            # Apply the mapping to create the header column
            self.merged_df['Header'] = self.merged_df.apply(get_header_for_row, axis=1)
            
            print(f"Added header information to {len(self.merged_df)} rows in merged_df")
            
        except Exception as e:
            print(f"Error adding header column: {e}")
    
    def save_experiment(self):
        """Save experiment with proper progress updates - UPDATED for rescoring"""
        if self.merged_df.empty:
            UIHelpers.show_validation_error(
                self.main_app, "No Data", 
                "No prepared data found. Please prepare data first before saving an experiment."
            )
            return
        
        # Determine if this is an update to existing file
        file_path = None
        has_rescoring = self.rescored_df is not None
        
        # Check if we should suggest updating existing file
        if has_rescoring and hasattr(self, '_last_experiment_path') and self._last_experiment_path:
            update_msg = f"""Update existing experiment file?

    Current file: {os.path.basename(self._last_experiment_path)}

    This will update the experiment file with the new rescoring results.
    Choose 'No' to save as a new file instead."""
            
            reply = QMessageBox.question(
                self.main_app,
                "Update Experiment File",
                update_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                file_path = self._last_experiment_path
        
        # Prompt for file path if not updating existing
        if not file_path:
            default_name = "experiment_rescored.kcx" if has_rescoring else "experiment.kcx"
            
            file_path, _ = QFileDialog.getSaveFileName(
                self.main_app, "Save Experiment", default_name,
                "Labile Annotation Experiments (*.kcx);;All Files (*.*)"
            )
            
            if not file_path:
                return
        
        # Store path for future updates
        self._last_experiment_path = file_path
        
        # Create progress dialog with proper steps
        progress = UIHelpers.create_progress_dialog(
            self.main_app, "Saving Experiment", "Preparing data...", 100, False
        )
        progress.show()
        QApplication.processEvents()
            
        try:
            # Step 1: Gather experiment metadata (20%)
            progress.setValue(20)
            progress.setLabelText("Gathering experiment metadata...")
            QApplication.processEvents()
            
            experiment_data = self._create_experiment_data()
            
            # Step 2: Prepare file paths (40%)
            progress.setValue(40)
            progress.setLabelText("Preparing file information...")
            QApplication.processEvents()
            
            # Step 3: Prepare dataframes (60%)
            progress.setValue(60)
            progress.setLabelText("Preparing PSM data...")
            QApplication.processEvents()
            
            # Step 4: Save to file (80%)
            progress.setValue(80)
            if has_rescoring:
                progress.setLabelText("Writing experiment with rescoring data...")
            else:
                progress.setLabelText("Writing experiment file...")
            QApplication.processEvents()
            
            # Save the experiment
            if self._save_experiment_data(experiment_data, file_path):
                # Step 5: Finalize (100%)
                progress.setValue(100)
                progress.setLabelText("Finalizing...")
                QApplication.processEvents()
                
                progress.close()
                
                metadata = experiment_data['metadata']
                
                success_msg = f"""Experiment saved successfully!

    Location: {file_path}
    PSMs: {metadata['total_psms']}
    Unique Peptides: {metadata['unique_peptides']}
    Raw Files: {metadata['raw_files_count']}
    Search Files: {metadata['search_files_count']}"""
                

                if has_rescoring:
                    success_msg += f"\n\n✓ Rescoring Results Included"
                    success_msg += f"\n  Rescored PSMs: {len(self.rescored_df)}"
                
                UIHelpers.show_success_message(self.main_app, success_msg)
            else:
                progress.close()
                UIHelpers.show_validation_error(self.main_app, "Save Error", "Failed to save experiment")
                
        except Exception as e:
            progress.close()
            UIHelpers.show_validation_error(
                self.main_app, "Save Error", f"Failed to save experiment:\n{str(e)}"
            )

    def _save_experiment_data(self, experiment_data, file_path):
        """Save experiment data to file using pickle for efficiency"""
        try:
            # Use pickle for efficient serialization of complex data structures
            with open(file_path, 'wb') as f:
                pickle.dump(experiment_data, f, protocol=pickle.HIGHEST_PROTOCOL)
            
            print(f"[DEBUG] Experiment saved successfully to {file_path}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to save experiment: {e}")
            traceback.print_exc()
            return False

    def load_experiment(self):
        """Load experiment with proper progress updates - UPDATED for rescoring"""
        file_path, _ = QFileDialog.getOpenFileName(  # CHANGED: Removed 's' from getOpenFileNames
            self.main_app, "Open Previous Experiment", "",
            "Labile Annotation Experiments (*.kcx);;All Files (*.*)"
        )
        
        if not file_path:  # Now it's a string, not a list
            return
        
        # Create progress dialog with more steps
        progress = UIHelpers.create_progress_dialog(
            self.main_app, "Loading Experiment", "Initializing...", 100, False
        )
        progress.show()
        QApplication.processEvents()
        
        try:
            # Step 1: Load and validate file (10%)
            progress.setValue(10)
            progress.setLabelText("Reading experiment file...")
            QApplication.processEvents()
            
            success, experiment_data, error_msg = self._load_experiment_data(file_path)
            
            if not success:
                progress.close()
                UIHelpers.show_validation_error(self.main_app, "Invalid File", error_msg)
                return
            
            # Step 2: Validate data structure (20%)
            progress.setValue(20)
            progress.setLabelText("Validating experiment data...")
            QApplication.processEvents()
            
            # Step 3: Restore file paths (30%)
            progress.setValue(30)
            progress.setLabelText("Restoring file paths...")
            QApplication.processEvents()
            
            # File lists
            self.raw_files = experiment_data['file_paths']['raw_files']
            self.search_files = experiment_data['file_paths']['search_files']
            self.df_file_paths = pd.DataFrame(experiment_data['file_paths']['df_file_paths'])
            
            # Step 4: Restore extracted spectral data (50%)
            progress.setValue(50)
            progress.setLabelText("Restoring spectral data cache...")
            QApplication.processEvents()
            
            self.extracted_spectral_data = experiment_data.get('extracted_spectral_data', {})
            
            # Step 5: Restore main dataframe (70%)
            progress.setValue(70)
            progress.setLabelText("Restoring PSM data...")
            QApplication.processEvents()
            
            self.merged_df = pd.DataFrame(experiment_data['merged_df'])
            
            # Step 6: Restore settings (80%)
            progress.setValue(80)
            progress.setLabelText("Restoring settings...")
            QApplication.processEvents()
            
            self._restore_experiment_settings(experiment_data)
            
            # Step 7: Update UI widgets (90%)
            progress.setValue(90)
            progress.setLabelText("Updating interface...")
            QApplication.processEvents()
            
            # Update both PSM widgets
            self.main_app.annotation_tab_manager.set_data(self.merged_df)  # Annotation tab
            self.main_app.frag_psm_summary_widget.setData(self.merged_df)  # Fragmentation tab
            
            if (hasattr(self.main_app, 'enable_direct_scan_checkbox') and 
                self.main_app.enable_direct_scan_checkbox.isChecked()):
                FileProcessingUtils.update_raw_file_dropdown(
                    self.main_app.raw_file_combo, self.raw_files
                )
            
            
            # Step 7.5: Load rescoring data if available (92%)
            progress.setValue(92)
            progress.setLabelText("Loading rescoring data...")
            QApplication.processEvents()
            

            if 'rescored_df' in experiment_data and experiment_data['rescored_df']:
                self.rescored_df = pd.DataFrame(experiment_data['rescored_df'])
                self.rescoring_metadata = experiment_data.get('rescoring_metadata', None)
                
                # Load into rescoring tab viewer
                if (hasattr(self.main_app, 'rescoring_tab_manager') and 
                    self.main_app.rescoring_tab_manager.results_viewer):
                    self.main_app.rescoring_tab_manager.load_existing_rescoring(
                        self.rescored_df
                    )
                
                print(f"[DEBUG] Loaded rescoring data: {len(self.rescored_df)} PSMs")
            else:
                self.rescored_df = None
                self.rescoring_metadata = None
                print("[DEBUG] No rescoring data in experiment file")
            
            # Step 8: Update UI widgets (95%)
            progress.setValue(95)
            progress.setLabelText("Updating interface...")
            QApplication.processEvents()
            # Step 8: Finalize (100%)
            progress.setValue(100)
            progress.setLabelText("Finalizing...")
            QApplication.processEvents()
            
            progress.close()
            
            # Show success message
            metadata = experiment_data['metadata']
            missing_files = self._check_file_existence(experiment_data['file_paths'])
            
            success_msg = f"""Experiment loaded successfully!

    Created: {metadata['created_date'][:19]}
    PSMs: {metadata['total_psms']}
    Unique Peptides: {metadata['unique_peptides']}
    Description: {metadata['description']}"""
            
            # Add rescoring info to success message
            if metadata.get('has_rescoring', False):
                rescoring_info = self.get_rescoring_info()
                if rescoring_info:
                    success_msg += f"\n\n✓ Rescoring Results Available"
                    success_msg += f"\n  Rescored Date: {rescoring_info['rescored_date'][:19]}"
                    success_msg += f"\n  PSMs Rescored: {rescoring_info['psm_count']}"
            
            if missing_files:
                success_msg += f"\n\nWarning: Some files missing:\n" + "\n".join(missing_files[:5])
                if len(missing_files) > 5:
                    success_msg += f"\n... and {len(missing_files) - 5} more files"
            
            UIHelpers.show_success_message(self.main_app, success_msg)
            
        except Exception as e:
            progress.close()
            UIHelpers.show_validation_error(
                self.main_app, "Load Error", f"Failed to load experiment:\n{str(e)}"
            )
    
    def _load_experiment_data(self, file_path):
        """Load experiment data from file"""
        try:
            if not os.path.exists(file_path):
                return False, None, f"File does not exist: {file_path}"
            
            # Use pickle to load the data
            with open(file_path, 'rb') as f:
                experiment_data = pickle.load(f)
            
            # Validate required keys
            required_keys = ['metadata', 'file_paths', 'merged_df']
            missing_keys = [key for key in required_keys if key not in experiment_data]
            
            if missing_keys:
                return False, None, f"Invalid experiment file. Missing keys: {missing_keys}"
            
            print(f"[DEBUG] Experiment loaded successfully from {file_path}")
            return True, experiment_data, None
            
        except Exception as e:
            print(f"[ERROR] Failed to load experiment: {e}")
            traceback.print_exc()
            return False, None, f"Failed to load experiment: {str(e)}"

    def _check_file_existence(self, file_paths):
        """Check which files from the experiment still exist"""
        missing_files = []
        
        # Check raw files
        for raw_file in file_paths.get('raw_files', []):
            if not os.path.exists(raw_file):
                missing_files.append(f"Raw: {os.path.basename(raw_file)}")
        
        # Check search files
        for search_file in file_paths.get('search_files', []):
            if not os.path.exists(search_file):
                missing_files.append(f"Search: {os.path.basename(search_file)}")
        
        return missing_files
    
    def _create_experiment_data(self):
        """Create experiment data dictionary for saving"""
        # Count unique peptides
        unique_peptides = len(self.merged_df['Peptide'].unique()) if not self.merged_df.empty else 0
        
        experiment_data = {
            'metadata': {
                'created_date': datetime.now().isoformat(),
                'total_psms': len(self.merged_df),
                'unique_peptides': unique_peptides,
                'raw_files_count': len(self.raw_files),
                'search_files_count': len(self.search_files),
                'description': f"Experiment with {len(self.merged_df)} PSMs from {len(self.search_files)} search files",
                'has_rescoring': self.rescored_df is not None  
            },
            'file_paths': {
                'raw_files': self.raw_files,
                'search_files': self.search_files,
                'df_file_paths': self.df_file_paths.to_dict('records')
            },
            'merged_df': self.merged_df.to_dict('records'),
            'extracted_spectral_data': self.extracted_spectral_data,
            'settings': self._get_current_settings()
        }
        
        # Add rescoring data if available
        if self.rescored_df is not None:
            experiment_data['rescored_df'] = self.rescored_df.to_dict('records')
            experiment_data['rescoring_metadata'] = self.rescoring_metadata
            print(f"[DEBUG] Including rescoring data: {len(self.rescored_df)} PSMs")
        
        return experiment_data
    
    def save_rescoring_to_experiment(self, rescored_df, rescoring_settings):
        """
        Save rescoring results to the current experiment file.
        
        Args:
            rescored_df: DataFrame with rescoring results
            rescoring_settings: Dictionary with rescoring configuration
        """
        # Store rescoring data in memory
        self.rescored_df = rescored_df
        self.rescoring_metadata = {
            'rescored_date': datetime.now().isoformat(),
            'settings': rescoring_settings,
            'psm_count': len(rescored_df),
            'score_columns': ['Hyperscore', 'Rescore']
        }
        
        print(f"[DEBUG] Rescoring data stored: {len(rescored_df)} PSMs")
        
    def has_existing_rescoring(self):
        """Check if current experiment has rescoring data"""
        return self.rescored_df is not None

    def get_rescoring_info(self):
        """Get information about existing rescoring data"""
        if not self.rescored_df is not None:
            return None
        
        return {
            'psm_count': len(self.rescored_df),
            'rescored_date': self.rescoring_metadata.get('rescored_date', 'Unknown'),
            'settings': self.rescoring_metadata.get('settings', {})
        }

    
    def _get_current_settings(self):
        """Get current GUI settings for saving"""
        settings = {
            'ppm_tolerance': self.main_app.ppm_tolerance_input.value(),
            'text_annotation_threshold': self.main_app.text_annotation_threshold.value()
        }
        
        return settings
    
    def _restore_experiment_settings(self, experiment_data):
        """Restore GUI settings from experiment data"""
        settings = experiment_data.get('settings', {})
        
        self.main_app.ppm_tolerance_input.setValue(settings.get('ppm_tolerance', 10))
        self.main_app.text_annotation_threshold.setValue(settings.get('text_annotation_threshold', 0))
    
    def update_spectrum_quality_in_dataframe(self, spectrum_data, quality):
        """Update the quality assessment in the main dataframe"""
        if self.merged_df.empty:
            return
            
        # Find matching rows and update quality
        try:
            peptide = spectrum_data.get('Peptide', '')
            scan = spectrum_data.get('index', '')
            charge = spectrum_data.get('Charge', '')
            
            # Create quality column if it doesn't exist
            if 'User_Quality_Assessment' not in self.merged_df.columns:
                self.merged_df['User_Quality_Assessment'] = ''
                
            # Find matching rows
            mask = (
                (self.merged_df['Peptide'] == peptide) &
                (self.merged_df['index'].astype(str) == str(scan)) &
                (self.merged_df['Charge'] == charge)
            )
            
            # Update quality assessment
            self.merged_df.loc[mask, 'User_Quality_Assessment'] = quality
            
            print(f"[DEBUG] Updated {mask.sum()} rows with quality: {quality}")
            
        except Exception as e:
            print(f"[ERROR] Failed to update quality in dataframe: {e}")
    
    
    def _register_modifications_in_central_db(self, df, central_db):
        """Ensure every unique modification mass from Parsed Modifications
        exists in the central modification database."""
        import ast as _ast

        seen_masses = set()
        for raw_mods in df['Parsed Modifications'].dropna():
            if isinstance(raw_mods, str):
                try:
                    mods = _ast.literal_eval(raw_mods)
                except Exception:
                    continue
            else:
                mods = raw_mods
            if not mods:
                continue
            for mass, _pos in mods:
                rounded = round(mass, 4)
                if rounded not in seen_masses:
                    seen_masses.add(rounded)
                    central_db.ensure_mass_exists(mass)

        if seen_masses:
            # Refresh the backward-compat view on the main app
            if hasattr(self.main_app, 'available_mods'):
                self.main_app.available_mods = central_db.as_dataframe()
            print(f"[CentralModDB] Registered {len(seen_masses)} unique modification masses")

    
    def extract_scan_data(self, selected_file: str, scan_number: str) -> tuple[list, list] | None:
        """
        Extract m/z and intensity data for a single scan from a raw file.
        
        Args:
            selected_file: Name of the raw file (from dropdown)
            scan_number: Scan number as string
            
        Returns:
            Tuple of (mz_list, intensity_list) or None if extraction fails
        """
        if not selected_file or not scan_number:
            print("[ERROR] Missing file or scan number")
            return None
        
        try:
            scan_num = int(scan_number)
        except ValueError:
            print(f"[ERROR] Invalid scan number: {scan_number}")
            return None
        
        # Find the full path for the selected file
        file_path = None
        for raw_file_path in self.raw_files:
            if selected_file in raw_file_path or raw_file_path.endswith(selected_file):
                file_path = raw_file_path
                break
        
        if not file_path:
            print(f"[ERROR] Could not find raw file: {selected_file}")
            return None
        
        print(f"[DEBUG] Extracting scan {scan_num} from {file_path}")
        
        try:

            # Extract the single scan
            results = extract_multiple_scans_from_file_lightweight(file_path, [scan_num])
            
            if not results:
                print(f"[ERROR] No results returned for scan {scan_num}")
                return None
            
            result = results[0]  # Get the first (and only) result
            
            if result['status'] != 'success':
                print(f"[ERROR] Scan extraction failed: {result['status']}")
                UIHelpers.show_validation_error(
                    self.main_app, 
                    "Extraction Error", 
                    f"Failed to extract scan {scan_num}:\n{result['status']}"
                )
                return None
            
            mz_list = result.get('mz', [])
            intensity_list = result.get('intensity', [])
            
            if not mz_list or not intensity_list:
                print(f"[ERROR] Empty data returned for scan {scan_num}")
                return None
            
            print(f"[DEBUG] Successfully extracted {len(mz_list)} peaks from scan {scan_num}")
            UIHelpers.show_success_message(
                self.main_app, 
                f"Extracted {len(mz_list)} peaks from scan {scan_num}"
            )
            
            return mz_list, intensity_list
            
        except Exception as e:
            print(f"[ERROR] Exception during scan extraction: {e}")

            traceback.print_exc()
            
            UIHelpers.show_validation_error(
                self.main_app, 
                "Extraction Error", 
                f"Failed to extract scan {scan_num}:\n{str(e)}"
            )
            return None