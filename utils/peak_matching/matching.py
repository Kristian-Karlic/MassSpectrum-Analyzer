"""Peak matching: match observed m/z values to theoretical fragment ions."""

import json
import logging
import traceback
import numpy as np
import pandas as pd

from .fragmentation import calculate_fragment_ions, filter_ions

logger = logging.getLogger(__name__)

__all__ = [
    'match_fragment_ions',
    'match_fragment_ions_fast',
    'fragment_and_match_peaks_cached',
]


# ---------------------------------------------------------------------------
# Shared matching core
# ---------------------------------------------------------------------------

def _match_core(theo_masses_arr, all_ions, user_mzs, ppm_tolerance,
                get_isotope, get_ion_num, get_ion_type, get_charge,
                track_alternatives=False):
    """
    Core matching engine used by both match_fragment_ions and match_fragment_ions_fast.

    Accessor functions abstract over dict-vs-tuple input format:
        get_isotope(ion) -> int
        get_ion_num(ion) -> value
        get_ion_type(ion) -> str
        get_charge(ion) -> int

    Returns
    -------
    matches : np.ndarray (bool)
    matched_indices : np.ndarray (int)
    ppm_errors : np.ndarray (float)
    base_matched : set
    all_candidates_per_peak : list[list] | None
        Only populated when *track_alternatives* is True.
    """
    sort_idx = np.argsort(theo_masses_arr)
    theo_masses_sorted = theo_masses_arr[sort_idx]

    num_user = len(user_mzs)
    matches = np.zeros(num_user, dtype=bool)
    matched_indices = np.full(num_user, -1, dtype=int)
    ppm_errors = np.full(num_user, np.nan)

    matched_ions = set()
    base_matched = set()

    all_candidates_per_peak = [[] for _ in range(num_user)] if track_alternatives else None

    for u_idx in range(num_user):
        mz = user_mzs[u_idx]
        lo_mass = mz * (1.0 - ppm_tolerance * 1e-6)
        hi_mass = mz * (1.0 + ppm_tolerance * 1e-6)

        left_idx = np.searchsorted(theo_masses_sorted, lo_mass, side='left')
        right_idx = np.searchsorted(theo_masses_sorted, hi_mass, side='right')

        candidate_orig_indices = [sort_idx[i] for i in range(left_idx, right_idx)]

        # Store ALL candidates (before filtering) for alternative match reporting
        if track_alternatives:
            for c_idx in candidate_orig_indices:
                c_ion = all_ions[c_idx]
                c_err = 1e6 * abs(theo_masses_arr[c_idx] - mz) / theo_masses_arr[c_idx]
                all_candidates_per_peak[u_idx].append((c_idx, c_err, c_ion))

        # Filter out already matched ions
        candidate_orig_indices = [c for c in candidate_orig_indices if c not in matched_ions]
        if not candidate_orig_indices:
            continue

        # Calculate ppm errors for candidates
        c_masses = theo_masses_arr[candidate_orig_indices]
        c_ppm = 1e6 * np.abs(c_masses - mz) / c_masses

        # Sort by ascending ppm error
        sort_c = np.argsort(c_ppm)

        # Try candidates in order of best ppm match
        for idx_c in sort_c:
            ion_idx = candidate_orig_indices[idx_c]
            ion_err = c_ppm[idx_c]
            ion_info = all_ions[ion_idx]

            iso = get_isotope(ion_info)
            ion_num = get_ion_num(ion_info)
            ion_type = get_ion_type(ion_info)
            charge = get_charge(ion_info)

            # If isotope > 0, only match if base is already matched
            if iso > 0:
                if (ion_num, ion_type, charge) not in base_matched:
                    continue

            # Mark the match
            matches[u_idx] = True
            matched_indices[u_idx] = ion_idx
            ppm_errors[u_idx] = ion_err
            matched_ions.add(ion_idx)

            # If it's a base isotope, note that the base is matched
            if iso == 0:
                base_matched.add((ion_num, ion_type, charge))
            break

    return matches, matched_indices, ppm_errors, base_matched, all_candidates_per_peak


# ---------------------------------------------------------------------------
# Dict-based matching (full DataFrame output with alternative matches)
# ---------------------------------------------------------------------------

