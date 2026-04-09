import time
import traceback
from PyQt6.QtCore import QThread, pyqtSignal
from utils.utilities import DataGatherer
from utils.rescoring.threaded_fragmentation_functions import (
    calculate_xtandem, process_fragments, count_ion_types_parallel,
    calculate_labeled_intensity_percentage, calculate_migration_ratios_parallel,
    calculate_scores_parallel
)
from utils.utilities import DataProcessingUtils


class RescoringWorker(QThread):
    """Worker thread for rescoring process"""

    progress_update = pyqtSignal(int, str)
    rescoring_complete = pyqtSignal(object)
    rescoring_error = pyqtSignal(str)

    def __init__(self, merged_df, options, custom_ion_series, diagnostic_ions,
                 selected_ions, selected_internal_ions, grouping_data,
                 decoy_settings, max_neutral_losses, extracted_spectral_data,
                 scoring_methods=None, central_mod_db=None, enable_labile=False,
                 enable_remainder=False, enable_mod_nl=False):
        super().__init__()
        self.merged_df = merged_df
        self.options = options
        self.custom_ion_series = custom_ion_series
        self.diagnostic_ions = diagnostic_ions
        self.selected_ions = selected_ions
        self.selected_internal_ions = selected_internal_ions
        self.grouping_data = grouping_data
        self.decoy_settings = decoy_settings
        self.max_neutral_losses = max_neutral_losses
        self.extracted_spectral_data = extracted_spectral_data
        self.scoring_methods = scoring_methods
        self.central_mod_db = central_mod_db
        self.enable_labile = enable_labile
        self.enable_remainder = enable_remainder
        self.enable_mod_nl = enable_mod_nl

    def _log_step(self, step_name, start_time):
        """Log completion of a step with elapsed time"""
        elapsed = time.time() - start_time
        print(f"[TIMING] {step_name}: {elapsed:.2f}s")
        return elapsed

    def _build_nl_lookup(self):
        """Build a mass → NL config dict from the central modification database.

        Returns a dict keyed by rounded mass (4 decimals).  Values are
        plain dicts safe for pickle serialisation to worker processes.
        Only entries that have at least one active neutral loss are included.
        """
        lookup = {}
        if not self.central_mod_db:
            return lookup
        effective_labile = self.enable_labile or self.enable_remainder
        for _name, entry in self.central_mod_db.get_all_entries().items():
            if self.central_mod_db.has_active_neutral_loss(entry, effective_labile,
                                                           enable_mod_nl=self.enable_mod_nl):
                remainder_ions = self.central_mod_db._parse_float_list(
                    entry.get("remainder_ions", "")) if self.enable_remainder else []
                neutral_losses = self.central_mod_db._parse_float_list(
                    entry.get("neutral_losses", "")) if self.enable_mod_nl else []
                config = {
                    "neutral_losses": neutral_losses,
                    "remainder_ions": remainder_ions,
                    "labile_loss": entry.get("labile_loss", False) if effective_labile else False,
                    "generate_labile_ion": self.enable_labile,
                    "mod_mass": entry["mass"],
                }
                lookup[round(entry["mass"], 4)] = config
        return lookup

    def run(self):
        """Run the rescoring process"""
        try:
            total_start = time.time()
            timings = {}

            # === Step 1: Prepare data ===
            step_start = time.time()
            self.progress_update.emit(5, "Preparing data...")
            filtered_df = self.merged_df.copy()

            print(f"[RESCORING] Starting with {len(filtered_df)} PSMs")

            # Add grouping information
            filtered_df['Group'] = filtered_df['spectrum_file_path'].map(
                lambda x: self.grouping_data.get(x, {}).get('Group', 'Ungrouped')
            )
            filtered_df['Replicate'] = filtered_df['spectrum_file_path'].map(
                lambda x: self.grouping_data.get(x, {}).get('Replicate', '1')
            )

            # Apply decoy detection
            filtered_df = self._apply_decoy_detection(filtered_df)

            # Apply filtering options (unique peptides, top N, etc.)
            filtered_df = self._apply_filtering(filtered_df)

            if len(filtered_df) == 0:
                raise ValueError("No PSMs remaining after filtering. Please adjust your filtering options.")

            filtered_df = filtered_df.sort_values('spectrum_file_path')
            timings['Data preparation'] = self._log_step("Data preparation", step_start)

            # === Step 2: Extract spectral data from cache ===
            step_start = time.time()
            self.progress_update.emit(10, f"Extracting spectral data for {len(filtered_df)} PSMs...")

            if not self.extracted_spectral_data:
                raise ValueError("No extracted spectral data cache provided")

            print(f"[RESCORING] Cache contains {len(self.extracted_spectral_data)} spectra")

            mz_values_list = []
            intensity_values_list = []
            cache_hits = 0
            cache_misses = 0

            for idx, row in filtered_df.iterrows():
                raw_path_str = row.get("spectrum_file_path", "")
                index_str = str(row.get("index", ""))

                if not raw_path_str or not index_str:
                    mz_values_list.append([])
                    intensity_values_list.append([])
                    cache_misses += 1
                    continue

                scan_str = DataGatherer._clean_scan_number(index_str)
                cache_key = f"{raw_path_str}_{scan_str}"

                if cache_key in self.extracted_spectral_data:
                    spectral_data = self.extracted_spectral_data[cache_key]
                    mz_values_list.append(spectral_data.get('mz_values', []))
                    intensity_values_list.append(spectral_data.get('intensity_values', []))
                    cache_hits += 1
                else:
                    mz_values_list.append([])
                    intensity_values_list.append([])
                    cache_misses += 1

            print(f"[RESCORING] Cache: {cache_hits} hits, {cache_misses} misses")

            # Add spectral data columns to dataframe
            filtered_df['mz_values'] = mz_values_list
            filtered_df['intensity_values'] = intensity_values_list

            # Validate that we have spectral data
            missing_data = filtered_df['mz_values'].apply(lambda x: len(x) == 0)
            if missing_data.any():
                missing_count = missing_data.sum()
                print(f"[WARNING] {missing_count} PSMs have missing spectral data - removing")
                filtered_df = filtered_df[~missing_data].copy()

            if len(filtered_df) == 0:
                raise ValueError(
                    "No PSMs with valid spectral data found. "
                    "Please ensure 'Prepare data' has been run to extract spectral information."
                )

            print(f"[RESCORING] PSMs with valid spectral data: {len(filtered_df)}")
            timings['Spectral data extraction'] = self._log_step("Spectral data extraction", step_start)

            # === Step 3: Prepare spectral format ===
            step_start = time.time()
            self.progress_update.emit(20, f"Preparing {len(filtered_df)} spectra for fragmentation...")

            def ensure_list_format(value):
                if isinstance(value, list):
                    return value
                elif isinstance(value, str):
                    import ast
                    try:
                        return ast.literal_eval(value)
                    except:
                        return []
                else:
                    return []

            filtered_df['mz_values'] = filtered_df['mz_values'].apply(ensure_list_format)
            filtered_df['intensity_values'] = filtered_df['intensity_values'].apply(ensure_list_format)
            filtered_df['mz'] = filtered_df['mz_values']
            filtered_df['intensity'] = filtered_df['intensity_values']

            # Compute Max Intensity and Total Intensity per spectrum
            filtered_df['Max_Intensity'] = filtered_df['intensity_values'].apply(
                lambda x: max(x) if x else 0.0
            )
            filtered_df['Total_Intensity'] = filtered_df['intensity_values'].apply(
                lambda x: sum(x) if x else 0.0
            )

            timings['Spectral format prep'] = self._log_step("Spectral format prep", step_start)

            # === Step 4: Fragment matching ===
            step_start = time.time()
            total_rows = len(filtered_df)
            cores = self.options['cores']
            batch_size = max(100, total_rows // (cores * 2))

            self.progress_update.emit(25, f"Matching fragments for {total_rows} PSMs ({cores} cores)...")

            print(f"[RESCORING] Fragment matching: {total_rows} PSMs, {cores} cores, batch size {batch_size}")
            print(f"[RESCORING] Ions: {self.selected_ions}")
            if self.selected_internal_ions:
                print(f"[RESCORING] Internal ions: {self.selected_internal_ions}")
            print(f"[RESCORING] PPM tolerance: {self.options['ppm_tolerance']}, Max neutral losses: {self.max_neutral_losses}")

            # Normalize custom ion series format for worker processes
            normalized_custom_ions = []
            if self.custom_ion_series:
                for custom_ion in self.custom_ion_series:
                    normalized_custom_ions.append({
                        'base': custom_ion.get('Base Ion', custom_ion.get('base', 'y')),
                        'name': custom_ion.get('Series Name', custom_ion.get('name', 'Custom')),
                        'offset': float(custom_ion.get('Mass Offset', custom_ion.get('offset', 0))),
                        'color': custom_ion.get('Color', custom_ion.get('color', '#CCCCCC')),
                        'restriction': custom_ion.get('Restriction', custom_ion.get('restriction', ''))
                    })

            # Precompute modification-specific neutral-loss configs
            filtered_df['Mod_NL_Config'] = None
            if self.central_mod_db:
                nl_lookup = self._build_nl_lookup()
                if nl_lookup:
                    import ast as _ast
                    def _get_mod_nl_for_row(parsed_mods):
                        if parsed_mods is None or (isinstance(parsed_mods, float)):
                            return None
                        if isinstance(parsed_mods, str):
                            try:
                                mods = _ast.literal_eval(parsed_mods)
                            except Exception:
                                return None
                        else:
                            mods = parsed_mods
                        if not mods:
                            return None
                        result = []
                        has_any = False
                        for mass, _pos in mods:
                            config = nl_lookup.get(round(mass, 4))
                            if config:
                                has_any = True
                                result.append(config)
                            else:
                                result.append(None)
                        return result if has_any else None

                    filtered_df['Mod_NL_Config'] = filtered_df['Parsed Modifications'].apply(
                        _get_mod_nl_for_row
                    )
                    active_count = filtered_df['Mod_NL_Config'].notna().sum()
                    print(f"[RESCORING] Mod-NL configs: {active_count} PSMs have active definitions")

            processed_df = process_fragments(
                filtered_df,
                custom_ion_series=normalized_custom_ions,
                diagnostic_ions=self.diagnostic_ions,
                selected_ions=self.selected_ions,
                selected_internal_ions=self.selected_internal_ions,
                ppm_tolerance=self.options['ppm_tolerance'],
                max_workers=cores,
                batch_size=batch_size,
                max_neutral_losses=self.max_neutral_losses,
                calculate_isotopes=self.options.get('calculate_isotopes', False)
            )

            # Report fragment matching results
            zero_rescore = processed_df[processed_df['matched_fragments'].apply(lambda x: x is None or len(x) == 0)]
            if len(zero_rescore) > 0:
                print(f"[WARNING] {len(zero_rescore)} PSMs have no matched fragments")
            timings['Fragment matching'] = self._log_step("Fragment matching", step_start)

            # === Step 5: Ion counting ===
            step_start = time.time()
            self.progress_update.emit(65, f"Counting ion types for {len(processed_df)} PSMs...")

            # Build comprehensive ion type list
            ion_types_to_count = list(set([
                ion.split('-')[0] if '-' in ion and ion not in ['z+1', 'c-1'] else ion
                for ion in self.selected_ions
            ]))

            if self.selected_internal_ions:
                for internal_ion in self.selected_internal_ions:
                    if not internal_ion.startswith('int-'):
                        ion_types_to_count.append(f'int-{internal_ion}')
                    else:
                        ion_types_to_count.append(internal_ion)

            if self.custom_ion_series:
                for custom_ion in self.custom_ion_series:
                    series_name = custom_ion.get('name', custom_ion.get('Series Name', ''))
                    if series_name and series_name not in ion_types_to_count:
                        ion_types_to_count.append(series_name)

            # Discover granular Mod-NL sub-types from matched fragments
            mod_nl_subtypes = []
            if self.central_mod_db is not None:
                mod_nl_subtypes = self._discover_mod_nl_subtypes(processed_df)
                ion_types_to_count.extend(mod_nl_subtypes)
                if mod_nl_subtypes:
                    print(f"[RESCORING] Mod-NL sub-types discovered: {mod_nl_subtypes}")

            self.mod_nl_subtypes = mod_nl_subtypes

            processed_df = count_ion_types_parallel(
                processed_df,
                ion_types_to_count=ion_types_to_count,
                max_workers=self.options['cores'],
                batch_size=1000,
                scoring_max_charge=self.options.get('scoring_max_charge', 0)
            )
            timings['Ion counting'] = self._log_step("Ion counting", step_start)

            # === Step 6: Hydrogen Migration Tracking ===
            migration_settings = self.options.get('migration_settings', {})
            z_migration_enabled = migration_settings.get('z_migration_enabled', False)
            c_migration_enabled = migration_settings.get('c_migration_enabled', False)

            if z_migration_enabled or c_migration_enabled:
                step_start = time.time()
                self.progress_update.emit(78, "Calculating hydrogen migration ratios...")

                min_charge = migration_settings.get('min_charge', 1)
                max_charge = migration_settings.get('max_charge', 3)
                charge_range = list(range(min_charge, max_charge + 1))

                processed_df = calculate_migration_ratios_parallel(
                    processed_df,
                    z_migration_enabled=z_migration_enabled,
                    c_migration_enabled=c_migration_enabled,
                    charge_range=charge_range,
                    max_workers=self.options['cores'],
                    batch_size=1000
                )

                if z_migration_enabled and 'z_migration' in processed_df.columns:
                    non_empty = processed_df['z_migration'].apply(lambda x: x != '' and x is not None).sum()
                    print(f"[MIGRATION] z+1 migration computed for {non_empty} PSMs")
                if c_migration_enabled and 'c_migration' in processed_df.columns:
                    non_empty = processed_df['c_migration'].apply(lambda x: x != '' and x is not None).sum()
                    print(f"[MIGRATION] c migration computed for {non_empty} PSMs")
                timings['Migration tracking'] = self._log_step("Migration tracking", step_start)

            # === Step 7: Score calculation ===
            step_start = time.time()
            self.progress_update.emit(82, "Calculating rescores...")

            processed_df = calculate_scores_parallel(
                processed_df,
                ion_types_to_use=ion_types_to_count,
                max_workers=cores,
                scoring_methods=self.scoring_methods,
                ppm_tolerance=self.options['ppm_tolerance'],
                scoring_max_charge=self.options.get('scoring_max_charge', 0)
            )
            timings['Score calculation'] = self._log_step("Score calculation", step_start)

            # === Step 7b: Length-dependent score normalization (post-processing) ===
            if self.scoring_methods and self.scoring_methods.get('length_dependent_normalized_score'):
                step_start = time.time()
                self.progress_update.emit(88, "Computing length-dependent normalized scores...")
                from utils.rescoring.threaded_fragmentation_functions import calculate_length_dependent_normalized_scores
                processed_df['Length_Dependent_Normalized_Score'] = calculate_length_dependent_normalized_scores(
                    processed_df,
                    score_column='Morpheus_Score',
                    psm_type_column='PSM_Type',
                    peptide_column='Peptide'
                )
                timings['Length-dependent normalization'] = self._log_step("Length-dependent normalization", step_start)

            # === Step 8: Finalize ===
            step_start = time.time()
            self.progress_update.emit(92, "Finalizing results...")

            # Store complete dataframe for debugging BEFORE cleaning
            self.debug_df = processed_df.copy()

            # Report score statistics
            zero_scores = processed_df[processed_df['Rescore'] == 0.0]
            if len(zero_scores) > 0:
                print(f"[RESCORING] PSMs with zero rescore: {len(zero_scores)} out of {len(processed_df)}")

            columns_to_drop = [
                'Theoretical_Fragments',
                'matched_fragments',
                'mz',
                'intensity',
                'mz_values',
                'intensity_values',
            ]
            final_df = processed_df.drop(columns=columns_to_drop, errors='ignore')
            timings['Finalization'] = self._log_step("Finalization", step_start)

            # === Done - print timing summary ===
            total_elapsed = time.time() - total_start
            self.progress_update.emit(100, "Complete!")

            print(f"\n{'='*60}")
            print(f"[RESCORING] COMPLETE - {len(final_df)} PSMs in {total_elapsed:.1f}s")
            print(f"{'='*60}")
            print(f"  Rescore: Mean={final_df['Rescore'].mean():.3f}, "
                f"Median={final_df['Rescore'].median():.3f}, "
                f"Max={final_df['Rescore'].max():.3f}")
            print(f"  {'-'*60}")
            print(f"  {'Step':<30} {'Time':>8} {'%':>6}")
            print(f"  {'-'*46}")
            for step_name, elapsed in timings.items():
                pct = (elapsed / total_elapsed * 100) if total_elapsed > 0 else 0
                print(f"  {step_name:<30} {elapsed:>7.2f}s {pct:>5.1f}%")
            print(f"  {'-'*46}")
            print(f"  {'TOTAL':<30} {total_elapsed:>7.2f}s")
            print(f"{'='*60}\n")

            # Emit completion signal
            self.rescoring_complete.emit(final_df)

        except Exception as e:
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            print(f"[ERROR] Rescoring failed: {error_msg}")
            self.rescoring_error.emit(error_msg)

    def _discover_mod_nl_subtypes(self, processed_df):
        """Scan matched fragments to discover all unique Mod-NL sub-types.

        Returns a sorted list of strings like 'ModNL1-y', 'ModNL1x2-y',
        'LabileLoss-b', etc.  Each string encodes NeutralLoss + '-' + BaseType.
        """
        _MOD_NL_PREFIXES = ("ModNL", "LabileLoss", "ModRM")
        seen = set()
        for fragments in processed_df['matched_fragments']:
            if not fragments:
                continue
            for frag in fragments:
                if len(frag) < 10:
                    continue
                if frag[2] is None or frag[2] == "No Match":
                    continue
                try:
                    isotope = int(float(frag[9]))
                except (ValueError, TypeError):
                    isotope = 0
                if isotope != 0:
                    continue
                nl = str(frag[7]) if frag[7] is not None else ''
                if not any(nl.startswith(p) for p in _MOD_NL_PREFIXES):
                    continue
                # Get base type (idx 11) for grouping
                base_type = str(frag[11]).strip() if len(frag) > 11 and frag[11] else str(frag[5]).strip()
                if not base_type or base_type in ('None', 'nan', ''):
                    continue
                seen.add(f"{nl}-{base_type}")
        return sorted(seen)

    def _apply_filtering(self, df):
        """Apply filtering options (unique peptides, top N, etc.)"""

        print(f"[RESCORING] Filters: topN={self.options['topN']}, "
            f"unique_pep={self.options['unique_pep']}, "
            f"unique_mod={self.options['unique_mod']}, "
            f"groupby={self.options.get('groupby_column', None)}")

        filtered_df = DataProcessingUtils.filter_dataframe(
            df,
            topN=self.options['topN'],
            unique_pep=self.options['unique_pep'],
            unique_mod=self.options['unique_mod'],
            groupby_column=self.options.get('groupby_column', None)
        )

        print(f"[RESCORING] Filtering: {len(df)} -> {len(filtered_df)} PSMs")

        return filtered_df

    def _apply_decoy_detection(self, df):
        """Apply decoy detection to dataframe"""
        if not self.decoy_settings["enabled"] or not self.decoy_settings["decoy_string"]:
            return df

        if 'Protein' not in df.columns:
            print("[WARNING] 'Protein' column not found - skipping decoy detection")
            return df

        decoy_string = self.decoy_settings["decoy_string"]
        df['PSM_Type'] = df['Protein'].apply(
            lambda x: 'Decoy' if isinstance(x, str) and decoy_string in x else 'Target'
        )

        target_count = (df['PSM_Type'] == 'Target').sum()
        decoy_count = (df['PSM_Type'] == 'Decoy').sum()
        print(f"[RESCORING] Decoy detection '{decoy_string}': {target_count} target, {decoy_count} decoy")

        return df
