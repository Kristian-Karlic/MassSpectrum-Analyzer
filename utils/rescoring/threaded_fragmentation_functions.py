import ast
import logging
import pandas as pd
from utils import calculate_fragment_ions, filter_ions, match_fragment_ions_fast
import math
from tqdm import tqdm
from concurrent.futures import as_completed, ProcessPoolExecutor
from collections import defaultdict
import numpy as np
import sys

# Ensure sys.stdout/stderr exist for tqdm
# In windowed .exe mode, these can be None, causing tqdm to crash
if sys.stdout is None:
    sys.stdout = open("NUL", "w")  # Windows null device
if sys.stderr is None:
    sys.stderr = open("NUL", "w")  # Windows null device

logger = logging.getLogger(__name__)


# Helper to safely create tqdm progress bars in frozen .exe
def safe_tqdm(*args, **kwargs):
    """
    Create tqdm progress bar, but disable it in frozen .exe if stdout/stderr are problematic.
    This prevents 'NoneType' object has no attribute 'write' errors.
    """
    try:
        # Check if running as frozen .exe
        is_frozen = getattr(sys, "frozen", False)

        # If frozen and file parameter not specified, disable tqdm
        if is_frozen and "file" not in kwargs:
            kwargs["disable"] = True

        return tqdm(*args, **kwargs)
    except Exception as e:
        logger.warning(f"tqdm initialization failed: {e}, disabling progress bar")
        kwargs["disable"] = True
        return tqdm(*args, **kwargs)


def process_theoretical_batch(
    batch_df,
    custom_ion_series=None,
    selected_ions=None,
    selected_internal_ions=None,
    max_neutral_losses=1,
    calculate_isotopes=True,
    isotope_max=4,
    glycan_composition_str=None,
    glycan_max_charge=None,
):
    """
    Worker function that each process calls.
    Must be defined at top level to be picklable.
    """

    # Set defaults if not provided
    if selected_ions is None:
        selected_ions = ["b", "y"]
    if selected_internal_ions is None:
        selected_internal_ions = []

    # Normalize custom ion series format in worker
    if custom_ion_series:
        normalized_custom = []
        for ion in custom_ion_series:
            # Handle both GUI format and normalized format
            normalized_custom.append(
                {
                    "base": ion.get("base", ion.get("Base Ion", "y")),
                    "name": ion.get("name", ion.get("Series Name", "Custom")),
                    "offset": float(ion.get("offset", ion.get("Mass Offset", 0))),
                    "color": ion.get("color", ion.get("Color", "#CCCCCC")),
                    "restriction": ion.get("restriction", ion.get("Restriction", "")),
                }
            )
        custom_ion_series = normalized_custom

    local_cache = {}
    results = {}
    batch_stats = {"processed": 0, "cache_hits": 0, "calc_errors": 0}

    col_idx = {col: pos for pos, col in enumerate(batch_df.columns, start=1)}
    idx_modified_peptide = col_idx.get("Modified Peptide")
    idx_charge = col_idx.get("Charge")
    idx_peptide = col_idx.get("Peptide")
    idx_parsed_modifications = col_idx.get("Parsed Modifications")
    idx_mod_nl_config = col_idx.get("Mod_NL_Config")

    def get_cache_key(modified_peptide, charge):
        return (modified_peptide, charge)

    def calculate_theoretical(
        peptide_sequence, modifications, max_charge, mod_nl_config=None
    ):
        """Calculate theoretical fragments for a given peptide and modifications."""
        try:
            fragment_ions_df_unfiltered = calculate_fragment_ions(
                peptide_sequence,
                modifications,
                max_charge,
                selected_ions,
                selected_internal_ions,
                custom_ion_series,
                max_neutral_losses,
                calculate_isotopes,
                isotope_max,
                mod_neutral_losses=mod_nl_config,
                glycan_composition_str=glycan_composition_str,
                glycan_max_charge=glycan_max_charge,
            )
            fragment_ions_df = filter_ions(fragment_ions_df_unfiltered)

            return list(
                zip(
                    fragment_ions_df["Theoretical Mass"],
                    fragment_ions_df["Ion Number"],
                    fragment_ions_df["Ion Type"],
                    fragment_ions_df["Fragment Sequence"],
                    fragment_ions_df["Neutral Loss"],
                    fragment_ions_df["Charge"],
                    fragment_ions_df["Isotope"],
                    fragment_ions_df["Color"],
                    fragment_ions_df["Base Type"],
                    fragment_ions_df["Modified Fragment"],
                )
            )
        except KeyError as e:
            logger.error(f"KeyError in calculate_theoretical: {e}")
            logger.error(f"Custom ion series: {custom_ion_series}")
            raise

    new_rows = []

    for row_tuple in batch_df.itertuples(index=True, name=None):
        idx = row_tuple[0]
        peptide_sequence = "Unknown"
        modified_peptide = "Unknown"
        try:
            modified_peptide = (
                row_tuple[idx_modified_peptide]
                if idx_modified_peptide is not None
                else None
            )
            max_charge = row_tuple[idx_charge] if idx_charge is not None else None
            cache_key = get_cache_key(modified_peptide, max_charge)
            peptide_sequence = row_tuple[idx_peptide] if idx_peptide is not None else ""

            raw_mods = (
                row_tuple[idx_parsed_modifications]
                if idx_parsed_modifications is not None
                else None
            )
            if raw_mods is None or (isinstance(raw_mods, float) and pd.isna(raw_mods)):
                modifications = None
            elif isinstance(raw_mods, str):
                modifications = ast.literal_eval(raw_mods) if raw_mods else None
            else:
                modifications = raw_mods

            # Modification-specific neutral loss config (precomputed)
            mod_nl_config = (
                row_tuple[idx_mod_nl_config] if idx_mod_nl_config is not None else None
            )
            if isinstance(mod_nl_config, float):  # NaN guard
                mod_nl_config = None

            if cache_key in local_cache:
                theoretical_fragments = local_cache[cache_key]
                batch_stats["cache_hits"] += 1
                results[idx] = theoretical_fragments
            else:
                theoretical_fragments = calculate_theoretical(
                    peptide_sequence, modifications, max_charge, mod_nl_config
                )
                local_cache[cache_key] = theoretical_fragments
                results[idx] = theoretical_fragments

            batch_stats["processed"] += 1

        except Exception as e:
            logger.debug(
                f"\n[Worker] Error calculating theoretical fragments for row {idx}: {e}"
            )
            logger.debug(f"[Worker] Peptide: {peptide_sequence}")
            logger.debug(f"[Worker] Modified: {modified_peptide}")
            import traceback

            traceback.print_exc()
            results[idx] = []
            batch_stats["calc_errors"] += 1

    # Debug output
    if batch_stats["cache_hits"] > 0 or batch_stats["calc_errors"] > 0:
        logger.debug(
            f"[Batch] Processed: {batch_stats['processed']}, Cache hits: {batch_stats['cache_hits']}, Errors: {batch_stats['calc_errors']}"
        )

    return results, batch_stats, new_rows


