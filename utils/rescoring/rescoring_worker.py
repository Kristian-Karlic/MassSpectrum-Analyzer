import logging
import time
import threading
import traceback
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from utils.utilities import DataGatherer
from utils.rescoring.threaded_fragmentation_functions import (
    process_fragments,
    count_ion_types_parallel,
    calculate_migration_ratios_parallel,
    calculate_scores_parallel,
)
from utils.utilities import DataProcessingUtils

logger = logging.getLogger(__name__)


class RescoringWorker(QThread):
    """Worker thread for rescoring process"""

    progress_update = pyqtSignal(int, str)
    rescoring_complete = pyqtSignal(object)
    rescoring_error = pyqtSignal(str)
    rescoring_cancelled = pyqtSignal()

    def __init__(
        self,
        merged_df,
        options,
        custom_ion_series,
        diagnostic_ions,
        selected_ions,
        selected_internal_ions,
        grouping_data,
        decoy_settings,
        max_neutral_losses,
        extracted_spectral_data,
        scoring_methods=None,
        central_mod_db=None,
        enable_labile=False,
        enable_remainder=False,
        enable_mod_nl=False,
    ):
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
        self._cancel_event = threading.Event()

    def cancel(self):
        """Request graceful cancellation of the rescoring process."""
        self._cancel_event.set()
        self.requestInterruption()

    def _raise_if_cancelled(self):
        """Raise interruption when cancellation is requested."""
        if self._cancel_event.is_set() or self.isInterruptionRequested():
            raise InterruptedError("Rescoring cancelled")

    def _log_step(self, step_name, start_time):
        """Log completion of a step with elapsed time"""
        elapsed = time.time() - start_time
        logger.debug(f"[TIMING] {step_name}: {elapsed:.2f}s")
        return elapsed

    def _get_mod_nl_for_row(self, parsed_mods):
        """Build per-modification neutral-loss config for one PSM row.

        Uses ``DataGatherer.build_mod_neutral_losses`` — the same tolerance-
        based lookup (0.01 Da) that the single-peptide annotation path uses.
        This avoids the exact-key mismatch that can occur when PSM masses
        differ slightly from central-mod-db masses.
        """
        if parsed_mods is None or isinstance(parsed_mods, float):
            return None
        if isinstance(parsed_mods, str):
            import ast as _ast

            try:
                mods = _ast.literal_eval(parsed_mods)
            except Exception:
                return None
        else:
            mods = parsed_mods
        if not mods:
            return None
        return DataGatherer.build_mod_neutral_losses(
            mods,
            self.central_mod_db,
            enable_labile=self.enable_labile,
            enable_remainder=self.enable_remainder,
            enable_mod_nl=self.enable_mod_nl,
        )

    def run(self):
        """Run the rescoring process"""
        try:
            total_start = time.time()
            timings = {}
            self._raise_if_cancelled()

            # === Step 1: Prepare data ===
            step_start = time.time()
            self.progress_update.emit(5, "Preparing data...")
            filtered_df = self.merged_df.copy()

            logger.debug(f"[RESCORING] Starting with {len(filtered_df)} PSMs")

            # Add grouping information
            filtered_df["Group"] = filtered_df["spectrum_file_path"].map(
                lambda x: self.grouping_data.get(x, {}).get("Group", "Ungrouped")
            )
            filtered_df["Replicate"] = filtered_df["spectrum_file_path"].map(
                lambda x: self.grouping_data.get(x, {}).get("Replicate", "1")
            )

            # Apply decoy detection
            filtered_df = self._apply_decoy_detection(filtered_df)

            # Apply filtering options (unique peptides, top N, etc.)
            filtered_df = self._apply_filtering(filtered_df)
            self._raise_if_cancelled()

            if len(filtered_df) == 0:
                raise ValueError(
                    "No PSMs remaining after filtering. Please adjust your filtering options."
                )

            filtered_df = filtered_df.sort_values("spectrum_file_path")
            timings["Data preparation"] = self._log_step("Data preparation", step_start)

            # === Step 2: Extract spectral data from cache ===
            step_start = time.time()
            self.progress_update.emit(
                10, f"Extracting spectral data for {len(filtered_df)} PSMs..."
            )

            if not self.extracted_spectral_data:
                raise ValueError("No extracted spectral data cache provided")

            logger.debug(
                f"[RESCORING] Cache contains {len(self.extracted_spectral_data)} spectra"
            )

            mz_values_list = []
            intensity_values_list = []
            cache_hits = 0
            cache_misses = 0

            for row in filtered_df.itertuples(index=False):
                self._raise_if_cancelled()
                raw_path_str = getattr(row, "spectrum_file_path", "")
                index_str = str(getattr(row, "index", ""))

                if not raw_path_str or not index_str:
                    mz_values_list.append([])
                    intensity_values_list.append([])
                    cache_misses += 1
                    continue

                scan_str = DataGatherer._clean_scan_number(index_str)
                cache_key = f"{raw_path_str}_{scan_str}"

                if cache_key in self.extracted_spectral_data:
                    spectral_data = self.extracted_spectral_data[cache_key]
                    mz_values_list.append(spectral_data.get("mz_values", []))
                    intensity_values_list.append(
                        spectral_data.get("intensity_values", [])
                    )
                    cache_hits += 1
                else:
                    mz_values_list.append([])
                    intensity_values_list.append([])
                    cache_misses += 1

            logger.debug(f"[RESCORING] Cache: {cache_hits} hits, {cache_misses} misses")

            # Add spectral data columns to dataframe
            filtered_df["mz_values"] = mz_values_list
            filtered_df["intensity_values"] = intensity_values_list

            # Validate that we have spectral data
            missing_data = filtered_df["mz_values"].apply(lambda x: len(x) == 0)
            if missing_data.any():
                missing_count = missing_data.sum()
                logger.warning(
                    f"{missing_count} PSMs have missing spectral data - removing"
                )
                filtered_df = filtered_df[~missing_data].copy()

            if len(filtered_df) == 0:
                raise ValueError(
                    "No PSMs with valid spectral data found. "
                    "Please ensure 'Prepare data' has been run to extract spectral information."
                )

            logger.debug(
                f"[RESCORING] PSMs with valid spectral data: {len(filtered_df)}"
            )
            timings["Spectral data extraction"] = self._log_step(
                "Spectral data extraction", step_start
            )

            # === Step 3: Prepare spectral format ===
            step_start = time.time()
            self.progress_update.emit(
                20, f"Preparing {len(filtered_df)} spectra for fragmentation..."
            )

            def ensure_list_format(value):
                if isinstance(value, list):
                    return value
                elif isinstance(value, str):
                    import ast

                    try:
                        return ast.literal_eval(value)
                    except Exception:
                        return []
                else:
                    return []

            filtered_df["mz_values"] = filtered_df["mz_values"].apply(
                ensure_list_format
            )
            filtered_df["intensity_values"] = filtered_df["intensity_values"].apply(
                ensure_list_format
            )
            filtered_df["mz"] = filtered_df["mz_values"]
            filtered_df["intensity"] = filtered_df["intensity_values"]
            self._raise_if_cancelled()

            # Compute Max Intensity and Total Intensity per spectrum
            filtered_df["Max_Intensity"] = filtered_df["intensity_values"].apply(
                lambda x: max(x) if x else 0.0
            )
            filtered_df["Total_Intensity"] = filtered_df["intensity_values"].apply(
                lambda x: sum(x) if x else 0.0
            )

            timings["Spectral format prep"] = self._log_step(
                "Spectral format prep", step_start
            )

            # === Step 4: Fragment processing (theoretical calc + matching) ===
            step_start = time.time()
            total_rows = len(filtered_df)
            cores = self.options["cores"]
            batch_size = max(100, total_rows // (cores * 2))

            logger.debug(
                f"[RESCORING] Fragment processing: {total_rows} PSMs, {cores} cores, batch size {batch_size}"
            )
            logger.debug(f"[RESCORING] Ions: {self.selected_ions}")
            if self.selected_internal_ions:
                logger.debug(
                    f"[RESCORING] Internal ions: {self.selected_internal_ions}"
                )
            logger.debug(
                f"[RESCORING] PPM tolerance: {self.options['ppm_tolerance']}, Max neutral losses: {self.max_neutral_losses}"
            )

            # Normalize custom ion series format for worker processes
            normalized_custom_ions = []
            if self.custom_ion_series:
                for custom_ion in self.custom_ion_series:
                    normalized_custom_ions.append(
                        {
                            "base": custom_ion.get(
                                "Base Ion", custom_ion.get("base", "y")
                            ),
                            "name": custom_ion.get(
                                "Series Name", custom_ion.get("name", "Custom")
                            ),
                            "offset": float(
                                custom_ion.get(
                                    "Mass Offset", custom_ion.get("offset", 0)
                                )
                            ),
                            "color": custom_ion.get(
                                "Color", custom_ion.get("color", "#CCCCCC")
                            ),
                            "restriction": custom_ion.get(
                                "Restriction", custom_ion.get("restriction", "")
                            ),
                        }
                    )

            # Precompute modification-specific neutral-loss configs
            filtered_df["Mod_NL_Config"] = None
            if self.central_mod_db:
                filtered_df["Mod_NL_Config"] = filtered_df[
                    "Parsed Modifications"
                ].apply(self._get_mod_nl_for_row)
                active_count = filtered_df["Mod_NL_Config"].notna().sum()
                logger.debug(
                    f"[RESCORING] Mod-NL configs: {active_count} PSMs have active definitions"
                )

            processed_df = process_fragments(
                filtered_df,
                custom_ion_series=normalized_custom_ions,
                diagnostic_ions=self.diagnostic_ions,
                selected_ions=self.selected_ions,
                selected_internal_ions=self.selected_internal_ions,
                ppm_tolerance=self.options["ppm_tolerance"],
                max_workers=cores,
                batch_size=batch_size,
                max_neutral_losses=self.max_neutral_losses,
                calculate_isotopes=self.options.get("calculate_isotopes", False),
                isotope_max=self.options.get("isotope_max", 4),
                progress_callback=lambda v, m: self.progress_update.emit(v, m),
                cancel_event=self._cancel_event,
            )
            self._raise_if_cancelled()

            # Report fragment matching results
            zero_rescore = processed_df[
                processed_df["matched_fragments"].apply(
                    lambda x: x is None or len(x) == 0
                )
            ]
            if len(zero_rescore) > 0:
                logger.warning(f"{len(zero_rescore)} PSMs have no matched fragments")
            timings["Fragment matching"] = self._log_step(
                "Fragment matching", step_start
            )

            # === Step 5: Ion counting ===
            step_start = time.time()
            self.progress_update.emit(
                65, f"Counting ion types for {len(processed_df)} PSMs..."
            )

            # Build comprehensive ion type list
            ion_types_to_count = list(
                set(
                    [
                        (
                            ion.split("-")[0]
                            if "-" in ion and ion not in ["z+1", "c-1"]
                            else ion
                        )
                        for ion in self.selected_ions
                    ]
                )
            )

            if self.selected_internal_ions:
                for internal_ion in self.selected_internal_ions:
                    if not internal_ion.startswith("int-"):
                        ion_types_to_count.append(f"int-{internal_ion}")
                    else:
                        ion_types_to_count.append(internal_ion)

            if self.custom_ion_series:
                for custom_ion in self.custom_ion_series:
                    series_name = custom_ion.get(
                        "name", custom_ion.get("Series Name", "")
                    )
                    if series_name and series_name not in ion_types_to_count:
                        ion_types_to_count.append(series_name)

            # Discover granular Mod-NL sub-types from matched fragments
            mod_nl_subtypes = []
            if self.central_mod_db is not None:
                mod_nl_subtypes = self._discover_mod_nl_subtypes(processed_df)
                ion_types_to_count.extend(mod_nl_subtypes)
                if mod_nl_subtypes:
                    logger.debug(
                        f"[RESCORING] Mod-NL sub-types discovered: {mod_nl_subtypes}"
                    )

            self.mod_nl_subtypes = mod_nl_subtypes

            processed_df = count_ion_types_parallel(
                processed_df,
                ion_types_to_count=ion_types_to_count,
                max_workers=self.options["cores"],
                batch_size=1000,
                scoring_max_charge=self.options.get("scoring_max_charge", 0),
            )
            self._raise_if_cancelled()
            timings["Ion counting"] = self._log_step("Ion counting", step_start)

            # === Step 6: Hydrogen Migration Tracking ===
            migration_settings = self.options.get("migration_settings", {})
            z_migration_enabled = migration_settings.get("z_migration_enabled", False)
            c_migration_enabled = migration_settings.get("c_migration_enabled", False)

            if z_migration_enabled or c_migration_enabled:
                step_start = time.time()
                self.progress_update.emit(
                    78, "Calculating hydrogen migration ratios..."
                )

                min_charge = migration_settings.get("min_charge", 1)
                max_charge = migration_settings.get("max_charge", 3)
                charge_range = list(range(min_charge, max_charge + 1))

                processed_df = calculate_migration_ratios_parallel(
                    processed_df,
                    z_migration_enabled=z_migration_enabled,
                    c_migration_enabled=c_migration_enabled,
                    charge_range=charge_range,
                    max_workers=self.options["cores"],
                    batch_size=1000,
                )
                self._raise_if_cancelled()

                if z_migration_enabled and "z_migration" in processed_df.columns:
                    non_empty = (
                        processed_df["z_migration"]
                        .apply(lambda x: x != "" and x is not None)
                        .sum()
                    )
                    logger.debug(
                        f"[MIGRATION] z+1 migration computed for {non_empty} PSMs"
                    )
                if c_migration_enabled and "c_migration" in processed_df.columns:
                    non_empty = (
                        processed_df["c_migration"]
                        .apply(lambda x: x != "" and x is not None)
                        .sum()
                    )
                    logger.debug(
                        f"[MIGRATION] c migration computed for {non_empty} PSMs"
                    )
                timings["Migration tracking"] = self._log_step(
                    "Migration tracking", step_start
                )

            # === Step 7: Score calculation ===
            step_start = time.time()
            self.progress_update.emit(82, "Calculating rescores...")

            processed_df = calculate_scores_parallel(
                processed_df,
                ion_types_to_use=ion_types_to_count,
                max_workers=cores,
                scoring_methods=self.scoring_methods,
                ppm_tolerance=self.options["ppm_tolerance"],
                scoring_max_charge=self.options.get("scoring_max_charge", 0),
                scoring_nl_in_count=self.options.get("scoring_nl_in_count", False),
            )
            self._raise_if_cancelled()
            timings["Score calculation"] = self._log_step(
                "Score calculation", step_start
            )

            # === Step 7c: Mokapot FDR Control ===
            if self.scoring_methods and self.scoring_methods.get("mokapot_fdr"):
                if "PSM_Type" not in processed_df.columns:
                    logger.warning("Mokapot FDR skipped: decoy detection not enabled")
                else:
                    step_start = time.time()
                    self.progress_update.emit(90, "Running Mokapot FDR control...")
                    try:
                        processed_df = self._run_mokapot(processed_df)
                    except Exception as e:
                        logger.warning(
                            f"Mokapot FDR failed, continuing without FDR columns: {e}"
                        )
                        traceback.print_exc()
                    self._raise_if_cancelled()
                    timings["Mokapot FDR"] = self._log_step("Mokapot FDR", step_start)

            # === Step 8: Finalize ===
            step_start = time.time()
            self.progress_update.emit(92, "Finalizing results...")

            # Keep pre-cleaned dataframe for fragment export in the results viewer
            self.debug_df = processed_df

            # Report score statistics
            zero_scores = processed_df[processed_df["Rescore"] == 0.0]
            if len(zero_scores) > 0:
                logger.debug(
                    f"[RESCORING] PSMs with zero rescore: {len(zero_scores)} out of {len(processed_df)}"
                )

            columns_to_drop = [
                "Theoretical_Fragments",
                "matched_fragments",
                "mz",
                "intensity",
                "mz_values",
                "intensity_values",
            ]
            final_df = processed_df.drop(columns=columns_to_drop, errors="ignore")
            timings["Finalization"] = self._log_step("Finalization", step_start)

            # === Done - print timing summary ===
            total_elapsed = time.time() - total_start
            self.progress_update.emit(100, "Complete!")

            logger.debug(f"\n{'='*60}")
            logger.debug(
                f"[RESCORING] COMPLETE - {len(final_df)} PSMs in {total_elapsed:.1f}s"
            )
            logger.debug(f"{'='*60}")
            logger.debug(
                f"  Rescore: Mean={final_df['Rescore'].mean():.3f}, Median={final_df['Rescore'].median():.3f}, Max={final_df['Rescore'].max():.3f}"
            )
            logger.debug(f"  {'-'*60}")
            logger.debug(f"  {'Step':<30} {'Time':>8} {'%':>6}")
            logger.debug(f"  {'-'*46}")
            for step_name, elapsed in timings.items():
                pct = (elapsed / total_elapsed * 100) if total_elapsed > 0 else 0
                logger.debug(f"  {step_name:<30} {elapsed:>7.2f}s {pct:>5.1f}%")
            logger.debug(f"  {'-'*46}")
            logger.debug(f"  {'TOTAL':<30} {total_elapsed:>7.2f}s")
            logger.debug(f"{'='*60}\n")

            # Emit completion signal
            self.rescoring_complete.emit(final_df)

            # Release large input data — no longer needed after rescoring completes
            self.merged_df = None
            self.extracted_spectral_data = None
            self.custom_ion_series = None
            self.diagnostic_ions = None
            self.grouping_data = None
            self.central_mod_db = None

        except InterruptedError:
            logger.debug("[RESCORING] Cancelled by user")
            self.rescoring_cancelled.emit()

        except Exception as e:
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            logger.error(f"Rescoring failed: {error_msg}")
            self.rescoring_error.emit(error_msg)

    def _discover_mod_nl_subtypes(self, processed_df):
        """Scan matched fragments to discover all unique Mod-NL sub-types.

        Returns a sorted list of strings like 'ModNL1-y', 'ModNL1x2-y',
        'LabileLoss-b', etc.  Each string encodes NeutralLoss + '-' + BaseType.
        """
        _MOD_NL_PREFIXES = ("ModNL", "LabileLoss", "ModRM")
        seen = set()
        for fragments in processed_df["matched_fragments"]:
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
                nl = str(frag[7]) if frag[7] is not None else ""
                if not any(nl.startswith(p) for p in _MOD_NL_PREFIXES):
                    continue
                # Get base type (idx 11) for grouping
                base_type = (
                    str(frag[11]).strip()
                    if len(frag) > 11 and frag[11]
                    else str(frag[5]).strip()
                )
                if not base_type or base_type in ("None", "nan", ""):
                    continue
                seen.add(f"{nl}-{base_type}")
        return sorted(seen)

    def _apply_filtering(self, df):
        """Apply filtering options (unique peptides, top N, etc.)"""

        logger.debug(
            f"[RESCORING] Filters: topN={self.options['topN']}, unique_pep={self.options['unique_pep']}, unique_mod={self.options['unique_mod']}, groupby={self.options.get('groupby_column', None)}"
        )

        filtered_df = DataProcessingUtils.filter_dataframe(
            df,
            topN=self.options["topN"],
            unique_pep=self.options["unique_pep"],
            unique_mod=self.options["unique_mod"],
            groupby_column=self.options.get("groupby_column", None),
        )

        logger.debug(f"[RESCORING] Filtering: {len(df)} -> {len(filtered_df)} PSMs")

        return filtered_df

    def _apply_decoy_detection(self, df):
        """Apply decoy detection to dataframe"""
        if (
            not self.decoy_settings["enabled"]
            or not self.decoy_settings["decoy_string"]
        ):
            return df

        if "Protein" not in df.columns:
            logger.warning("'Protein' column not found - skipping decoy detection")
            return df

        decoy_string = self.decoy_settings["decoy_string"]
        df["PSM_Type"] = df["Protein"].apply(
            lambda x: "Decoy" if isinstance(x, str) and decoy_string in x else "Target"
        )

        target_count = (df["PSM_Type"] == "Target").sum()
        decoy_count = (df["PSM_Type"] == "Decoy").sum()
        logger.debug(
            f"[RESCORING] Decoy detection '{decoy_string}': {target_count} target, {decoy_count} decoy"
        )

        return df

    def _run_mokapot(self, df):
        """Run mokapot for FDR control on the rescored PSMs.

        Collects all numeric feature columns dynamically, constructs a
        mokapot LinearPsmDataset, runs brew(), and merges q-values and
        PEP back into the dataframe.
        """
        import pandas as pd
        import tempfile
        from pathlib import Path

        # Patch NumPy 2.0 compatibility for mokapot 0.10.0
        if not hasattr(np, "float_"):
            np.float_ = np.float64
        import mokapot

        # 1. Build feature set for mokapot
        feature_cols = []

        # Include specific numeric columns by pattern:
        #  - Rescore, Avg_error (direct scores)
        #  - {ion}_count columns (y_count, b_count, a_count, etc.) excluding MH
        #  - ModNL1-{ion}_count / RM1 columns (no x2, x3 etc.)
        for col in df.columns:
            if col in ("Rescore", "Avg_error"):
                feature_cols.append(col)
            elif (
                col.endswith("_count")
                and "_unique_count" not in col
                and not col.startswith("total_")
            ):
                # Skip anything with MH in the name
                if "MH" in col.upper():
                    continue
                # Skip ModNL1x2, ModNL1x3, etc. — only allow plain ModNL1-
                if "ModNL1x" in col or "RM1x" in col:
                    continue
                # e.g. y_count, b_count, ModNL1-y_count, RM1-b_count
                if pd.api.types.is_numeric_dtype(df[col]) and df[col].notna().any():
                    feature_cols.append(col)

        logger.debug(f"[MOKAPOT] Selected {len(feature_cols)} features: {feature_cols}")

        # Charge - one-hot encoded
        if "Charge" in df.columns:
            charges = pd.to_numeric(df["Charge"], errors="coerce").fillna(0).astype(int)
            charges = charges.clip(upper=7)  # anything ≥7 becomes 7
            for z in range(1, 8):
                col = f"charge_{z}"
                df[col] = (charges == z).astype(int)
                feature_cols.append(col)

        # Ensure peptide length column exists
        if "Peptide Length" in df.columns and df["Peptide Length"].notna().any():
            df["_moka_PepLen"] = (
                pd.to_numeric(df["Peptide Length"], errors="coerce")
                .fillna(df["Peptide"].str.len())
                .astype(int)
            )
        else:
            df["_moka_PepLen"] = df["Peptide"].str.len().astype(int)

        # MSFragger-style bins
        df["length_7"] = (df["_moka_PepLen"] == 7).astype(int)
        df["length_8"] = (df["_moka_PepLen"] == 8).astype(int)
        df["length_9_30"] = df["_moka_PepLen"].between(9, 30).astype(int)
        df["length_31"] = (df["_moka_PepLen"] >= 31).astype(int)

        # Track features
        feature_cols.extend(["length_7", "length_8", "length_9_30", "length_31"])

        # Total matched ion count - single column summing all base types (exclude MH)
        total_matched = pd.Series(0, index=df.index)
        for col in df.columns:
            if col.startswith("total_") and col.endswith("_count"):
                base_type = col.replace("total_", "").replace("_count", "")
                if base_type.upper() == "MH":
                    continue
                total_matched += df[col].fillna(0)
        df["matched_ion_num"] = total_matched
        feature_cols.append("matched_ion_num")

        if len(feature_cols) < 1:
            raise ValueError("No feature columns available for mokapot")

        logger.debug(
            f"[MOKAPOT] Total features for training ({len(feature_cols)}): {feature_cols}"
        )

        # 2. Validate target/decoy counts
        is_target = df["PSM_Type"] == "Target"
        n_target = is_target.sum()
        n_decoy = (~is_target).sum()
        if n_target == 0 or n_decoy == 0:
            raise ValueError(
                f"Mokapot requires both targets and decoys. "
                f"Found {n_target} targets, {n_decoy} decoys."
            )

        if len(df) < 200:
            logger.debug(
                f"[MOKAPOT] Warning: only {len(df)} PSMs - results may be unreliable"
            )

        # Add retention time if available
        for rt_col in ("Retention", "Retention Time", "RT"):
            if rt_col in df.columns and df[rt_col].notna().any():
                df["Retention"] = pd.to_numeric(df[rt_col], errors="coerce").fillna(0)
                feature_cols.append("Retention")
                logger.debug(
                    f"[MOKAPOT] Including retention time from '{rt_col}' column"
                )
                break

        # Experimental mass from Observed M/Z and Charge: ExpMass = (mz * z) - (z * 1.00728)
        if "Observed M/Z" in df.columns and "Charge" in df.columns:
            mz = pd.to_numeric(df["Observed M/Z"], errors="coerce").fillna(0)
            z = pd.to_numeric(df["Charge"], errors="coerce").fillna(0)
            df["ExpMass"] = (mz * z) - (z * 1.00727646677)
            feature_cols.append("ExpMass")
            logger.debug(
                "[MOKAPOT] Including ExpMass (calculated from Observed M/Z × Charge)"
            )

        # Number of missed cleavages
        if "Missed Cleavages" in df.columns:
            df["nmc"] = (
                pd.to_numeric(df["Missed Cleavages"], errors="coerce")
                .fillna(0)
                .astype(int)
            )
            feature_cols.append("nmc")
            logger.debug("[MOKAPOT] Including nmc (Missed Cleavages)")

        # Delta hyperscore
        if "Delta Hyperscore" in df.columns and df["Delta Hyperscore"].notna().any():
            df["delta_hyperscore"] = pd.to_numeric(
                df["Delta Hyperscore"], errors="coerce"
            ).fillna(0)
            feature_cols.append("delta_hyperscore")
            logger.debug("[MOKAPOT] Including delta_hyperscore")

        # Binary group: 1 if peptide has any modification with mass > 50 Da, else 0
        def _has_large_mod(parsed_mods):
            if parsed_mods is None or (
                isinstance(parsed_mods, float) and pd.isna(parsed_mods)
            ):
                return 0
            if isinstance(parsed_mods, str):
                import ast

                try:
                    mods = ast.literal_eval(parsed_mods)
                except Exception:
                    return 0
            else:
                mods = parsed_mods
            if not mods:
                return 0
            return 1 if any(abs(mass) > 50 for mass, _pos in mods) else 0

        if "Parsed Modifications" in df.columns:
            df["group"] = df["Parsed Modifications"].apply(_has_large_mod)
            feature_cols.append("group")
            n_mod = (df["group"] == 1).sum()
            logger.debug(
                f"[MOKAPOT] Including group feature (modified >50Da: {n_mod}, unmodified: {len(df) - n_mod})"
            )

        # 3. Build PIN-format DataFrame for mokapot
        #    Label: 1 = target, 0 = decoy (mokapot converts to bool internally; -1 is truthy)
        #    ScanNr: sequential index for reliable merge-back
        #    Peptide: MSFragger PIN format PrevAA.ModifiedSequenceCharge.NextAA
        charge_str = (
            pd.to_numeric(df["Charge"], errors="coerce")
            .fillna(0)
            .astype(int)
            .astype(str)
        )

        if "Modified Peptide" in df.columns:
            pep_base = df["Modified Peptide"].fillna(df["Peptide"]).astype(str)
        else:
            pep_base = df["Peptide"].astype(str)

        pep_with_charge = pep_base + charge_str

        if "Prev.AA" in df.columns and "Next.AA" in df.columns:
            prev_aa = df["Prev.AA"].fillna("-").astype(str)
            next_aa = df["Next.AA"].fillna("-").astype(str)
            peptide_col = prev_aa + "." + pep_with_charge + "." + next_aa
        else:
            peptide_col = pep_with_charge

        pin_df = pd.DataFrame(
            {
                "Label": np.where(is_target.values, 1, 0),
                "ScanNr": np.arange(len(df)),
                "Peptide": peptide_col.values,
                "Proteins": df["Protein"].fillna("Unknown").values,
            }
        )

        for col in feature_cols:
            pin_df[col] = df[col].fillna(0).values

        # 4. Create mokapot dataset
        dataset = mokapot.LinearPsmDataset(
            psms=pin_df,
            target_column="Label",
            spectrum_columns=["ScanNr"],
            peptide_column="Peptide",
            protein_column="Proteins",
            feature_columns=feature_cols,
        )

        # 5. Run brew (semi-supervised learning + confidence estimation)
        #    Use custom SVM with higher max_iter to avoid IRLS convergence warnings
        from sklearn.svm import LinearSVC
        from sklearn.model_selection import GridSearchCV, KFold

        svm = LinearSVC(dual=False, max_iter=5000, random_state=7)
        param_grid = {"C": [0.1, 1, 10]}
        cv_model = GridSearchCV(
            svm,
            param_grid=param_grid,
            refit=False,
            cv=KFold(3, shuffle=True, random_state=42),
            n_jobs=-1,
        )
        model = mokapot.Model(
            estimator=cv_model,
            train_fdr=0.01,
            max_iter=10,
            rng=42,
        )
        results, models = mokapot.brew(
            dataset, model=model, test_fdr=0.01, folds=3, rng=42
        )

        # 6. Write results to temp files and read back for merge
        with tempfile.TemporaryDirectory() as tmpdir:
            files = results.to_txt(dest_dir=tmpdir, decoys=True)

            # Read target and decoy PSM result files separately for validation
            target_psms = None
            decoy_psms = None
            for f in files:
                fname = Path(f).name
                if "psms" in fname:
                    file_df = pd.read_csv(f, sep="\t")
                    if "decoy" in fname:
                        decoy_psms = file_df
                    else:
                        target_psms = file_df

            if target_psms is None:
                raise ValueError("Mokapot produced no target PSM results")

            # Row count integrity checks per file
            if len(target_psms) != n_target:
                raise ValueError(
                    f"Target row count mismatch: {n_target} input targets vs "
                    f"{len(target_psms)} mokapot target results"
                )
            if decoy_psms is not None and len(decoy_psms) != n_decoy:
                raise ValueError(
                    f"Decoy row count mismatch: {n_decoy} input decoys vs "
                    f"{len(decoy_psms)} mokapot decoy results"
                )

            psm_dfs = [target_psms]
            if decoy_psms is not None:
                psm_dfs.append(decoy_psms)
            psm_results = pd.concat(psm_dfs, ignore_index=True)

        # 7. Merge q-values and PEP back into original df by ScanNr
        df = df.copy()
        df["_mokapot_idx"] = np.arange(len(df))

        merge_cols = psm_results[["ScanNr", "mokapot q-value", "mokapot PEP"]].copy()
        merge_cols = merge_cols.rename(
            columns={
                "mokapot q-value": "mokapot_qvalue",
                "mokapot PEP": "mokapot_PEP",
            }
        )

        df = df.merge(
            merge_cols,
            left_on="_mokapot_idx",
            right_on="ScanNr",
            how="left",
            suffixes=("", "_moka"),
        )

        # Clean up temporary columns
        temp_cols = [c for c in df.columns if c.startswith("_moka")]
        df.drop(
            columns=temp_cols + ["ScanNr", "ScanNr_moka"], errors="ignore", inplace=True
        )

        # Check for missing q-values after merge
        n_missing = df["mokapot_qvalue"].isna().sum()
        if n_missing > 0:
            logger.debug(
                f"[MOKAPOT] Warning: {n_missing} PSMs have no q-value after merge — check ScanNr alignment"
            )

        # 8. Report statistics
        target_df = df[df["PSM_Type"] == "Target"]
        fdr_01 = (target_df["mokapot_qvalue"] <= 0.01).sum()
        fdr_05 = (target_df["mokapot_qvalue"] <= 0.05).sum()
        total_targets = len(target_df)
        logger.debug(
            f"[MOKAPOT] Complete: {fdr_01} target PSMs at 1% FDR, {fdr_05} at 5% FDR (of {total_targets} total targets)"
        )

        return df
