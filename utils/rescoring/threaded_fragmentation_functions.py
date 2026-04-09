import ast
import pandas as pd
from utils import calculate_fragment_ions, filter_ions, match_fragment_ions, match_fragment_ions_fast
import math
from math import factorial
from tqdm import tqdm
from concurrent.futures import  as_completed, ProcessPoolExecutor
import numpy as np
import sys

# Ensure sys.stdout/stderr exist for tqdm
# In windowed .exe mode, these can be None, causing tqdm to crash
if sys.stdout is None:
    sys.stdout = open('NUL', 'w')  # Windows null device
if sys.stderr is None:
    sys.stderr = open('NUL', 'w')  # Windows null device

# Helper to safely create tqdm progress bars in frozen .exe
def safe_tqdm(*args, **kwargs):
    """
    Create tqdm progress bar, but disable it in frozen .exe if stdout/stderr are problematic.
    This prevents 'NoneType' object has no attribute 'write' errors.
    """
    try:
        # Check if running as frozen .exe
        is_frozen = getattr(sys, 'frozen', False)
        
        # If frozen and file parameter not specified, disable tqdm
        if is_frozen and 'file' not in kwargs:
            kwargs['disable'] = True
            
        return tqdm(*args, **kwargs)
    except Exception as e:
        print(f"[WARNING] tqdm initialization failed: {e}, disabling progress bar")
        kwargs['disable'] = True
        return tqdm(*args, **kwargs)

def process_theoretical_batch(batch_df, custom_ion_series=None, selected_ions=None,
                              selected_internal_ions=None, max_neutral_losses=1,
                              calculate_isotopes=True):
    """
    Worker function that each process calls.
    Must be defined at top level to be picklable.
    """
    
    # Set defaults if not provided
    if selected_ions is None:
        selected_ions = ['b', 'y']
    if selected_internal_ions is None:
        selected_internal_ions = []
    
    # Normalize custom ion series format in worker
    if custom_ion_series:
        normalized_custom = []
        for ion in custom_ion_series:
            # Handle both GUI format and normalized format
            normalized_custom.append({
                'base': ion.get('base', ion.get('Base Ion', 'y')),
                'name': ion.get('name', ion.get('Series Name', 'Custom')),
                'offset': float(ion.get('offset', ion.get('Mass Offset', 0))),
                'color': ion.get('color', ion.get('Color', '#CCCCCC')),
                'restriction': ion.get('restriction', ion.get('Restriction', ''))
            })
        custom_ion_series = normalized_custom
    
    local_cache = {}
    results = {}
    batch_stats = {'processed': 0, 'cache_hits': 0, 'calc_errors': 0}

    def get_cache_key(row):
        return (row['Modified Peptide'], row['Charge'])

    def calculate_theoretical(peptide_sequence, modifications, max_charge, mod_nl_config=None):
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
                mod_neutral_losses=mod_nl_config
            )
            fragment_ions_df = filter_ions(fragment_ions_df_unfiltered)

            return list(zip(
                fragment_ions_df['Theoretical Mass'],
                fragment_ions_df['Ion Number'],
                fragment_ions_df['Ion Type'],
                fragment_ions_df['Fragment Sequence'],
                fragment_ions_df['Neutral Loss'],
                fragment_ions_df['Charge'],
                fragment_ions_df['Isotope'],
                fragment_ions_df['Color'],
                fragment_ions_df['Base Type']
            ))
        except KeyError as e:
            print(f"[ERROR] KeyError in calculate_theoretical: {e}")
            print(f"[ERROR] Custom ion series: {custom_ion_series}")
            raise
    
    new_rows = []
    
    for idx, row in batch_df.iterrows():
        try:
            cache_key = get_cache_key(row)
            peptide_sequence = row['Peptide']
            peptide_length = len(peptide_sequence)
            max_charge = row["Charge"]
            
            raw_mods = row.get('Parsed Modifications')
            if raw_mods is None or (isinstance(raw_mods, float) and pd.isna(raw_mods)):
                modifications = None
            elif isinstance(raw_mods, str):
                modifications = ast.literal_eval(raw_mods) if raw_mods else None
            else:
                modifications = raw_mods

            # Modification-specific neutral loss config (precomputed)
            mod_nl_config = row.get('Mod_NL_Config')
            if isinstance(mod_nl_config, float):  # NaN guard
                mod_nl_config = None

            if cache_key in local_cache:
                theoretical_fragments = local_cache[cache_key]
                batch_stats['cache_hits'] += 1
                results[idx] = theoretical_fragments
            else:
                theoretical_fragments = calculate_theoretical(peptide_sequence, modifications, max_charge, mod_nl_config)
                local_cache[cache_key] = theoretical_fragments
                results[idx] = theoretical_fragments
            
            batch_stats['processed'] += 1

        except Exception as e:
            print(f"\n[Worker] Error calculating theoretical fragments for row {idx}: {e}")
            print(f"[Worker] Peptide: {row.get('Peptide', 'Unknown')}")
            print(f"[Worker] Modified: {row.get('Modified Peptide', 'Unknown')}")
            import traceback
            traceback.print_exc()
            results[idx] = []
            batch_stats['calc_errors'] += 1
    
    # Debug output
    if batch_stats['cache_hits'] > 0 or batch_stats['calc_errors'] > 0:
        print(f"[Batch] Processed: {batch_stats['processed']}, "
              f"Cache hits: {batch_stats['cache_hits']}, "
              f"Errors: {batch_stats['calc_errors']}")
            
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
    batch_stats = {'processed': 0, 'match_errors': 0, 'zero_matches': 0}

    # Convert diagnostic ion dicts to (name, mass, color) tuples if needed
    diag_tuples = None
    if diagnostic_ions:
        diag_tuples = []
        for d in diagnostic_ions:
            if isinstance(d, dict):
                diag_tuples.append((d['Name'], d['Mass'], d['Color']))
            else:
                diag_tuples.append(d)
        if not diag_tuples:
            diag_tuples = None

    for idx, row in batch_df.iterrows():
        try:
            theoretical_fragments = row['Theoretical_Fragments']
            mz_values = row['mz']
            intensity_values = row['intensity']

            has_theoretical = theoretical_fragments is not None and len(theoretical_fragments) > 0
            has_experimental = mz_values is not None and len(mz_values) > 0

            if not has_theoretical or not has_experimental:
                results[idx] = None
                batch_stats['zero_matches'] += 1
                continue

            user_mz_values = list(zip(mz_values, intensity_values))

            # Match directly using fast path - tuples in, tuples out
            # Theoretical fragments are already filtered from Phase 1
            # Diagnostic ions are appended inside match_fragment_ions_fast
            matched_fragments = match_fragment_ions_fast(
                theoretical_fragments,
                user_mz_values,
                ppm_tolerance,
                diagnostic_ions=diag_tuples
            )

            # Count actual matches (not "No Match")
            actual_matches = sum(1 for frag in matched_fragments if frag[2] != "No Match")

            if actual_matches == 0:
                peptide = row.get('Peptide', 'Unknown')
                print(f"[DEBUG] Row {idx} ({peptide}): "
                      f"{len(theoretical_fragments)} theoretical fragments, "
                      f"{len(mz_values)} experimental peaks, "
                      f"but NO MATCHES (PPM={ppm_tolerance})")
                batch_stats['zero_matches'] += 1

            results[idx] = matched_fragments
            batch_stats['processed'] += 1

        except Exception as e:
            print(f"[Worker] Error matching fragments for row {idx}: {str(e)}")
            import traceback
            traceback.print_exc()
            batch_stats['match_errors'] += 1
            results[idx] = None

    if batch_stats['zero_matches'] > 0:
        print(f"[Batch Stats] Processed: {batch_stats['processed']}, "
              f"Zero matches: {batch_stats['zero_matches']}, "
              f"Errors: {batch_stats['match_errors']}")
    
    return results, batch_stats