# ---------------------------------------------------------
# 2) Top-level worker function for matching
# ---------------------------------------------------------
def process_matching_batch(batch_df, diagnostic_ions, ppm_tolerance):
    """
    Worker function for matching fragments.
    Uses match_fragment_ions_fast for direct tuple-based matching.
    Theoretical fragments are already filtered in Phase 1, so no filter_ions needed here.
    """
    results = {}
    batch_stats = {"processed": 0, "match_errors": 0, "zero_matches": 0}

    # Convert diagnostic ion dicts to (name, mass, color) tuples if needed
    diag_tuples = None
    if diagnostic_ions:
        diag_tuples = []
        for d in diagnostic_ions:
            if isinstance(d, dict):
                diag_tuples.append((d["Name"], d["Mass"], d["Color"]))
            else:
                diag_tuples.append(d)
        if not diag_tuples:
            diag_tuples = None

    col_idx = {col: pos for pos, col in enumerate(batch_df.columns, start=1)}
    idx_theoretical = col_idx.get("Theoretical_Fragments")
    idx_mz = col_idx.get("mz")
    idx_intensity = col_idx.get("intensity")
    idx_peptide = col_idx.get("Peptide")

    for row_tuple in batch_df.itertuples(index=True, name=None):
        idx = row_tuple[0]
        peptide = "Unknown"
        try:
            theoretical_fragments = (
                row_tuple[idx_theoretical] if idx_theoretical is not None else None
            )
            mz_values = row_tuple[idx_mz] if idx_mz is not None else None
            intensity_values = (
                row_tuple[idx_intensity] if idx_intensity is not None else None
            )

            has_theoretical = (
                theoretical_fragments is not None and len(theoretical_fragments) > 0
            )
            has_experimental = mz_values is not None and len(mz_values) > 0

            if not has_theoretical or not has_experimental:
                results[idx] = None
                batch_stats["zero_matches"] += 1
                continue

            user_mz_values = list(zip(mz_values, intensity_values))

            # Match directly using fast path - tuples in, tuples out
            # Theoretical fragments are already filtered from Phase 1
            # Diagnostic ions are appended inside match_fragment_ions_fast
            matched_fragments = match_fragment_ions_fast(
                theoretical_fragments,
                user_mz_values,
                ppm_tolerance,
                diagnostic_ions=diag_tuples,
            )

            # Count actual matches (not "No Match")
            actual_matches = sum(
                1 for frag in matched_fragments if frag[2] != "No Match"
            )

            if actual_matches == 0:
                peptide = (
                    row_tuple[idx_peptide] if idx_peptide is not None else "Unknown"
                )
                logger.debug(
                    f"Row {idx} ({peptide}): {len(theoretical_fragments)} theoretical fragments, {len(mz_values)} experimental peaks, but NO MATCHES (PPM={ppm_tolerance})"
                )
                batch_stats["zero_matches"] += 1

            results[idx] = matched_fragments
            batch_stats["processed"] += 1

        except Exception as e:
            logger.debug(f"[Worker] Error matching fragments for row {idx}: {str(e)}")
            import traceback

            traceback.print_exc()
            batch_stats["match_errors"] += 1
            results[idx] = None

    if batch_stats["zero_matches"] > 0:
        logger.debug(
            f"[Batch Stats] Processed: {batch_stats['processed']}, Zero matches: {batch_stats['zero_matches']}, Errors: {batch_stats['match_errors']}"
        )

    return results, batch_stats


# ---------------------------------------------------------
# 4) Main multiprocess functions
# ---------------------------------------------------------