def match_fragment_ions(calculated_ions, user_mz_values, ppm_tolerance=10):
    """
    Match observed m/z values to calculated fragment ions within ppm tolerance.
    Uses optimized searching and isotope matching logic.

    Args:
        calculated_ions: List of calculated ion dictionaries
        user_mz_values: List of (mz, intensity) tuples
        ppm_tolerance: PPM tolerance for matching

    Returns:
        DataFrame with matched results
    """
    user_mzs = np.array([mz for (mz, _) in user_mz_values], dtype=np.float64)
    user_intensities = np.array([it for (_, it) in user_mz_values], dtype=np.float64)

    theo_masses_arr = np.array([ion["Theoretical Mass"] for ion in calculated_ions], dtype=np.float64)

    # Dict accessors
    matches, matched_indices, ppm_errors, _, all_candidates_per_peak = _match_core(
        theo_masses_arr, calculated_ions, user_mzs, ppm_tolerance,
        get_isotope=lambda ion: ion["Isotope"],
        get_ion_num=lambda ion: ion["Ion Number"],
        get_ion_type=lambda ion: ion["Ion Type"],
        get_charge=lambda ion: ion["Charge"],
        track_alternatives=True,
    )

    num_user = len(user_mzs)

    # Build final results table
    results = []
    for u_idx in range(num_user):
        mz_val = user_mzs[u_idx]
        intensity_val = user_intensities[u_idx]
        matched_str = "No Match"
        err_ppm = None
        ion_data = {
            "Ion Number": None, "Ion Type": None, "Fragment Sequence": None,
            "Neutral Loss": None, "Charge": None, "Isotope": None,
            "Color": None, "Base Type": None, "Ion Series Type": None
        }

        if matches[u_idx]:
            i_idx = matched_indices[u_idx]
            err_ppm = ppm_errors[u_idx]
            ion_info = calculated_ions[i_idx]
            matched_str = ion_info["Theoretical Mass"]

            ion_data = {
                "Ion Number": ion_info["Ion Number"],
                "Ion Type": ion_info["Ion Type"],
                "Fragment Sequence": ion_info["Fragment Sequence"],
                "Neutral Loss": ion_info["Neutral Loss"],
                "Charge": ion_info["Charge"],
                "Isotope": ion_info["Isotope"],
                "Color": ion_info["Color"],
                "Base Type": ion_info["Base Type"],
                "Ion Series Type": ion_info.get("Ion Series Type", "Standard-Ion-Series")
            }

        # Build alternative matches list (monoisotopic candidates that are NOT the best match)
        alt_matches = []
        best_ion_idx = matched_indices[u_idx] if matches[u_idx] else -1
        for cand_idx, cand_err, cand_ion in all_candidates_per_peak[u_idx]:
            if cand_idx == best_ion_idx:
                continue  # skip the primary match
            # Only include monoisotopic alternatives (Isotope == 0)
            if cand_ion['Isotope'] != 0:
                continue
            charge_str = f"{int(cand_ion['Charge'])}+" if cand_ion['Charge'] > 1 else ""
            alt_label = f"{cand_ion['Ion Type']}{cand_ion['Ion Number']}{charge_str}"
            alt_matches.append({
                "label": alt_label,
                "ppm": round(cand_err, 4),
                "Theoretical Mass": cand_ion["Theoretical Mass"],
                "Ion Number": cand_ion["Ion Number"],
                "Ion Type": cand_ion["Ion Type"],
                "Fragment Sequence": cand_ion["Fragment Sequence"],
                "Neutral Loss": cand_ion["Neutral Loss"],
                "Charge": int(cand_ion["Charge"]),
                "Isotope": int(cand_ion["Isotope"]),
                "Color": cand_ion["Color"],
                "Base Type": cand_ion["Base Type"],
                "Ion Series Type": cand_ion.get("Ion Series Type", "Standard-Ion-Series")
            })

        # Sort alternatives by ppm error
        alt_matches.sort(key=lambda x: x["ppm"])
        alt_matches_str = json.dumps(alt_matches) if alt_matches else ""

        row_dict = {"m/z": mz_val, "intensity": intensity_val, "Matched": matched_str, "error_ppm": err_ppm,
                    "Alternative Matches": alt_matches_str}
        row_dict.update(ion_data)
        results.append(row_dict)

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Tuple-based fast matching (batch rescoring pipeline)
# ---------------------------------------------------------------------------