# ---------------------------------------------------------
# 4) Main multiprocess functions
# ---------------------------------------------------------


def process_fragments(filtered_df, custom_ion_series=None, diagnostic_ions=None,
                     selected_ions=None, selected_internal_ions=None, ppm_tolerance=10,
                     max_workers=8, batch_size=1000, max_neutral_losses=1,
                     calculate_isotopes=True):
    """
    Process theoretical and matched fragments with REUSED process pool
    """
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from tqdm import tqdm
    
    print(f"\n[DEBUG] Starting theoretical fragment calculation for {len(filtered_df)} PSMs")
    print(f"[DEBUG] Using {max_workers} workers with batch size {batch_size}")
    
    # Calculate LARGER batches to reduce process spawning
    # Aim for 4-8 batches per worker instead of 2
    optimal_batch_size = max(200, len(filtered_df) // (max_workers * 4))
    
    print(f"[OPTIMIZATION] Using batch size {optimal_batch_size}")
    
    # PHASE 1: Theoretical fragments with SINGLE reused pool
    print("\nPhase 1: Calculating theoretical fragments (multiprocessing)")
    processed_df = filtered_df.copy()
    processed_df['Theoretical_Fragments'] = [[] for _ in range(len(filtered_df))]
    
    # Create batches for Phase 1
    batches_phase1 = np.array_split(processed_df, max(1, len(processed_df) // optimal_batch_size))
    print(f"[OPTIMIZATION] Phase 1: {len(batches_phase1)} batches")
    
    total_cache_hits = 0
    total_calc_errors = 0
    
    # Use context manager to ensure proper cleanup
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batches to REUSED pool
        futures = {
            executor.submit(
                process_theoretical_batch,
                batch,
                custom_ion_series,
                selected_ions,
                selected_internal_ions,
                max_neutral_losses,
                calculate_isotopes
            ): i for i, batch in enumerate(batches_phase1)
        }
        
        # Collect results with progress bar
        with safe_tqdm(total=len(filtered_df), desc="Calculating theoretical fragments") as pbar:
            for future in as_completed(futures):
                try:
                    batch_results, batch_stats, _ = future.result()
                    
                    # Update dataframe with batch results
                    for idx, theoretical_fragments in batch_results.items():
                        processed_df.at[idx, 'Theoretical_Fragments'] = theoretical_fragments
                    
                    # Update statistics
                    total_cache_hits += batch_stats.get('cache_hits', 0)
                    total_calc_errors += batch_stats.get('calc_errors', 0)
                    
                    pbar.update(len(batch_results))
                    
                except Exception as e:
                    print(f"[ERROR] Batch theoretical calculation failed: {e}")
                    import traceback
                    traceback.print_exc()
    
    print(f"[DEBUG] Theoretical fragments calculated for {len(processed_df[processed_df['Theoretical_Fragments'].apply(len) > 0])} rows out of {len(processed_df)}")
    if total_cache_hits > 0:
        print(f"[CACHE] Cache hits: {total_cache_hits}, Errors: {total_calc_errors}")
    
    # PHASE 2: Fragment matching with REUSED pool
    print("\nPhase 2: Matching fragments (multiprocessing)")
    processed_df['matched_fragments'] = [None for _ in range(len(filtered_df))]
    
    # Re-create batches from processed_df (which now has Theoretical_Fragments column)
    batches_phase2 = np.array_split(processed_df, max(1, len(processed_df) // optimal_batch_size))
    print(f"[OPTIMIZATION] Phase 2: {len(batches_phase2)} batches")
    
    total_match_errors = 0
    total_zero_matches = 0
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_matching_batch,
                batch,
                diagnostic_ions,
                ppm_tolerance
            ): i for i, batch in enumerate(batches_phase2)  
        }
        
        with safe_tqdm(total=len(filtered_df), desc="Matching fragments") as pbar:
            for future in as_completed(futures):
                try:
                    batch_results, batch_stats = future.result()
                    
                    for idx, matched_fragments in batch_results.items():
                        processed_df.at[idx, 'matched_fragments'] = matched_fragments
                    
                    total_match_errors += batch_stats.get('match_errors', 0)
                    total_zero_matches += batch_stats.get('zero_matches', 0)
                    
                    pbar.update(len(batch_results))
                    
                except Exception as e:
                    print(f"[ERROR] Batch matching failed: {e}")
                    import traceback
                    traceback.print_exc()
    
    if total_match_errors > 0 or total_zero_matches > 0:
        print(f"[STATS] Match errors: {total_match_errors}, Zero matches: {total_zero_matches}")
    
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

    def _ion_type_matches_selected(ion_type_full, selected_ion_type):
        """Unified ion type matching method"""
        # Mod-NL: match any ion whose Neutral Loss is ModNL1/ModNL2/ModNL3/LabileLoss
        # This is handled specially below using the neutral_loss tuple field
        if selected_ion_type == 'Mod-NL':
            return False  # handled via neutral_loss field below

        if selected_ion_type == 'z+1':
            return 'z+1' in ion_type_full.lower() or (
                ion_type_full.startswith('z') and '+1' in ion_type_full
            )
        if selected_ion_type == 'c-1':
            return 'c-1' in ion_type_full.lower() or (
                ion_type_full.startswith('c') and '-1' in ion_type_full
            )
        if selected_ion_type == 'z':
            if 'z+1' in ion_type_full.lower():
                return False
            return re.match(r'^z\d*', ion_type_full) is not None
        if selected_ion_type == 'c':
            if 'c-1' in ion_type_full.lower():
                return False
            return re.match(r'^c\d*', ion_type_full) is not None

        # Handle d (include da, db variants)
        if selected_ion_type == 'd':
            return re.match(r'^d[ab]?\d*', ion_type_full) is not None

        # Handle w (include wa, wb variants)
        if selected_ion_type == 'w':
            return re.match(r'^w[ab]?\d*', ion_type_full) is not None

        # Handle satellite neutral losses: d-H2O matches da-H2O, db-H2O etc.
        if selected_ion_type.startswith(('d-', 'w-')):
            base_letter = selected_ion_type[0]  # 'd' or 'w'
            loss_part = selected_ion_type[1:]    # '-H2O', '-NH3'
            return re.match(rf'^{base_letter}[ab]?{re.escape(loss_part)}$', ion_type_full) is not None
        if selected_ion_type.startswith('v-'):
            return ion_type_full == selected_ion_type

        base_type = ion_type_full.split('-')[0].split('+')[0]

        if selected_ion_type.startswith('int-'):
            if base_type.startswith('int-') and base_type[4:] == selected_ion_type[4:]:
                return True
        elif '-' in selected_ion_type and selected_ion_type not in ['z+1', 'c-1']:
            if selected_ion_type in ion_type_full or base_type == selected_ion_type.split('-')[0]:
                return True
        elif selected_ion_type in ['b', 'y', 'a', 'x', 'MH', 'd', 'v', 'w']:
            if base_type == selected_ion_type:
                return True
        else:
            if selected_ion_type in ion_type_full:
                return True
        return False

    results = {}

    for idx, row in batch_df.iterrows():
        matched_fragments = row.get('matched_fragments', None)

        ion_counts = {}
        unique_counts = {}

        if matched_fragments is None or len(matched_fragments) == 0:
            for ion_type in ion_types_to_count:
                ion_counts[ion_type] = 0
                unique_counts[ion_type] = 0
            results[idx] = (ion_counts, unique_counts, {})
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

            # Count by ion type
            _MOD_NL_PREFIXES = ("ModNL", "LabileLoss", "ModRM")

            def _is_mod_nl_label(nl_str):
                return any(nl_str.startswith(p) for p in _MOD_NL_PREFIXES)

            for ion_type in ion_types_to_count:
                count = 0
                unique_positions = set()

                # Granular Mod-NL sub-type: e.g. 'ModNL1-y', 'ModNL1x2-b', 'LabileLoss-b'
                mod_nl_parts = None
                if '-' in ion_type:
                    prefix = ion_type.split('-', 1)[0]
                    if _is_mod_nl_label(prefix):
                        mod_nl_parts = (prefix, ion_type.split('-', 1)[1])

                for frag in filtered:
                    if ion_type == 'Mod-NL':
                        # Legacy bulk match by neutral loss label (tuple idx 7)
                        nl = str(frag[7]) if frag[7] is not None else ''
                        if not _is_mod_nl_label(nl):
                            continue
                    elif mod_nl_parts is not None:
                        # Granular: match neutral loss AND base type
                        nl = str(frag[7]) if frag[7] is not None else ''
                        if nl != mod_nl_parts[0]:
                            continue
                        base_type = str(frag[11]).strip() if len(frag) > 11 and frag[11] else str(frag[5]).strip()
                        if base_type != mod_nl_parts[1]:
                            continue
                    else:
                        ion_type_full = str(frag[5]) if frag[5] is not None else ''
                        if not _ion_type_matches_selected(ion_type_full, ion_type):
                            continue

                    count += 1
                    try:
                        ion_number = int(frag[4])
                        unique_positions.add(ion_number)
                    except (ValueError, TypeError):
                        pass

                ion_counts[ion_type] = count
                unique_counts[ion_type] = len(unique_positions)

            # Sequence coverage by base type
            base_type_positions = {}
            for frag in filtered:
                bt = str(frag[11]).strip() if frag[11] is not None else ''
                if not bt or bt in ('None', 'nan', ''):
                    continue
                try:
                    ion_number = int(frag[4])
                    if bt not in base_type_positions:
                        base_type_positions[bt] = set()
                    base_type_positions[bt].add(ion_number)
                except (ValueError, TypeError):
                    pass
            base_type_coverage = {bt: len(positions) for bt, positions in base_type_positions.items()}

        except Exception as e:
            print(f"[ERROR] Error processing row {idx}: {e}")
            for ion_type in ion_types_to_count:
                ion_counts[ion_type] = 0
                unique_counts[ion_type] = 0
            base_type_coverage = {}

        results[idx] = (ion_counts, unique_counts, base_type_coverage)

    return results


def count_ion_types_parallel(merged_df, ion_types_to_count=['b', 'y'], max_workers=8, batch_size=1000,
                             scoring_max_charge=0):
    """
    Parallelized ion counting with optimized batch sizes
    """
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from tqdm import tqdm
    
    print(f"[DEBUG] Starting parallel ion counting for {len(merged_df)} rows with {max_workers} workers")
    print(f"[DEBUG] Ion types to count: {ion_types_to_count}")
    
    # Initialize columns for all ion types
    for ion_type in ion_types_to_count:
        merged_df[f'{ion_type}_count'] = 0
        merged_df[f'{ion_type}_unique_count'] = 0
    
    # CHANGED: Use larger batches (aim for 4-8 batches per worker)
    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))
    
    print(f"[OPTIMIZATION] Using {len(batches)} batches (batch size ~{optimal_batch_size})")
    
    final_results = {}
    
    # CHANGED: Use single context manager for entire operation
    with safe_tqdm(total=len(merged_df), desc="Counting ion types (parallel)") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all batches to reused pool
            futures = {
                executor.submit(count_ions_batch, batch, ion_types_to_count,
                                scoring_max_charge): i
                for i, batch in enumerate(batches)
            }
            
            # Collect results
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    print(f"[ERROR] Batch counting failed: {e}")
    
    # Assign results back to dataframe
    all_base_types = set()
    for idx, (ion_counts, unique_counts, base_type_coverage) in final_results.items():
        for ion_type in ion_types_to_count:
            merged_df.at[idx, f'{ion_type}_count'] = ion_counts.get(ion_type, 0)
            merged_df.at[idx, f'{ion_type}_unique_count'] = unique_counts.get(ion_type, 0)
        all_base_types.update(base_type_coverage.keys())

    # Initialize sequence coverage columns for all discovered base types
    for base_type in sorted(all_base_types):
        merged_df[f'sequence_coverage_count_{base_type}'] = 0

    # Populate sequence coverage columns
    for idx, (ion_counts, unique_counts, base_type_coverage) in final_results.items():
        for base_type, coverage_count in base_type_coverage.items():
            merged_df.at[idx, f'sequence_coverage_count_{base_type}'] = coverage_count

    print(f"[DEBUG] Ion counting complete")

    # Print statistics
    for ion_type in ion_types_to_count:
        mean_count = merged_df[f'{ion_type}_unique_count'].mean()
        max_count = merged_df[f'{ion_type}_unique_count'].max()
        print(f"[DEBUG] {ion_type}: Mean={mean_count:.2f}, Max={max_count}")

    # Print sequence coverage statistics
    for base_type in sorted(all_base_types):
        col = f'sequence_coverage_count_{base_type}'
        mean_cov = merged_df[col].mean()
        max_cov = merged_df[col].max()
        print(f"[DEBUG] Sequence coverage {base_type}: Mean={mean_cov:.2f}, Max={max_cov}")
    
    return merged_df


def _compute_ratios_for_ion_type(matched_fragments, ion_type, charge_range, match_func,
                                 numerator_isotope=0, denominator_isotope=-1):
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
    intensity_map = {}  # (charge, position) -> {isotope: [intensities]}

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

        key = (charge, position)
        if key not in intensity_map:
            intensity_map[key] = {}
        if isotope not in intensity_map[key]:
            intensity_map[key][isotope] = []
        intensity_map[key][isotope].append(intensity)

    # Compute ratios: numerator_isotope / denominator_isotope
    ratios_by_charge = {}

    for (charge, position), isotope_data in intensity_map.items():
        if charge not in ratios_by_charge:
            ratios_by_charge[charge] = {}

        has_num = numerator_isotope in isotope_data
        has_denom = denominator_isotope in isotope_data

        if has_num and has_denom:
            num_val = sum(isotope_data[numerator_isotope]) / len(isotope_data[numerator_isotope])
            denom_val = sum(isotope_data[denominator_isotope]) / len(isotope_data[denominator_isotope])

            if denom_val > 0:
                ratios_by_charge[charge][position] = num_val / denom_val
            elif num_val > 0:
                ratios_by_charge[charge][position] = 5.0
            else:
                ratios_by_charge[charge][position] = 0
        elif has_num and not has_denom:
            num_val = sum(isotope_data[numerator_isotope]) / len(isotope_data[numerator_isotope])
            ratios_by_charge[charge][position] = 5.0 if num_val > 0 else 0
        elif has_denom and not has_num:
            ratios_by_charge[charge][position] = 0

    return ratios_by_charge


def compute_migration_ratios_batch(batch_df, z_migration_enabled, c_migration_enabled,
                                   charge_range):
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
        if migration_type == 'z+1':
            return 'z+1' in ion_type_full.lower() or (
                ion_type_full.startswith('z') and '+1' in ion_type_full
            )
        elif migration_type == 'c':
            if 'c-1' in ion_type_full.lower():
                return False
            base_match = re.match(r'^c\d*', ion_type_full)
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
                    position_ratios.append(f"{ratio:.4f}".rstrip('0').rstrip('.'))

            ratio_str = ",".join(position_ratios)
            parts.append(f"({ratio_str}){charge}")

        return ",".join(parts)

    results = {}

    for idx, row in batch_df.iterrows():
        matched_fragments = row.get('matched_fragments', None)
        peptide = row.get('Peptide', '')
        peptide_length = len(peptide) if peptide else 0

        z_migration_str = ''
        c_migration_str = ''

        if not matched_fragments or peptide_length < 2:
            results[idx] = (z_migration_str, c_migration_str)
            continue

        if z_migration_enabled:
            z_ratios = _compute_ratios_for_ion_type(
                matched_fragments, 'z+1', charge_range,
                _ion_type_matches_for_migration,
                numerator_isotope=0, denominator_isotope=-1
            )
            z_migration_str = _format_migration_string(
                z_ratios, peptide_length, charge_range
            )

        if c_migration_enabled:
            c_ratios = _compute_ratios_for_ion_type(
                matched_fragments, 'c', charge_range,
                _ion_type_matches_for_migration,
                numerator_isotope=-1, denominator_isotope=0
            )
            c_migration_str = _format_migration_string(
                c_ratios, peptide_length, charge_range
            )

        results[idx] = (z_migration_str, c_migration_str)

    return results


def calculate_migration_ratios_parallel(merged_df, z_migration_enabled=False,
                                        c_migration_enabled=False,
                                        charge_range=None, max_workers=8,
                                        batch_size=1000):
    """
    Parallelized hydrogen migration ratio computation.

    For z+1: computes isotope(0)/isotope(-1) ratios per backbone position.
    For c: computes isotope(-1)/isotope(0) ratios per backbone position.
    Results stored as formatted strings in z_migration and c_migration columns.
    """
    if charge_range is None:
        charge_range = [1, 2, 3]

    print(f"[MIGRATION] Starting parallel migration calculation for {len(merged_df)} rows")
    print(f"[MIGRATION] z+1 enabled: {z_migration_enabled}, c enabled: {c_migration_enabled}")
    print(f"[MIGRATION] Charge range: {charge_range}")

    if z_migration_enabled:
        merged_df['z_migration'] = ''
    if c_migration_enabled:
        merged_df['c_migration'] = ''

    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))

    print(f"[MIGRATION] Using {len(batches)} batches (batch size ~{optimal_batch_size})")

    final_results = {}

    with safe_tqdm(total=len(merged_df), desc="Computing migration ratios") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    compute_migration_ratios_batch,
                    batch,
                    z_migration_enabled,
                    c_migration_enabled,
                    charge_range
                ): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    print(f"[ERROR] Migration batch failed: {e}")

    for idx, (z_str, c_str) in final_results.items():
        if z_migration_enabled:
            merged_df.at[idx, 'z_migration'] = z_str
        if c_migration_enabled:
            merged_df.at[idx, 'c_migration'] = c_str

    print(f"[MIGRATION] Migration calculation complete")

    return merged_df