def process_fragments(
    filtered_df,
    custom_ion_series=None,
    diagnostic_ions=None,
    selected_ions=None,
    selected_internal_ions=None,
    ppm_tolerance=10,
    max_workers=8,
    batch_size=1000,
    max_neutral_losses=1,
    calculate_isotopes=True,
    isotope_max=4,
    progress_callback=None,
    cancel_event=None,
    glycan_composition_str=None,
    glycan_max_charge=None,
):
    """
    Process theoretical and matched fragments with REUSED process pool
    """
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor, as_completed

    logger.debug(
        f"\nStarting theoretical fragment calculation for {len(filtered_df)} PSMs"
    )
    logger.debug(f"Using {max_workers} workers with batch size {batch_size}")

    # Calculate LARGER batches to reduce process spawning
    # Aim for 4-8 batches per worker instead of 2
    optimal_batch_size = max(200, len(filtered_df) // (max_workers * 4))

    logger.debug(f"[OPTIMIZATION] Using batch size {optimal_batch_size}")

    n_total = len(filtered_df)

    # PHASE 1: Theoretical fragments with SINGLE reused pool
    logger.debug("\nPhase 1: Calculating theoretical fragments (multiprocessing)")
    if progress_callback:
        progress_callback(
            25, f"Calculating theoretical fragments for {n_total} PSMs..."
        )

    processed_df = filtered_df.copy()
    processed_df["Theoretical_Fragments"] = [[] for _ in range(n_total)]

    # Create batches for Phase 1
    batches_phase1 = np.array_split(
        processed_df, max(1, len(processed_df) // optimal_batch_size)
    )
    logger.debug(f"[OPTIMIZATION] Phase 1: {len(batches_phase1)} batches")

    total_cache_hits = 0
    total_calc_errors = 0
    done_p1 = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_theoretical_batch,
                batch,
                custom_ion_series,
                selected_ions,
                selected_internal_ions,
                max_neutral_losses,
                calculate_isotopes,
                isotope_max,
                glycan_composition_str,
                glycan_max_charge,
            ): i
            for i, batch in enumerate(batches_phase1)
        }

        cancelled = False
        with safe_tqdm(total=n_total, desc="Calculating theoretical fragments") as pbar:
            for future in as_completed(futures):
                try:
                    batch_results, batch_stats, _ = future.result()

                    for idx, theoretical_fragments in batch_results.items():
                        processed_df.at[idx, "Theoretical_Fragments"] = (
                            theoretical_fragments
                        )

                    total_cache_hits += batch_stats.get("cache_hits", 0)
                    total_calc_errors += batch_stats.get("calc_errors", 0)

                    done_p1 += len(batch_results)
                    pbar.update(len(batch_results))

                    if progress_callback:
                        pct = 25 + int(done_p1 / n_total * 20)
                        progress_callback(
                            pct,
                            f"Calculating theoretical fragments... {done_p1}/{n_total}",
                        )

                except Exception as e:
                    logger.error(f"Batch theoretical calculation failed: {e}")
                    import traceback

                    traceback.print_exc()

                if cancel_event is not None and cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    cancelled = True
                    break

        if cancelled:
            raise InterruptedError("Rescoring cancelled by user")

    logger.debug(
        f"Theoretical fragments calculated for {len(processed_df[processed_df['Theoretical_Fragments'].apply(len) > 0])} rows out of {len(processed_df)}"
    )
    if total_cache_hits > 0:
        logger.debug(
            f"[CACHE] Cache hits: {total_cache_hits}, Errors: {total_calc_errors}"
        )

    # PHASE 2: Fragment matching with REUSED pool
    logger.debug("\nPhase 2: Matching fragments (multiprocessing)")
    if progress_callback:
        progress_callback(45, f"Matching fragments for {n_total} PSMs...")

    processed_df["matched_fragments"] = [None for _ in range(n_total)]

    batches_phase2 = np.array_split(
        processed_df, max(1, len(processed_df) // optimal_batch_size)
    )
    logger.debug(f"[OPTIMIZATION] Phase 2: {len(batches_phase2)} batches")

    total_match_errors = 0
    total_zero_matches = 0
    done_p2 = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_matching_batch, batch, diagnostic_ions, ppm_tolerance
            ): i
            for i, batch in enumerate(batches_phase2)
        }

        cancelled = False
        with safe_tqdm(total=n_total, desc="Matching fragments") as pbar:
            for future in as_completed(futures):
                try:
                    batch_results, batch_stats = future.result()

                    for idx, matched_fragments in batch_results.items():
                        processed_df.at[idx, "matched_fragments"] = matched_fragments

                    total_match_errors += batch_stats.get("match_errors", 0)
                    total_zero_matches += batch_stats.get("zero_matches", 0)

                    done_p2 += len(batch_results)
                    pbar.update(len(batch_results))

                    if progress_callback:
                        pct = 45 + int(done_p2 / n_total * 20)
                        progress_callback(
                            pct, f"Matching fragments... {done_p2}/{n_total}"
                        )

                except Exception as e:
                    logger.error(f"Batch matching failed: {e}")
                    import traceback

                    traceback.print_exc()

                if cancel_event is not None and cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    cancelled = True
                    break

        if cancelled:
            raise InterruptedError("Rescoring cancelled by user")

    if total_match_errors > 0 or total_zero_matches > 0:
        logger.debug(
            f"[STATS] Match errors: {total_match_errors}, Zero matches: {total_zero_matches}"
        )

    return processed_df