def match_fragment_ions_fast(theoretical_tuples, user_mz_values, ppm_tolerance=10, diagnostic_ions=None):
    """
    Fast fragment matching for batch rescoring pipeline.
    Accepts theoretical fragments as tuples directly, returns matched results as tuples.
    Skips alternative match tracking and DataFrame construction.

    Args:
        theoretical_tuples: List of tuples (Theoretical Mass, Ion Number, Ion Type,
                           Fragment Sequence, Neutral Loss, Charge, Isotope, Color, Base Type)
        user_mz_values: List of (mz, intensity) tuples
        ppm_tolerance: PPM tolerance for matching
        diagnostic_ions: Optional list of (name, mass, color) diagnostic ions

    Returns:
        List of 12-element tuples: (m/z, intensity, Matched, error_ppm, Ion Number,
                                     Ion Type, Fragment Sequence, Neutral Loss, Charge,
                                     Isotope, Color, Base Type)
    """
    user_mzs = np.array([mz for (mz, _) in user_mz_values], dtype=np.float64)
    user_intensities = np.array([it for (_, it) in user_mz_values], dtype=np.float64)

    # Build theoretical array from tuples + optional diagnostic ions
    # Tuple indices: 0=Mass, 1=IonNum, 2=IonType, 3=FragSeq, 4=NeutLoss, 5=Charge, 6=Isotope, 7=Color, 8=BaseType
    all_ions = list(theoretical_tuples)
    if diagnostic_ions:
        for (ion_name, mass_val, color) in diagnostic_ions:
            all_ions.append((mass_val, "", ion_name, "", "Custom_Ion", 1, 0, color, None))

    if not all_ions:
        return [
            (user_mzs[i], user_intensities[i], "No Match", None, None, None, None, None, None, None, None, None)
            for i in range(len(user_mzs))
        ]

    theo_masses_arr = np.array([ion[0] for ion in all_ions], dtype=np.float64)

    # Tuple accessors
    matches, matched_indices, ppm_errors, _, _ = _match_core(
        theo_masses_arr, all_ions, user_mzs, ppm_tolerance,
        get_isotope=lambda ion: ion[6],
        get_ion_num=lambda ion: ion[1],
        get_ion_type=lambda ion: ion[2],
        get_charge=lambda ion: ion[5],
        track_alternatives=False,
    )

    # Build result tuples directly
    result_tuples = []
    for u_idx in range(len(user_mzs)):
        mz_val = user_mzs[u_idx]
        intensity_val = user_intensities[u_idx]

        if matches[u_idx]:
            i_idx = matched_indices[u_idx]
            ion = all_ions[i_idx]
            result_tuples.append((
                mz_val, intensity_val, ion[0],  # Matched = theoretical mass
                ppm_errors[u_idx],
                ion[1], ion[2], ion[3], ion[4], ion[5], ion[6], ion[7], ion[8]
            ))
        else:
            result_tuples.append((
                mz_val, intensity_val, "No Match", None,
                None, None, None, None, None, None, None, None
            ))

    return result_tuples


# ---------------------------------------------------------------------------
# Synchronous fragmentation + matching wrapper
# ---------------------------------------------------------------------------

def fragment_and_match_peaks_cached(peptide, modifications, max_charge, ppm_tolerance,
                                   selected_ions, selected_internal_ions, user_mz_values,
                                   diagnostic_ions=None, custom_ion_series_list=None,
                                   max_neutral_losses=1, mod_neutral_losses=None):
    """
    Fragment peptide and match peaks.
    Synchronous wrapper for export and relocalisation purposes.

    Returns:
        tuple: (matched_data_df, theoretical_data_df) or None if failed
    """
    try:
        if diagnostic_ions is None:
            diagnostic_ions = []
        if custom_ion_series_list is None:
            custom_ion_series_list = []

        # Step 1: Calculate theoretical fragment ions
        calculated_ions = calculate_fragment_ions(
            peptide_sequence=peptide,
            modifications=modifications,
            max_charge=max_charge,
            ion_types=selected_ions,
            Internal=selected_internal_ions,
            custom_ion_series=custom_ion_series_list,
            max_neutral_losses=max_neutral_losses,
            mod_neutral_losses=mod_neutral_losses
        )

        if calculated_ions.empty:
            return None, None

        # Step 2: Apply filtering
        calculated_ions = filter_ions(calculated_ions)

        # Step 3: Add diagnostic ions if provided
        if diagnostic_ions:
            extra_rows = []
            for (ion_name, mass_val, color) in diagnostic_ions:
                extra_rows.append({
                    "Theoretical Mass": mass_val,
                    "Ion Number": "",
                    "Ion Type": ion_name,
                    "Fragment Sequence": "",
                    "Neutral Loss": "None",
                    "Charge": 1,
                    "Isotope": 0,
                    "Color": color,
                    "Base Type": None,
                    "Ion Series Type": "Diagnostic-Ion"
                })

            if extra_rows:
                df_diagnostic = pd.DataFrame(extra_rows, columns=calculated_ions.columns)
                calculated_ions = pd.concat([calculated_ions, df_diagnostic], ignore_index=True)

        # Store theoretical data
        theoretical_data = calculated_ions.copy()

        # Step 4: Match with experimental data
        matched_data = match_fragment_ions(
            calculated_ions.to_dict(orient='records'),
            user_mz_values,
            ppm_tolerance
        )

        return matched_data, theoretical_data

    except Exception as e:
        logger.error("Fragmentation failed: %s", e)
        traceback.print_exc()
        return None, None