# ---------------------------------------------------------
# Parallelized score calculation (Annotated TIC% + Rescore)
# ---------------------------------------------------------
def compute_scores_batch(batch_df, ion_types_to_use, scoring_methods=None, ppm_tolerance=10.0,
                         scoring_max_charge=0):
    """
    Worker function to compute Annotated TIC%, Rescore, and optional scoring
    metrics (consecutive series, complementary pairs) for a batch.
    Works directly with matched_fragments tuples to avoid per-row DataFrame creation.
    Must be at top level for pickling by ProcessPoolExecutor.

    Tuple indices: 0=m/z, 1=intensity, 2=Matched, 3=error_ppm, 4=Ion Number,
                   5=Ion Type, 6=Fragment Sequence, 7=Neutral Loss, 8=Charge,
                   9=Isotope, 10=Color, 11=Base Type

    Returns dict[idx] -> (annotated_pct, rescore,
                          consec_longest, consec_detail, comp_pairs, comp_possible,
                          morpheus_val)
    """
    if scoring_methods is None:
        scoring_methods = {}

    calc_consecutive = scoring_methods.get('consecutive_series', False)
    calc_complementary = scoring_methods.get('complementary_pairs', False)
    calc_morpheus = scoring_methods.get('morpheus_score', False)

    n_term_types = {'b', 'a', 'c', 'c-1', 'd', 'da', 'db'}
    c_term_types = {'y', 'x', 'z', 'z+1', 'w', 'wa', 'wb', 'v'}

    results = {}

    for idx, row in batch_df.iterrows():
        matched_fragments = row.get('matched_fragments', None)
        intensity_values = row.get('intensity', [])

        annotated_pct = 0.0
        rescore = 0.0
        consec_longest = 0
        consec_detail = ''
        comp_pairs = 0
        comp_possible = 0
        morpheus_val = 0.0

        if not matched_fragments or not intensity_values:
            results[idx] = (annotated_pct, rescore,
                            consec_longest, consec_detail, comp_pairs, comp_possible,
                            morpheus_val)
            continue

        total_experimental_intensity = sum(intensity_values)
        if total_experimental_intensity == 0:
            results[idx] = (annotated_pct, rescore,
                            consec_longest, consec_detail, comp_pairs, comp_possible,
                            morpheus_val)
            continue

        # Get peptide length for metrics that need it
        peptide = row.get('Peptide', '')
        pep_len = len(peptide) if peptide else 0

        # Single pass over matched fragments for all calculations
        annotated_intensity = 0.0
        unique_ion_positions = {ion_type: set() for ion_type in ion_types_to_use}
        total_scored_intensity = 0.0

        # Additional tracking for optional metrics
        mono_positions_by_base = {}   # base_type -> set of ion_numbers (for consecutive)
        n_positions = set()            # N-terminal ion numbers (for complementary)
        c_positions = set()            # C-terminal ion numbers (for complementary)
        total_mono_matched = 0         # total monoisotopic matched count

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

            # Everything below is monoisotopic only (scoring, ion counting, export)
            if isotope != 0:
                continue

            # Charge state filter for scoring
            if scoring_max_charge > 0:
                try:
                    charge = int(float(frag[8]))
                except (ValueError, TypeError):
                    charge = 1
                if charge > scoring_max_charge:
                    continue

            # X!Tandem: only count ions in the selected types
            base_type = str(frag[11]).strip() if frag[11] is not None else ''
            if base_type not in ion_types_to_use:
                continue

            total_scored_intensity += intensity

            try:
                ion_number = int(frag[4])
            except (ValueError, TypeError):
                ion_number = None

            if ion_number is not None:
                unique_ion_positions[base_type].add(ion_number)
                total_mono_matched += 1

                # Track for consecutive series
                if calc_consecutive:
                    if base_type not in mono_positions_by_base:
                        mono_positions_by_base[base_type] = set()
                    mono_positions_by_base[base_type].add(ion_number)

                # Track for complementary pairs
                if calc_complementary and pep_len >= 2:
                    ion_type_full = str(frag[5]).lower() if frag[5] else ''
                    if 'z+1' in ion_type_full:
                        effective = 'z+1'
                    elif 'c-1' in ion_type_full:
                        effective = 'c-1'
                    else:
                        effective = base_type
                    if effective in n_term_types:
                        n_positions.add(ion_number)
                    elif effective in c_term_types:
                        c_positions.add(ion_number)

        # Annotated TIC %
        if annotated_intensity > 0:
            annotated_pct = (annotated_intensity / total_experimental_intensity) * 100.0

        # Rescore: HS = log1p((sum_intensities) * product(Ni!))
        factorial_product = 1
        for ion_type in ion_types_to_use:
            unique_count = len(unique_ion_positions[ion_type])
            if unique_count > 0:
                factorial_product *= factorial(unique_count)

        if total_scored_intensity > 0 and factorial_product > 0:
            rescore = math.log1p(total_scored_intensity * factorial_product)

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
                consec_detail = ''

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

        # --- Optional: Morpheus Score ---
        if calc_morpheus:
            morpheus_val = round(total_mono_matched + annotated_pct / 100.0, 4)

        results[idx] = (annotated_pct, rescore,
                        consec_longest, consec_detail, comp_pairs, comp_possible,
                        morpheus_val)

    return results