def count_ions_batch(batch_df, ion_types_to_count, scoring_max_charge=0):
    """
    Worker function to count ions for a batch of rows.
    Works directly with matched_fragments tuples to avoid per-row DataFrame creation.
    Must be at top level for pickling.

    Tuple indices: 0=m/z, 1=intensity, 2=Matched, 3=error_ppm, 4=Ion Number,
                   5=Ion Type, 6=Fragment Sequence, 7=Neutral Loss, 8=Charge,
                   9=Isotope, 10=Color, 11=Base Type
    """
    import re

    # Precompiled patterns for ion type matching (compiled once per batch call)
    _RE_Z_NUM = re.compile(r"^z\d*")
    _RE_C_NUM = re.compile(r"^c\d*")
    _RE_D_VARIANT = re.compile(r"^d[ab]?\d*")
    _RE_W_VARIANT = re.compile(r"^w[ab]?\d*")
    _RE_SAT_NL_CACHE = {}

    def _re_sat_nl(base_letter, loss_part):
        key = (base_letter, loss_part)
        if key not in _RE_SAT_NL_CACHE:
            _RE_SAT_NL_CACHE[key] = re.compile(
                rf"^{base_letter}[ab]?{re.escape(loss_part)}$"
            )
        return _RE_SAT_NL_CACHE[key]

    _MOD_NL_PREFIXES = ("ModNL", "LabileLoss", "ModRM")

    def _is_mod_nl_label(nl_str):
        return any(nl_str.startswith(p) for p in _MOD_NL_PREFIXES)

    def _ion_type_matches_selected(ion_type_full, selected_ion_type):
        """Unified ion type matching method"""
        # Mod-NL: match any ion whose Neutral Loss is ModNL1/ModNL2/ModNL3/LabileLoss
        # This is handled specially below using the neutral_loss tuple field
        if selected_ion_type == "Mod-NL":
            return False  # handled via neutral_loss field below

        if selected_ion_type == "z+1":
            return "z+1" in ion_type_full.lower() or (
                ion_type_full.startswith("z") and "+1" in ion_type_full
            )
        if selected_ion_type == "c-1":
            return "c-1" in ion_type_full.lower() or (
                ion_type_full.startswith("c") and "-1" in ion_type_full
            )
        if selected_ion_type == "z":
            if "z+1" in ion_type_full.lower():
                return False
            return _RE_Z_NUM.match(ion_type_full) is not None
        if selected_ion_type == "c":
            if "c-1" in ion_type_full.lower():
                return False
            return _RE_C_NUM.match(ion_type_full) is not None

        # Handle d (include da, db variants)
        if selected_ion_type == "d":
            return _RE_D_VARIANT.match(ion_type_full) is not None

        # Handle w (include wa, wb variants)
        if selected_ion_type == "w":
            return _RE_W_VARIANT.match(ion_type_full) is not None

        # Handle satellite neutral losses: d-H2O matches da-H2O, db-H2O etc.
        if selected_ion_type.startswith(("d-", "w-")):
            base_letter = selected_ion_type[0]  # 'd' or 'w'
            loss_part = selected_ion_type[1:]  # '-H2O', '-NH3'
            return _re_sat_nl(base_letter, loss_part).match(ion_type_full) is not None
        if selected_ion_type.startswith("v-"):
            return ion_type_full == selected_ion_type

        base_type = ion_type_full.split("-")[0].split("+")[0]

        if selected_ion_type.startswith("int-"):
            if base_type.startswith("int-") and base_type[4:] == selected_ion_type[4:]:
                return True
        elif "-" in selected_ion_type and selected_ion_type not in ["z+1", "c-1"]:
            if (
                selected_ion_type in ion_type_full
                or base_type == selected_ion_type.split("-")[0]
            ):
                return True
        elif selected_ion_type in ["b", "y", "a", "x", "MH", "d", "v", "w"]:
            if base_type == selected_ion_type:
                return True
        else:
            if selected_ion_type in ion_type_full:
                return True
        return False

    results = {}

    # Precompute mod_nl_parts lookup for all ion types (None if not a mod-NL type)
    _mod_nl_parts_lookup = {}
    for _it in ion_types_to_count:
        if "-" in _it:
            _prefix = _it.split("-", 1)[0]
            if _is_mod_nl_label(_prefix):
                _mod_nl_parts_lookup[_it] = (_prefix, _it.split("-", 1)[1])
            else:
                _mod_nl_parts_lookup[_it] = None
        else:
            _mod_nl_parts_lookup[_it] = None

    col_idx = {col: pos for pos, col in enumerate(batch_df.columns, start=1)}
    idx_matched_fragments = col_idx.get("matched_fragments")
    idx_peptide = col_idx.get("Peptide")

    for row_tuple in batch_df.itertuples(index=True, name=None):
        idx = row_tuple[0]
        matched_fragments = (
            row_tuple[idx_matched_fragments]
            if idx_matched_fragments is not None
            else None
        )

        ion_counts = {}
        unique_counts = {}

        if matched_fragments is None or len(matched_fragments) == 0:
            for ion_type in ion_types_to_count:
                ion_counts[ion_type] = 0
                unique_counts[ion_type] = 0
            results[idx] = (ion_counts, unique_counts, {}, 0, 0, 0, 0, {})
            continue

        try:
            # Pre-filter matched monoisotopic peaks directly from tuples
            # Only keep: matched (not "No Match") AND isotope == 0
            filtered = []
            for frag in matched_fragments:
                matched_status = frag[2]
                if matched_status is None or matched_status == "No Match":
                    continue
                try:
                    isotope = int(float(frag[9]))
                except (ValueError, TypeError):
                    isotope = 0
                if isotope == 0:
                    if scoring_max_charge > 0:
                        try:
                            charge = int(float(frag[8]))
                        except (ValueError, TypeError):
                            charge = 1
                        if charge > scoring_max_charge:
                            continue
                    filtered.append(frag)

            # Single pass: build ion type counts, base type maps, and backbone sets
            ion_count_map = {it: 0 for it in ion_types_to_count}
            unique_pos_map = {it: set() for it in ion_types_to_count}
            base_type_positions = {}
            base_type_total_counts = {}
            bonds_overall = set()
            bonds_intact = set()
            bonds_partial = set()

            _INTACT_EXCLUDE = frozenset("*^~")
            _PARTIAL_EXCLUDE = frozenset("~")

            for frag in filtered:
                ion_type_full = str(frag[5]) if frag[5] is not None else ""
                nl = str(frag[7]) if frag[7] is not None else ""
                bt = str(frag[11]).strip() if frag[11] is not None else ""

                # --- Ion type counting ---
                for it in ion_types_to_count:
                    if it == "Mod-NL":
                        if not _is_mod_nl_label(nl):
                            continue
                    elif _mod_nl_parts_lookup[it] is not None:
                        mnl_prefix, mnl_base = _mod_nl_parts_lookup[it]
                        if nl != mnl_prefix:
                            continue
                        frag_bt = (
                            str(frag[11]).strip()
                            if len(frag) > 11 and frag[11]
                            else str(frag[5]).strip()
                        )
                        if frag_bt != mnl_base:
                            continue
                    else:
                        if not _ion_type_matches_selected(ion_type_full, it):
                            continue

                    ion_count_map[it] += 1
                    try:
                        ion_num = int(frag[4])
                        unique_pos_map[it].add(ion_num)
                    except (ValueError, TypeError):
                        pass

                # --- Base type tracking ---
                if bt and bt not in ("None", "nan", ""):
                    base_type_total_counts[bt] = base_type_total_counts.get(bt, 0) + 1
                    try:
                        ion_number = int(frag[4])
                        if bt not in base_type_positions:
                            base_type_positions[bt] = set()
                        base_type_positions[bt].add(ion_number)
                    except (ValueError, TypeError):
                        pass

                # --- Backbone coverage ---
                if bt and bt not in ("None", "nan", ""):
                    try:
                        ion_num = int(frag[4])
                        if bt in ("y", "z", "x"):
                            bond_key = ("yzx", ion_num)
                        elif bt in ("b", "c", "a"):
                            bond_key = ("bca", ion_num)
                        else:
                            bond_key = None

                        if bond_key is not None:
                            bonds_overall.add(bond_key)
                            if not any(ch in ion_type_full for ch in _INTACT_EXCLUDE):
                                bonds_intact.add(bond_key)
                            if not any(ch in ion_type_full for ch in _PARTIAL_EXCLUDE):
                                bonds_partial.add(bond_key)
                    except (ValueError, TypeError):
                        pass

            # Build final dicts
            ion_counts = {it: ion_count_map[it] for it in ion_types_to_count}
            unique_counts = {it: len(unique_pos_map[it]) for it in ion_types_to_count}
            base_type_coverage = {
                bt: len(positions) for bt, positions in base_type_positions.items()
            }
            peptide = row_tuple[idx_peptide] if idx_peptide is not None else ""
            if not isinstance(peptide, str):
                if peptide is None or (isinstance(peptide, float) and pd.isna(peptide)):
                    peptide = ""
                else:
                    peptide = str(peptide)
            potential_fragments = (len(peptide) * 2) - 2 if len(peptide) >= 2 else 0
            backbone_cov_overall = len(bonds_overall)
            backbone_cov_intact = len(bonds_intact)
            backbone_cov_partial = len(bonds_partial)

        except Exception as e:
            logger.error(f"Error processing row {idx}: {e}")
            for ion_type in ion_types_to_count:
                ion_counts[ion_type] = 0
                unique_counts[ion_type] = 0
            base_type_coverage = {}
            base_type_total_counts = {}
            potential_fragments = 0
            backbone_cov_overall = 0
            backbone_cov_intact = 0
            backbone_cov_partial = 0

        results[idx] = (
            ion_counts,
            unique_counts,
            base_type_coverage,
            potential_fragments,
            backbone_cov_overall,
            backbone_cov_intact,
            backbone_cov_partial,
            base_type_total_counts,
        )

    return results


def count_ion_types_parallel(
    merged_df,
    ion_types_to_count=["b", "y"],
    max_workers=8,
    batch_size=1000,
    scoring_max_charge=0,
):
    """
    Parallelized ion counting with optimized batch sizes
    """
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor, as_completed

    logger.debug(
        f"Starting parallel ion counting for {len(merged_df)} rows with {max_workers} workers"
    )
    logger.debug(f"Ion types to count: {ion_types_to_count}")

    # CHANGED: Use larger batches (aim for 4-8 batches per worker)
    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))

    logger.debug(
        f"[OPTIMIZATION] Using {len(batches)} batches (batch size ~{optimal_batch_size})"
    )

    final_results = {}

    # CHANGED: Use single context manager for entire operation
    with safe_tqdm(total=len(merged_df), desc="Counting ion types (parallel)") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all batches to reused pool
            futures = {
                executor.submit(
                    count_ions_batch, batch, ion_types_to_count, scoring_max_charge
                ): i
                for i, batch in enumerate(batches)
            }

            # Collect results
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    logger.error(f"Batch counting failed: {e}")

    # --- Build column arrays from final_results in ONE pass ---
    all_base_types = set()
    for idx, (
        _,
        _,
        base_type_coverage,
        _,
        _,
        _,
        _,
        base_type_total_counts,
    ) in final_results.items():
        all_base_types.update(base_type_coverage.keys())

    # Initialize coverage/total columns
    for base_type in sorted(all_base_types):
        merged_df[f"sequence_coverage_count_{base_type}"] = 0
        merged_df[f"total_{base_type}_count"] = 0

    # Ion count columns
    ion_count_arrays = {
        it: np.zeros(len(merged_df), dtype=np.int64) for it in ion_types_to_count
    }
    ion_unique_arrays = {
        it: np.zeros(len(merged_df), dtype=np.int64) for it in ion_types_to_count
    }
    cov_arrays = {bt: np.zeros(len(merged_df), dtype=np.int64) for bt in all_base_types}
    total_arrays = {
        bt: np.zeros(len(merged_df), dtype=np.int64) for bt in all_base_types
    }
    pot_arr = np.zeros(len(merged_df), dtype=np.int64)
    bb_overall_arr = np.zeros(len(merged_df), dtype=np.int64)
    bb_intact_arr = np.zeros(len(merged_df), dtype=np.int64)
    bb_partial_arr = np.zeros(len(merged_df), dtype=np.int64)

    # Build integer position lookup for index → array position
    idx_to_pos = {idx: pos for pos, idx in enumerate(merged_df.index)}

    for idx, (
        ion_counts,
        unique_counts,
        base_type_coverage,
        potential_fragments,
        backbone_cov_overall,
        backbone_cov_intact,
        backbone_cov_partial,
        base_type_total_counts,
    ) in final_results.items():
        pos = idx_to_pos.get(idx)
        if pos is None:
            continue
        for it in ion_types_to_count:
            ion_count_arrays[it][pos] = ion_counts.get(it, 0)
            ion_unique_arrays[it][pos] = unique_counts.get(it, 0)
        for bt, cnt in base_type_coverage.items():
            if bt in cov_arrays:
                cov_arrays[bt][pos] = cnt
        for bt, cnt in base_type_total_counts.items():
            if bt in total_arrays:
                total_arrays[bt][pos] = cnt
        pot_arr[pos] = potential_fragments
        bb_overall_arr[pos] = backbone_cov_overall
        bb_intact_arr[pos] = backbone_cov_intact
        bb_partial_arr[pos] = backbone_cov_partial

    # Bulk column assignment
    for it in ion_types_to_count:
        merged_df[f"{it}_count"] = ion_count_arrays[it]
        merged_df[f"{it}_unique_count"] = ion_unique_arrays[it]
    for bt in sorted(all_base_types):
        merged_df[f"sequence_coverage_count_{bt}"] = cov_arrays[bt]
        merged_df[f"total_{bt}_count"] = total_arrays[bt]
    merged_df["backbone_coverage_potential"] = pot_arr
    merged_df["backbone_coverage_overall"] = bb_overall_arr
    merged_df["backbone_coverage_intact"] = bb_intact_arr
    merged_df["backbone_coverage_partial"] = bb_partial_arr

    logger.debug("Ion counting complete")

    # Print statistics
    for ion_type in ion_types_to_count:
        mean_count = merged_df[f"{ion_type}_unique_count"].mean()
        max_count = merged_df[f"{ion_type}_unique_count"].max()
        logger.debug(f"{ion_type}: Mean={mean_count:.2f}, Max={max_count}")

    # Print sequence coverage statistics
    for base_type in sorted(all_base_types):
        col = f"sequence_coverage_count_{base_type}"
        mean_cov = merged_df[col].mean()
        max_cov = merged_df[col].max()
        logger.debug(
            f"Sequence coverage {base_type}: Mean={mean_cov:.2f}, Max={max_cov}"
        )

    # Print total base type count statistics
    for base_type in sorted(all_base_types):
        col = f"total_{base_type}_count"
        mean_ct = merged_df[col].mean()
        max_ct = merged_df[col].max()
        logger.debug(f"Total {base_type} count: Mean={mean_ct:.2f}, Max={max_ct}")

    # Print backbone coverage statistics
    for cov_type in ["overall", "intact", "partial"]:
        col = f"backbone_coverage_{cov_type}"
        mean_cov = merged_df[col].mean()
        max_cov = merged_df[col].max()
        logger.debug(
            f"Backbone coverage {cov_type}: Mean={mean_cov:.2f}, Max={max_cov}"
        )

    return merged_df