def calculate_scores_parallel(merged_df, ion_types_to_use=None, max_workers=8,
                              scoring_methods=None, ppm_tolerance=10.0,
                              scoring_max_charge=0):
    """
    Parallelized score calculation combining Annotated TIC%, Rescore,
    and optional metrics (consecutive, complementary).
    Uses compute_scores_batch with ProcessPoolExecutor.
    """
    if ion_types_to_use is None:
        ion_types_to_use = ['b', 'y']
    if scoring_methods is None:
        scoring_methods = {}

    if merged_df.empty:
        merged_df['Annotated_TIC_%'] = 0.0
        merged_df['Rescore'] = 0.0
        return merged_df

    any_optional = any(scoring_methods.get(k) for k in
                       ('consecutive_series', 'complementary_pairs',
                        'morpheus_score'))

    print(f"[DEBUG] Starting parallel score calculation for {len(merged_df)} rows with {max_workers} workers")
    print(f"[DEBUG] Ion types for scoring: {ion_types_to_use}")
    if any_optional:
        enabled = [k for k in ('consecutive_series', 'complementary_pairs',
                                'morpheus_score')
                   if scoring_methods.get(k)]
        print(f"[DEBUG] Optional scoring metrics enabled: {enabled}")

    optimal_batch_size = max(200, len(merged_df) // (max_workers * 4))
    batches = np.array_split(merged_df, max(1, len(merged_df) // optimal_batch_size))

    print(f"[OPTIMIZATION] Score calculation: {len(batches)} batches (batch size ~{optimal_batch_size})")

    final_results = {}

    with safe_tqdm(total=len(merged_df), desc="Calculating scores (parallel)") as pbar:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(compute_scores_batch, batch, ion_types_to_use,
                                scoring_methods, ppm_tolerance,
                                scoring_max_charge): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    final_results.update(batch_results)
                    pbar.update(len(batch_results))
                except Exception as e:
                    print(f"[ERROR] Score calculation batch failed: {e}")

    # Assign results back to dataframe
    annotated_vals = []
    rescore_vals = []
    consec_longest_vals = []
    consec_detail_vals = []
    comp_pairs_vals = []
    morpheus_vals = []

    for idx in merged_df.index:
        if idx in final_results:
            (annotated_pct, rescore,
             consec_longest, consec_detail, comp_pairs, comp_possible,
             morpheus_val) = final_results[idx]
            annotated_vals.append(annotated_pct)
            rescore_vals.append(rescore)
            consec_longest_vals.append(consec_longest)
            consec_detail_vals.append(consec_detail)
            comp_pairs_vals.append(f"{comp_pairs}/{comp_possible}" if comp_possible > 0 else "0/0")
            morpheus_vals.append(morpheus_val)
        else:
            annotated_vals.append(0.0)
            rescore_vals.append(0.0)
            consec_longest_vals.append(0)
            consec_detail_vals.append('')
            comp_pairs_vals.append('0/0')
            morpheus_vals.append(0.0)

    merged_df['Annotated_TIC_%'] = annotated_vals
    merged_df['Rescore'] = rescore_vals

    # Only add optional metric columns when that metric was enabled
    if scoring_methods.get('consecutive_series'):
        merged_df['Consecutive_Series_Longest'] = consec_longest_vals
        merged_df['Consecutive_Series_Detail'] = consec_detail_vals
    if scoring_methods.get('complementary_pairs'):
        merged_df['Complementary_Pairs'] = comp_pairs_vals
    if scoring_methods.get('morpheus_score'):
        merged_df['Morpheus_Score'] = morpheus_vals

    print(f"[DEBUG] Score calculation complete. "
          f"Annotated TIC: Mean={np.mean(annotated_vals):.2f}%, "
          f"Rescore: Mean={np.mean(rescore_vals):.3f}, Max={np.max(rescore_vals):.3f}")

    return merged_df


def calculate_length_dependent_normalized_scores(df, score_column='Morpheus_Score',
                                                  psm_type_column='PSM_Type',
                                                  peptide_column='Peptide',
                                                  fdr_threshold=0.05,
                                                  window_size=5):
    """
    Wilhelm et al. length-dependent score normalization.

    1. Bin PSMs by peptide length
    2. For each length, bin scores in 1-point intervals
    3. Smooth target/decoy counts (moving avg, window=5)
    4. Local FDR = decoy / target per bin
    5. Smooth FDR (moving avg, window=5)
    6. Cutoff = min score where local FDR < threshold
    7. Normalized = score / cutoff

    Returns: Series of normalized scores (NaN where cutoff unavailable)
    """
    normalized = pd.Series(np.nan, index=df.index)

    # Need PSM_Type column for FDR calculation
    if psm_type_column not in df.columns:
        print("[WARNING] PSM_Type column not found — cannot compute length-dependent "
              "normalization. Enable decoy detection.")
        return normalized

    # Need the score column to exist
    if score_column not in df.columns:
        print(f"[WARNING] {score_column} column not found — cannot compute length-dependent "
              "normalization. Enable the corresponding scoring method.")
        return normalized

    # Get peptide lengths
    lengths = df[peptide_column].str.len()
    scores = df[score_column].astype(float)
    psm_types = df[psm_type_column]

    # Process each peptide length group
    cutoffs = {}
    for pep_len in lengths.unique():
        mask = lengths == pep_len
        group_scores = scores[mask]
        group_types = psm_types[mask]

        if len(group_scores) < window_size:
            continue  # Not enough data for this length

        # Bin scores in intervals of 1 point
        min_score = int(np.floor(group_scores.min()))
        max_score = int(np.ceil(group_scores.max()))

        if min_score == max_score:
            continue

        bins = np.arange(min_score, max_score + 2, 1.0)  # +2 for right edge

        # Count targets and decoys per bin
        target_scores = group_scores[group_types == 'Target']
        decoy_scores = group_scores[group_types == 'Decoy']

        target_counts, _ = np.histogram(target_scores, bins=bins)
        decoy_counts, _ = np.histogram(decoy_scores, bins=bins)

        # Smooth counts with moving average (window=5)
        kernel = np.ones(window_size) / window_size
        target_smooth = np.convolve(target_counts.astype(float), kernel, mode='same')
        decoy_smooth = np.convolve(decoy_counts.astype(float), kernel, mode='same')

        # Calculate local FDR = decoy / target (avoid div by zero)
        with np.errstate(divide='ignore', invalid='ignore'):
            local_fdr = np.where(target_smooth > 0, decoy_smooth / target_smooth, 1.0)

        # Smooth FDR with moving average (window=5)
        fdr_smooth = np.convolve(local_fdr, kernel, mode='same')

        # Find minimum score where smoothed FDR < threshold
        bin_centers = (bins[:-1] + bins[1:]) / 2.0
        valid_bins = np.where(fdr_smooth < fdr_threshold)[0]

        if len(valid_bins) > 0:
            cutoff = bin_centers[valid_bins[0]]  # minimum score meeting criterion
            if cutoff > 0:
                cutoffs[pep_len] = cutoff

    # Apply normalization: score / cutoff
    for pep_len, cutoff in cutoffs.items():
        len_mask = lengths == pep_len
        normalized[len_mask] = scores[len_mask] / cutoff

    n_normalized = normalized.notna().sum()
    n_total = len(df)
    print(f"[RESCORING] Length-dependent normalization: {len(cutoffs)} length cutoffs found, "
          f"{n_normalized}/{n_total} PSMs normalized")

    return normalized


def calculate_labeled_intensity_percentage(df):
    """
    Calculate the percentage of total intensity that is annotated (matched to theoretical fragments)
    RENAMED: Now called 'Annotated_TIC_%' to match terminology in other parts of program
    """
    if df.empty:
        df['Annotated_TIC_%'] = 0.0 
        return df
    
    print(f"[DEBUG] Calculating annotated TIC percentage for {len(df)} rows")
    
    annotated_percentages = []  
    
    for idx, row in df.iterrows():
        try:
            # Get matched fragments
            matched_fragments = row.get('matched_fragments', [])
            
            # Get experimental data (mz, intensity)
            mz_values = row.get('mz', [])
            intensity_values = row.get('intensity', [])
            
            if not matched_fragments or not intensity_values:
                annotated_percentages.append(0.0)
                continue
            
            # Calculate total experimental intensity
            total_intensity = sum(intensity_values)
            
            if total_intensity == 0:
                annotated_percentages.append(0.0)
                continue
            
            # Calculate annotated (matched) intensity
            annotated_intensity = 0.0
            
            # Convert matched_fragments to DataFrame for easier processing
            matched_df = pd.DataFrame(matched_fragments, columns=[
                'm/z', 'intensity', 'Matched', 'error_ppm', 'Ion Number', 
                'Ion Type', 'Fragment Sequence', 'Neutral Loss', 'Charge', 
                'Isotope', 'Color', 'Base Type'
            ])
            
            # Filter for matched peaks only
            matched_df = matched_df[
                (matched_df['Matched'].notna()) & 
                (matched_df['Matched'] != 'No Match')
            ]
            
            # Sum intensities of matched peaks
            for _, fragment in matched_df.iterrows():
                try:
                    intensity = float(fragment.get('intensity', 0))
                    annotated_intensity += intensity
                except (ValueError, TypeError):
                    continue
            
            # Calculate percentage
            annotated_percentage = (annotated_intensity / total_intensity) * 100.0
            annotated_percentages.append(annotated_percentage)
            
        except Exception as e:
            print(f"[ERROR] Error calculating annotated TIC for row {idx}: {e}")
            annotated_percentages.append(0.0)
    
    df['Annotated_TIC_%'] = annotated_percentages
    
    print(f"[DEBUG] Annotated TIC calculation complete. Mean: {np.mean(annotated_percentages):.2f}%")
    
    return df

def calculate_xtandem(df, ion_types_to_use=None):
    """
    Calculate X!Tandem score using: HS = log10((∑Ii) * Nb! * Ny!)
    - Ion counts: UNIQUE Ion Number positions per base type (isotope=0 only)
    - Intensities: SUM of ALL matched peaks (all isotopes)

    IMPORTANT: This is called 'Rescore' in output to distinguish from original Hyperscore
    
    Args:
        df: DataFrame with matched fragment data
        ion_types_to_use: List of ion types to include in scoring (e.g., ['b', 'y', 'a'])
    """
    if df.empty:
        df['Rescore'] = 0.0 
        return df
    
    # Default to common ion types if not specified
    if ion_types_to_use is None:
        ion_types_to_use = ['b', 'y']
    
    print(f"[DEBUG] Calculating rescore for {len(df)} rows using ion types: {ion_types_to_use}")
    
    rescores = [] 
    
    for idx, row in df.iterrows():
        try:
            # Get matched fragments for this row
            matched_fragments = row.get('matched_fragments', [])
            
            if not matched_fragments:
                rescores.append(0.0)
                continue
            
            # Convert to DataFrame for easier processing
            matched_df = pd.DataFrame(matched_fragments, columns=[
                'm/z', 'intensity', 'Matched', 'error_ppm', 'Ion Number', 
                'Ion Type', 'Fragment Sequence', 'Neutral Loss', 'Charge', 
                'Isotope', 'Color', 'Base Type'
            ])
            
            # Filter for matched peaks only
            matched_df = matched_df[
                (matched_df['Matched'].notna()) & 
                (matched_df['Matched'] != 'No Match')
            ]
            
            if matched_df.empty:
                rescores.append(0.0)
                continue
            
            # Initialize counters
            unique_ion_positions = {ion_type: set() for ion_type in ion_types_to_use}
            total_ion_intensities = {ion_type: 0 for ion_type in ion_types_to_use}
            total_intensity = 0.0
            
            # Process each fragment
            for _, fragment in matched_df.iterrows():
                base_type = str(fragment.get('Base Type', '')).strip()
                
                # Skip if not in our ion types
                if base_type not in ion_types_to_use:
                    continue
                
                # Get ion number
                try:
                    ion_number = int(fragment.get('Ion Number', 0))
                except (ValueError, TypeError):
                    continue
                
                # Get isotope
                try:
                    isotope = int(float(fragment.get('Isotope', 0)))
                except (ValueError, TypeError):
                    isotope = 0

                # Only use monoisotopic peaks for scoring
                if isotope != 0:
                    continue

                # Get intensity
                try:
                    intensity = float(fragment.get('intensity', 0))
                except (ValueError, TypeError):
                    intensity = 0.0

                # Add intensity (monoisotopic only)
                total_ion_intensities[base_type] += intensity
                total_intensity += intensity

                # Count unique positions
                unique_ion_positions[base_type].add(ion_number)
            
            # Calculate factorial product using ONLY unique monoisotopic position counts
            factorial_product = 1
            for ion_type in ion_types_to_use:
                unique_count = len(unique_ion_positions[ion_type])
                if unique_count > 0:
                    factorial_product *= factorial(unique_count)
            
            # Calculate rescore: HS = log10((∑Ii) * Nb! * Ny!)
            if total_intensity > 0 and factorial_product > 0:
                rescore_raw = total_intensity * factorial_product
                rescore = math.log1p(rescore_raw)
            else:
                rescore = 0.0
            
            rescores.append(rescore)
            
        except Exception as e:
            print(f"[ERROR] Error calculating rescore for row {idx}: {e}")
            rescores.append(0.0)
    
    df['Rescore'] = rescores  #Rescore
    
    print(f"[DEBUG] Rescore calculation complete. Mean: {np.mean(rescores):.3f}, Max: {np.max(rescores):.3f}")
    
    return df