def _compute_ratios_for_ion_type(
    matched_fragments,
    ion_type,
    charge_range,
    match_func,
    numerator_isotope=0,
    denominator_isotope=-1,
):
    """
    Compute isotope ratios per position per charge for a given ion type.

    For z+1 migration: numerator_isotope=0, denominator_isotope=-1  (iso 0 / iso -1)
    For c migration:   numerator_isotope=-1, denominator_isotope=0  (iso -1 / iso 0)

    When denominator is 0 but numerator > 0: ratio = 5.0 (complete transfer).
    When neither isotope matched: ratio = 0.

    Returns: dict[charge] -> dict[position] -> ratio_value
    """
    needed_isotopes = (numerator_isotope, denominator_isotope)

    # Collect intensities grouped by (charge, position, isotope)
    intensity_map = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0])
    )  # (charge, position) -> {isotope: [sum, count]}

    for frag in matched_fragments:
        matched_status = frag[2]
        if matched_status is None or matched_status == "No Match":
            continue

        ion_type_full = str(frag[5])
        if not match_func(ion_type_full, ion_type):
            continue

        try:
            charge = int(frag[8])
        except (ValueError, TypeError):
            continue

        if charge not in charge_range:
            continue

        try:
            position = int(frag[4])
        except (ValueError, TypeError):
            continue

        try:
            isotope = int(float(frag[9]))
        except (ValueError, TypeError):
            isotope = 0

        if isotope not in needed_isotopes:
            continue

        try:
            intensity = float(frag[1])
        except (ValueError, TypeError):
            continue

        agg = intensity_map[(charge, position)][isotope]
        agg[0] += intensity
        agg[1] += 1

    # Compute ratios: numerator_isotope / denominator_isotope
    ratios_by_charge = {}

    for (charge, position), isotope_data in intensity_map.items():
        if charge not in ratios_by_charge:
            ratios_by_charge[charge] = {}

        has_num = numerator_isotope in isotope_data
        has_denom = denominator_isotope in isotope_data

        if has_num and has_denom:
            num_sum, num_count = isotope_data[numerator_isotope]
            denom_sum, denom_count = isotope_data[denominator_isotope]
            if num_count == 0 or denom_count == 0:
                continue
            num_val = num_sum / num_count
            denom_val = denom_sum / denom_count

            if denom_val > 0:
                ratios_by_charge[charge][position] = num_val / denom_val
            elif num_val > 0:
                ratios_by_charge[charge][position] = 5.0
            else:
                ratios_by_charge[charge][position] = 0
        elif has_num and not has_denom:
            num_sum, num_count = isotope_data[numerator_isotope]
            if num_count == 0:
                continue
            num_val = num_sum / num_count
            ratios_by_charge[charge][position] = 5.0 if num_val > 0 else 0
        elif has_denom and not has_num:
            ratios_by_charge[charge][position] = 0

    return ratios_by_charge


def compute_migration_ratios_batch(
    batch_df, z_migration_enabled, c_migration_enabled, charge_range
):
    """
    Worker function to compute hydrogen migration ratios for a batch of PSMs.
    Must be at top level for pickling by ProcessPoolExecutor.

    For z migration: z+1 ion type, ratio = isotope(0) / isotope(-1)
    For c migration: c ion type (NOT c-1), ratio = isotope(-1) / isotope(0)

    Returns dict[idx] -> (z_migration_str, c_migration_str)
    """
    import re

    def _ion_type_matches_for_migration(ion_type_full, migration_type):
        """Check if an ion type string matches z+1 or c for migration."""
        if migration_type == "z+1":
            return "z+1" in ion_type_full.lower() or (
                ion_type_full.startswith("z") and "+1" in ion_type_full
            )
        elif migration_type == "c":
            if "c-1" in ion_type_full.lower():
                return False
            base_match = re.match(r"^c\d*", ion_type_full)
            return base_match is not None
        return False

    def _format_migration_string(ratios_by_charge, peptide_length, charge_range):
        """
        Format migration ratios into output string.
        Output: "(r1,r2,...,rN)1,(r1,r2,...,rN)2"
        N = peptide_length - 1
        """
        num_positions = peptide_length - 1
        parts = []

        for charge in charge_range:
            position_ratios = []
            for pos in range(1, num_positions + 1):
                ratio = ratios_by_charge.get(charge, {}).get(pos, 0)
                if ratio == 0:
                    position_ratios.append("0")
                elif ratio == 5.0:
                    position_ratios.append("5")
                else:
                    position_ratios.append(f"{ratio:.4f}".rstrip("0").rstrip("."))

            ratio_str = ",".join(position_ratios)
            parts.append(f"({ratio_str}){charge}")

        return ",".join(parts)

    results = {}

    col_idx = {col: pos for pos, col in enumerate(batch_df.columns, start=1)}
    idx_matched_fragments = col_idx.get("matched_fragments")
    idx_peptide = col_idx.get("Peptide")

    for row_tuple in batch_df.itertuples(index=True, name=None):
        idx = row_tuple[0]
        matched_fragments = (
            row_tuple[idx_matched_fragments]
            if idx_matched_fragments is not None
            else None
        )
        peptide = row_tuple[idx_peptide] if idx_peptide is not None else ""
        if not isinstance(peptide, str):
            if peptide is None or (isinstance(peptide, float) and pd.isna(peptide)):
                peptide = ""
            else:
                peptide = str(peptide)
        peptide_length = len(peptide) if peptide else 0

        z_migration_str = ""
        c_migration_str = ""

        if not matched_fragments or peptide_length < 2:
            results[idx] = (z_migration_str, c_migration_str)
            continue

        if z_migration_enabled:
            z_ratios = _compute_ratios_for_ion_type(
                matched_fragments,
                "z+1",
                charge_range,
                _ion_type_matches_for_migration,
                numerator_isotope=0,
                denominator_isotope=-1,
            )
            z_migration_str = _format_migration_string(
                z_ratios, peptide_length, charge_range
            )

        if c_migration_enabled:
            c_ratios = _compute_ratios_for_ion_type(
                matched_fragments,
                "c",
                charge_range,
                _ion_type_matches_for_migration,
                numerator_isotope=-1,
                denominator_isotope=0,
            )
            c_migration_str = _format_migration_string(
                c_ratios, peptide_length, charge_range
            )

        results[idx] = (z_migration_str, c_migration_str)

    return results


def calculate_migration_ratios_parallel(
    merged_df,
    z_migration_enabled=False,
    c_migration_enabled=False,
    charge_range=None,
    max_workers=8,
    batch_size=1000,
):
    """
    Parallelized hydrogen migration ratio computation.

    For z+1: computes isotope(0)/isotope(-1) ratios per backbone position.
    For c: computes isotope(-1)/isotope(0) ratios per backbone position.
    Results stored as formatted strings in z_migration and c_migration columns.
    """
    if charge_range is None:
        charge_range = [1, 2, 3]

    logger.debug(
        f"[MIGRATION] Starting parallel migration calculation for {len(merged_df)} rows"
    )
    logger.debug(
        f"[MIGRATION] z+1 enabled: {z_migration_enabled}, c enabled: {c_migration_enabled}"
    )
    logger.debug(f"[MIGRATION] Charge range: {charge_range}")

    if z_migration_enabled:
        merged_df["z_migration"] = ""
    if c_migration_enabled:
        merged_df["c_migration"] = ""

    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))

    logger.debug(
        f"[MIGRATION] Using {len(batches)} batches (batch size ~{optimal_batch_size})"
    )

    final_results = {}

    with safe_tqdm(total=len(merged_df), desc="Computing migration ratios") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    compute_migration_ratios_batch,
                    batch,
                    z_migration_enabled,
                    c_migration_enabled,
                    charge_range,
                ): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    logger.error(f"Migration batch failed: {e}")

    for idx, (z_str, c_str) in final_results.items():
        if z_migration_enabled:
            merged_df.at[idx, "z_migration"] = z_str
        if c_migration_enabled:
            merged_df.at[idx, "c_migration"] = c_str

    logger.debug("[MIGRATION] Migration calculation complete")

    return merged_df


# ---------------------------------------------------------
# Parallelized score calculation (Annotated TIC% + Rescore)
# ---------------------------------------------------------
def compute_scores_batch(
    batch_df,
    ion_types_to_use,
    scoring_methods=None,
    ppm_tolerance=10.0,
    scoring_max_charge=0,
    scoring_nl_in_count=False,
):
    """
    Worker function to compute Annotated TIC%, Rescore, and optional scoring
    metrics (consecutive series, complementary pairs) for a batch.
    Works directly with matched_fragments tuples to avoid per-row DataFrame creation.
    Must be at top level for pickling by ProcessPoolExecutor.

    Tuple indices: 0=m/z, 1=intensity, 2=Matched, 3=error_ppm, 4=Ion Number,
                   5=Ion Type, 6=Fragment Sequence, 7=Neutral Loss, 8=Charge,
                   9=Isotope, 10=Color, 11=Base Type

    Returns dict[idx] -> (annotated_pct, rescore,
                          consec_longest, consec_detail, comp_pairs, comp_possible)
    """
    if scoring_methods is None:
        scoring_methods = {}

    calc_consecutive = scoring_methods.get("consecutive_series", False)
    calc_complementary = scoring_methods.get("complementary_pairs", False)

    n_term_types = {"b", "a", "c", "c-1", "d", "da", "db"}
    c_term_types = {"y", "x", "z", "z+1", "w", "wa", "wb", "v"}

    # Precomputed factorials for fast lookup (covers up to 200 unique ions per type)
    _FACTORIAL_CACHE = [1] * 201
    for _fi in range(1, 201):
        _FACTORIAL_CACHE[_fi] = _FACTORIAL_CACHE[_fi - 1] * _fi

    results = {}

    col_idx = {col: pos for pos, col in enumerate(batch_df.columns, start=1)}
    idx_matched_fragments = col_idx.get("matched_fragments")
    idx_intensity = col_idx.get("intensity")
    idx_peptide = col_idx.get("Peptide")

    for row_tuple in batch_df.itertuples(index=True, name=None):
        idx = row_tuple[0]
        matched_fragments = (
            row_tuple[idx_matched_fragments]
            if idx_matched_fragments is not None
            else None
        )
        intensity_values = row_tuple[idx_intensity] if idx_intensity is not None else []

        annotated_pct = 0.0
        rescore = 0.0
        consec_longest = 0
        consec_detail = ""
        comp_pairs = 0
        comp_possible = 0
        avg_error = 0.0

        if (
            matched_fragments is None
            or len(matched_fragments) == 0
            or intensity_values is None
            or len(intensity_values) == 0
        ):
            results[idx] = (
                annotated_pct,
                rescore,
                consec_longest,
                consec_detail,
                comp_pairs,
                comp_possible,
                avg_error,
            )
            continue

        total_experimental_intensity = sum(intensity_values)
        if total_experimental_intensity == 0:
            results[idx] = (
                annotated_pct,
                rescore,
                consec_longest,
                consec_detail,
                comp_pairs,
                comp_possible,
                avg_error,
            )
            continue

        # Get peptide length for metrics that need it
        peptide = row_tuple[idx_peptide] if idx_peptide is not None else ""
        if not isinstance(peptide, str):
            if peptide is None or (isinstance(peptide, float) and pd.isna(peptide)):
                peptide = ""
            else:
                peptide = str(peptide)
        pep_len = len(peptide) if peptide else 0

        # Single pass over matched fragments for all calculations
        annotated_intensity = 0.0
        ion_type_positions = {ion_type: set() for ion_type in ion_types_to_use}
        intensity_sum = 0.0

        # Additional tracking for optional metrics
        mono_positions_by_base = {}  # base_type -> set of ion_numbers (for consecutive)
        n_positions = set()  # N-terminal ion numbers (for complementary)
        c_positions = set()  # C-terminal ion numbers (for complementary)
        total_mono_matched = 0  # total monoisotopic matched count
        ppm_error_sum = 0.0  # sum of absolute ppm errors for matched ions
        ppm_error_count = 0  # count of matched ions with valid ppm errors

        for frag in matched_fragments:
            matched_status = frag[2]
            if matched_status is None or matched_status == "No Match":
                continue

            try:
                intensity = float(frag[1])
            except (ValueError, TypeError):
                continue

            try:
                isotope = int(float(frag[9]))
            except (ValueError, TypeError):
                isotope = 0

            # Annotated TIC: sum ALL matched peak intensities (all isotopes)
            annotated_intensity += intensity

            # Accumulate ppm errors for Avg_error calculation
            try:
                ppm_err = abs(float(frag[3]))
                ppm_error_sum += ppm_err
                ppm_error_count += 1
            except (ValueError, TypeError):
                pass

            # Extract base type and ion number for scoring
            base_type = str(frag[11]).strip() if frag[11] is not None else ""

            # MH ions are never used in scoring
            if base_type == "MH":
                continue

            try:
                ion_number = int(frag[4])
            except (ValueError, TypeError):
                ion_number = None

            # Accumulate intensity for scoring (all isotopes), excluding MH
            if base_type in ion_types_to_use and ion_number is not None:
                intensity_sum += intensity

            # Everything below is monoisotopic only (ion counting, consecutive, complementary)
            if isotope != 0:
                continue

            # ── Complementary pairs: ALL N/C-term ions, no charge or type filter ──
            # Runs before any restriction so any combination (y/b, y/a, c/z, b/z, etc.)
            # at a backbone position is captured.
            if calc_complementary and pep_len >= 2 and ion_number is not None:
                ion_type_full = str(frag[5]).lower() if frag[5] else ""
                if "z+1" in ion_type_full:
                    effective = "z+1"
                elif "c-1" in ion_type_full:
                    effective = "c-1"
                else:
                    effective = base_type
                if effective in n_term_types:
                    n_positions.add(ion_number)
                elif effective in c_term_types:
                    c_positions.add(ion_number)

            # ── Consecutive series: selected types only, no charge filter ──
            if (
                calc_consecutive
                and ion_number is not None
                and base_type in ion_types_to_use
            ):
                mono_positions_by_base.setdefault(base_type, set()).add(ion_number)

            # ── X!Tandem: charge filter applies only here ──
            if scoring_max_charge > 0:
                try:
                    charge = int(float(frag[8]))
                except (ValueError, TypeError):
                    charge = 1
                if charge > scoring_max_charge:
                    continue

            # X!Tandem: only count ions in the selected types
            if base_type not in ion_types_to_use:
                continue

            if ion_number is not None:
                # Check if this is a standard neutral loss (H2O, NH3, etc.)
                nl = str(frag[7]) if frag[7] is not None else ""
                is_standard_nl = (
                    nl != ""
                    and nl != "None"
                    and nl != "nan"
                    and not nl.startswith(("ModNL", "LabileLoss", "ModRM"))
                )

                # Standard NL ions only count toward positions if setting enabled
                if not is_standard_nl or scoring_nl_in_count:
                    ion_type_positions[base_type].add(ion_number)
                total_mono_matched += 1

        # Annotated TIC %
        if annotated_intensity > 0:
            annotated_pct = (annotated_intensity / total_experimental_intensity) * 100.0

        # Rescore: HS = ln(∑Ii * Nb! * Ny!)
        factorial_product = 1
        for ion_type in ion_types_to_use:
            unique_count = len(ion_type_positions[ion_type])
            if unique_count > 0:
                factorial_product *= _FACTORIAL_CACHE[min(unique_count, 200)]

        if intensity_sum > 0 and factorial_product > 0:
            rescore = math.log(intensity_sum * factorial_product)

        # --- Optional: Consecutive Ion Series ---
        if calc_consecutive and mono_positions_by_base:
            try:
                overall_longest = 0
                per_type_runs = {}
                for bt, positions in mono_positions_by_base.items():
                    sorted_pos = sorted(positions)
                    if not sorted_pos:
                        continue
                    max_run = current_run = 1
                    for i in range(1, len(sorted_pos)):
                        if sorted_pos[i] == sorted_pos[i - 1] + 1:
                            current_run += 1
                            if current_run > max_run:
                                max_run = current_run
                        else:
                            current_run = 1
                    per_type_runs[bt] = max_run
                    if max_run > overall_longest:
                        overall_longest = max_run
                consec_longest = overall_longest
                consec_detail = ", ".join(
                    f"{k}:{v}" for k, v in sorted(per_type_runs.items()) if v > 0
                )
            except Exception:
                consec_longest = 0
                consec_detail = ""

        # --- Optional: Complementary Pairs ---
        if calc_complementary and pep_len >= 2:
            try:
                paired = 0
                possible = pep_len - 1
                for pos in n_positions:
                    complement = pep_len - pos
                    if complement in c_positions:
                        paired += 1
                comp_pairs = paired
                comp_possible = possible
            except Exception:
                comp_pairs = 0
                comp_possible = max(pep_len - 1, 0)

        # --- Average absolute ppm error ---
        if ppm_error_count > 0:
            avg_error = round(ppm_error_sum / ppm_error_count, 4)

        results[idx] = (
            annotated_pct,
            rescore,
            consec_longest,
            consec_detail,
            comp_pairs,
            comp_possible,
            avg_error,
        )

    return results


def calculate_scores_parallel(
    merged_df,
    ion_types_to_use=None,
    max_workers=8,
    scoring_methods=None,
    ppm_tolerance=10.0,
    scoring_max_charge=0,
    scoring_nl_in_count=False,
):
    """
    Parallelized score calculation combining Annotated TIC%, Rescore,
    and optional metrics (consecutive, complementary).
    Uses compute_scores_batch with ProcessPoolExecutor.
    """
    if ion_types_to_use is None:
        ion_types_to_use = ["b", "y"]
    if scoring_methods is None:
        scoring_methods = {}

    if merged_df.empty:
        merged_df["Annotated_TIC_%"] = 0.0
        merged_df["Rescore"] = 0.0
        return merged_df

    any_optional = any(
        scoring_methods.get(k) for k in ("consecutive_series", "complementary_pairs")
    )

    logger.debug(
        f"Starting parallel score calculation for {len(merged_df)} rows with {max_workers} workers"
    )
    logger.debug(f"Ion types for scoring: {ion_types_to_use}")
    if any_optional:
        enabled = [
            k
            for k in ("consecutive_series", "complementary_pairs")
            if scoring_methods.get(k)
        ]
        logger.debug(f"Optional scoring metrics enabled: {enabled}")

    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))

    logger.debug(
        f"[OPTIMIZATION] Score calculation: {len(batches)} batches (batch size ~{optimal_batch_size})"
    )

    final_results = {}

    with safe_tqdm(total=len(merged_df), desc="Calculating scores (parallel)") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    compute_scores_batch,
                    batch,
                    ion_types_to_use,
                    scoring_methods,
                    ppm_tolerance,
                    scoring_max_charge,
                    scoring_nl_in_count,
                ): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    logger.error(f"Score calculation batch failed: {e}")

    # Assign results back to dataframe
    annotated_vals = []
    rescore_vals = []
    consec_longest_vals = []
    consec_detail_vals = []
    comp_pairs_vals = []
    avg_error_vals = []

    for idx in merged_df.index:
        if idx in final_results:
            (
                annotated_pct,
                rescore,
                consec_longest,
                consec_detail,
                comp_pairs,
                comp_possible,
                avg_error,
            ) = final_results[idx]
            annotated_vals.append(annotated_pct)
            rescore_vals.append(rescore)
            consec_longest_vals.append(consec_longest)
            consec_detail_vals.append(consec_detail)
            comp_pairs_vals.append(
                f"{comp_pairs}/{comp_possible}" if comp_possible > 0 else "0/0"
            )
            avg_error_vals.append(avg_error)
        else:
            annotated_vals.append(0.0)
            rescore_vals.append(0.0)
            consec_longest_vals.append(0)
            consec_detail_vals.append("")
            comp_pairs_vals.append("0/0")
            avg_error_vals.append(0.0)

    merged_df["Annotated_TIC_%"] = annotated_vals
    merged_df["Rescore"] = rescore_vals
    merged_df["Avg_error"] = avg_error_vals

    # Only add optional metric columns when that metric was enabled
    if scoring_methods.get("consecutive_series"):
        merged_df["Consecutive_Series_Longest"] = consec_longest_vals
        merged_df["Consecutive_Series_Detail"] = consec_detail_vals
    if scoring_methods.get("complementary_pairs"):
        merged_df["Complementary_Pairs"] = comp_pairs_vals

    logger.debug(
        f"Score calculation complete. Annotated TIC: Mean={np.mean(annotated_vals):.2f}%, Rescore: Mean={np.mean(rescore_vals):.3f}, Max={np.max(rescore_vals):.3f}"
    )

    return merged_df
