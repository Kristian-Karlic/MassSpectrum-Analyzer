"""Fragment ion generation, neutral loss calculation, and filtering for peptide fragmentation."""

import re
import pandas as pd
import numpy as np
from itertools import combinations

from .constants import (
    AMINO_ACID_MASSES, SIDECHAIN_LEAVING_GROUPS, V_ION_EXCLUDED_AA,
    H, E, C13, H2O, NH3, NH2, H_ion, H3PO4, CO, SOCH4, C2H2NO, O,
    ion_colors, _SUPERSCRIPT,
)

__all__ = [
    'calculate_fragment_ions', 'filter_ions',
    'generate_multiple_neutral_losses',
    'count_amino_acids_for_neutral_loss', 'get_neutral_loss_mass',
    'process_neutral_losses_and_base_types', 'check_restriction',
    '_nl_tag', '_rm_tag', '_insert_mod_nl_tag', '_clean_base_type',
]


def _clean_base_type(ion_type):
    """Strip charge-variant suffixes (+1, -1) from an ion type string."""
    return ion_type.replace("+1", "").replace("-1", "")


def check_restriction(fragment_seq, restriction_str, base_type, peptide_sequence):
    """
    Check whether a fragment sequence meets the restriction criteria for a
    custom ion series.

    Parameters
    ----------
    fragment_seq : str
        The amino acid sequence of the current fragment.
    restriction_str : str
        Comma-separated restriction tokens, e.g. "E", "E,D", "C-term",
        "N-term,E,D".  Empty string means no restriction (always passes).
        Amino acid tokens use OR logic: the fragment must contain at least
        one of the specified amino acids.
    base_type : str
        The base ion type ("b","y","a","c","x","z","MH").
    peptide_sequence : str
        The full peptide sequence.

    Returns
    -------
    bool
        True if the fragment satisfies the restriction criteria, False otherwise.
    """
    if not restriction_str or not isinstance(restriction_str, str):
        return True  # no restriction -> always pass

    # Determine the sequence to test against
    seq_to_check = fragment_seq
    required_aas = []

    for part in restriction_str.split(","):
        part = part.strip()
        if not part:
            continue

        if part == "C-term":
            # For C-terminal ions (y/x/z/z+1/w/v), use the full peptide sequence
            if base_type in ("y", "x", "z", "z+1", "w", "wa", "wb", "v"):
                seq_to_check = peptide_sequence
            continue

        if part == "N-term":
            # For N-terminal ions (b/a/c/c-1/d), use the full peptide sequence
            if base_type in ("b", "a", "c", "c-1", "d", "da", "db"):
                seq_to_check = peptide_sequence
            continue

        # Single amino acid letter (new format) or old format like "2E"
        aa = part.upper()
        if len(aa) == 1 and aa.isalpha():
            required_aas.append(aa)
        else:
            # Backwards compatibility: old format "2E" -> just treat as "E"
            try:
                aa = part[-1].upper()
                if aa.isalpha():
                    required_aas.append(aa)
            except IndexError:
                continue

    # OR logic: fragment must contain at least one of the required amino acids
    if required_aas:
        seq_upper = seq_to_check.upper()
        if not any(aa in seq_upper for aa in required_aas):
            return False

    return True


def _insert_mod_nl_tag(ion_type, tag):
    """Insert a modification neutral-loss tag into an ion type name.

    Examples:
        'y'   + '*'  -> 'y*'
        'z+1' + '**' -> 'z**+1'
        'c-1' + '~'  -> 'c~-1'
    """
    if ion_type == "z+1":
        return f"z{tag}+1"
    if ion_type == "c-1":
        return f"c{tag}-1"
    return f"{ion_type}{tag}"


def _nl_tag(index: int) -> str:
    """Generate NL tag: NL1='*', NL2='**', NL3='***', NL4='*4', NL5='*5', ..."""
    if index < 3:
        return "*" * (index + 1)
    sup = str(index + 1).translate(_SUPERSCRIPT)
    return f"*{sup}"


def _rm_tag(index: int) -> str:
    """Generate RM tag: RM1='^', RM2='^^', RM3='^^^', RM4='^4', RM5='^5', ..."""
    if index < 3:
        return "^" * (index + 1)
    sup = str(index + 1).translate(_SUPERSCRIPT)
    return f"^{sup}"


# ---------------------------------------------------------------------------
# Neutral-loss helpers
# ---------------------------------------------------------------------------

_LOSS_AA_MAPPING = {
    'H2O': 'STED',      # Serine, Threonine, Glutamic acid, Aspartic acid
    'NH3': 'RKQN',      # Arginine, Lysine, Glutamine, Asparagine
    'H3PO4': 'STY',     # Serine, Threonine, Tyrosine (phosphorylation sites)
    'SOCH4': 'M'         # Methionine (oxidation)
}

_LOSS_MASSES = {
    'H2O': H2O,
    'NH3': NH3,
    'H3PO4': H3PO4,
    'SOCH4': SOCH4,
}

_LOSS_TYPES = ['H2O', 'NH3', 'H3PO4', 'SOCH4']


def count_amino_acids_for_neutral_loss(sequence, loss_type):
    """Count amino acids that can undergo specific neutral losses."""
    relevant_aas = _LOSS_AA_MAPPING.get(loss_type)
    if relevant_aas is None:
        return 0
    return sum(1 for aa in sequence if aa in relevant_aas)


def get_neutral_loss_mass(loss_type):
    """Get the mass of a neutral loss."""
    return _LOSS_MASSES.get(loss_type, 0)


def generate_multiple_neutral_losses(base_mass, sequence, ion_type,
                                     max_losses=5,
                                     selected_ion_types=None,
                                     base_type=None):
    """
    Generate multiple neutral loss variants for a fragment.

    When *selected_ion_types* and *base_type* are provided (custom-ion path),
    only loss types whose corresponding base neutral-loss ion (e.g. "y-H2O")
    is in *selected_ion_types* are generated.  When omitted (standard-ion
    path), all applicable losses are generated.
    """
    neutral_loss_variants = []

    for loss_type in _LOSS_TYPES:
        # Custom-ion guard: skip if corresponding neutral loss ion not selected
        if selected_ion_types is not None and base_type is not None:
            if f"{base_type}-{loss_type}" not in selected_ion_types:
                continue

        max_possible = count_amino_acids_for_neutral_loss(sequence, loss_type)
        max_to_calculate = min(max_possible, max_losses)

        for loss_count in range(1, max_to_calculate + 1):
            loss_mass = get_neutral_loss_mass(loss_type) * loss_count
            modified_mass = base_mass - loss_mass

            if loss_count == 1:
                loss_description = f"{ion_type}-{loss_type}"
            else:
                loss_description = f"{ion_type}-{loss_count}{loss_type}"

            neutral_loss_variants.append((modified_mass, loss_description, loss_type, loss_count))

    return neutral_loss_variants


# ---------------------------------------------------------------------------
# Main fragmentation function
# ---------------------------------------------------------------------------

def calculate_fragment_ions(peptide_sequence,
                             modifications=None,
                             max_charge=2,
                             ion_types=None,
                             Internal=None,
                             custom_ion_series=None,
                             max_neutral_losses=1,
                             calculate_isotopes=True,
                             mod_neutral_losses=None):
    """
    Calculate fragment ion masses for a, b, c, x, y, z ions from a peptide sequence.
    Now includes multiple neutral losses based on amino acid composition.
    Optimized with batch charge/isotope generation.
    """
    if modifications is None:
        modifications = []
    if ion_types is None:
        ion_types = ["y", "b", "MH"]
    if Internal is None:
        Internal = []
    if custom_ion_series is None:
        custom_ion_series = []

    peptide_length = len(peptide_sequence)
    peptide_mass = sum(AMINO_ACID_MASSES[aa] for aa in peptide_sequence)

    fragment_ions = []

    # Compute total modification mass for MH ion (precursor)
    total_mod_mass = sum(mass for mass, site in modifications)

    # Precompute MH_mass — includes all modifications
    MH_mass = peptide_mass + total_mod_mass + H2O

    # Local neutral-loss count cache to avoid repeated counting
    _nl_count_cache = {}
    def _cached_nl_count(seq, loss_type):
        key = (seq, loss_type)
        if key not in _nl_count_cache:
            _nl_count_cache[key] = count_amino_acids_for_neutral_loss(seq, loss_type)
        return _nl_count_cache[key]

    # Helper function to generate all charge states and isotopes at once
    def add_charged_isotopes(mass_val, num, ion_type, seq, loss_type, base_color, base_type, ion_series_type):
        """Generate all charge states and isotopes for a given ion."""
        for charge in range(1, max_charge + 1):
            charged_mass = (mass_val + charge * H_ion) / charge

            # For z+1 ions, also calculate the -1 isotope
            # z+1 has nearly the same mass as z isotope 1, so -1 isotope of z+1 ~ z monoisotopic
            if ion_type == "z+1":
                minus1_isotope_mass = charged_mass - (C13 / charge)
                fragment_ions.append(
                    (minus1_isotope_mass, num, ion_type, seq, loss_type, charge, -1, base_color, base_type, ion_series_type)
                )

            # For c ions, also calculate the -1 isotope for hydrogen transfer detection
            if ion_type == "c":
                minus1_isotope_mass = charged_mass - (C13 / charge)
                fragment_ions.append(
                    (minus1_isotope_mass, num, ion_type, seq, loss_type, charge, -1, base_color, base_type, ion_series_type)
                )

            # Monoisotopic
            fragment_ions.append(
                (charged_mass, num, ion_type, seq, loss_type, charge, 0, base_color, base_type, ion_series_type)
            )
            # Isotopes 1-4 (only when calculate_isotopes is enabled)
            if calculate_isotopes:
                for isotope in range(1, 5):
                    isotope_mass = charged_mass + (isotope * C13 / charge)
                    fragment_ions.append(
                        (isotope_mass, num, ion_type, seq, loss_type, charge, isotope, base_color, base_type, ion_series_type)
                    )

    # Helper to add H2O/NH3 neutral losses for satellite ion variants (d/w/v)
    def _add_satellite_neutral_losses(sat_mass, ion_num, sat_type, seq,
                                      base_key, default_color, ion_series_type):
        for loss_type in ('H2O', 'NH3'):
            nl_ion_type = f"{base_key}-{loss_type}"
            if nl_ion_type not in ion_types:
                continue
            loss_mass = get_neutral_loss_mass(loss_type)
            if _cached_nl_count(seq, loss_type) <= 0:
                continue
            nl_label = f"{sat_type}-{loss_type}"
            nl_color = ion_colors.get(nl_ion_type, default_color)
            add_charged_isotopes(sat_mass - loss_mass, ion_num, nl_label,
                                 seq, loss_type, nl_color, base_key, ion_series_type)

    # Helper: generate standard neutral losses (H2O, NH3, ...) for a
    # mod-series ion, mirroring the custom-ion logic.
    def _add_standard_losses_for_mod_ion(mod_ion_mass, mod_ion_type, num, seq, base_color, clean_base):
        for loss_type in _LOSS_TYPES:
            if f"{clean_base}-{loss_type}" not in ion_types:
                continue
            max_possible = _cached_nl_count(seq, loss_type)
            max_to_calc = min(max_possible, max_neutral_losses)
            for loss_count in range(1, max_to_calc + 1):
                loss_mass = get_neutral_loss_mass(loss_type) * loss_count
                if loss_count == 1:
                    loss_desc = f"{mod_ion_type}-{loss_type}"
                else:
                    loss_desc = f"{mod_ion_type}-{loss_count}{loss_type}"
                add_charged_isotopes(mod_ion_mass - loss_mass, num, loss_desc, seq,
                                     loss_type, base_color, clean_base, "Mod-NL-Series")

    def _apply_mod_nl_to_satellite(sat_type, sat_mass, sat_num, sat_seq,
                                   clean_base, base_color, is_in_frag):
        """Apply mod-specific NL/labile/remainder tags to one satellite ion variant."""
        if not mod_neutral_losses or not modifications:
            return
        for mod_idx, (mod_mass_val, mod_site) in enumerate(modifications):
            nl_cfg = (mod_neutral_losses[mod_idx]
                      if mod_idx < len(mod_neutral_losses) else None)
            if nl_cfg is None or not is_in_frag(mod_site):
                continue
            # Dynamic neutral losses (*, **, ***)
            for nl_i, nl_mass in enumerate(nl_cfg.get("neutral_losses", [])):
                if nl_mass <= 0:
                    continue
                tag = _nl_tag(nl_i)
                nl_ion = _insert_mod_nl_tag(sat_type, tag)
                add_charged_isotopes(sat_mass - nl_mass, sat_num, nl_ion, sat_seq,
                                     f"ModNL{nl_i + 1}", base_color, clean_base, "Mod-NL-Series")
                _add_standard_losses_for_mod_ion(sat_mass - nl_mass, nl_ion,
                                                 sat_num, sat_seq, base_color, clean_base)
            # Labile loss (~)
            if nl_cfg.get("labile_loss", False):
                labile = nl_cfg.get("mod_mass", mod_mass_val)
                if nl_cfg.get("generate_labile_ion", True):
                    labile_ion = _insert_mod_nl_tag(sat_type, "~")
                    add_charged_isotopes(sat_mass - labile, sat_num, labile_ion, sat_seq,
                                         "LabileLoss", base_color, clean_base, "Mod-NL-Series")
                    _add_standard_losses_for_mod_ion(sat_mass - labile, labile_ion,
                                                     sat_num, sat_seq, base_color, clean_base)
                # Remainder ions (^, ^^, ^^^)
                for rm_i, rm_mass in enumerate(nl_cfg.get("remainder_ions", [])):
                    if rm_mass <= 0:
                        continue
                    tag = _rm_tag(rm_i)
                    rm_ion = _insert_mod_nl_tag(sat_type, tag)
                    rm_frag_mass = sat_mass - labile + rm_mass
                    add_charged_isotopes(rm_frag_mass, sat_num, rm_ion, sat_seq,
                                         f"ModRM{rm_i + 1}", base_color, clean_base, "Mod-NL-Series")
                    _add_standard_losses_for_mod_ion(rm_frag_mass, rm_ion,
                                                     sat_num, sat_seq, base_color, clean_base)

    # ---- Main loop: iterate over cleavage positions ----
    prefix_mass = 0.0
    for i in range(1, peptide_length):
        prefix = peptide_sequence[:i]
        suffix = peptide_sequence[i:]

        # Incremental prefix/suffix mass computation
        prefix_mass += AMINO_ACID_MASSES[peptide_sequence[i - 1]]
        suffix_mass = peptide_mass - prefix_mass

        # Apply modifications to the appropriate fragment mass
        prefix_mod_mass = prefix_mass
        suffix_mod_mass = suffix_mass
        for mass, site in modifications:
            if site <= i:
                prefix_mod_mass += mass
            else:
                suffix_mod_mass += mass

        # Calculate base ion masses
        b_mass = prefix_mod_mass
        a_mass = b_mass - CO
        c_mass = prefix_mod_mass + NH3
        y_mass = suffix_mod_mass + H2O
        x_mass = y_mass + (CO - 2*H)
        z_mass = y_mass - NH2

        # Define base ions with their sequences
        base_ions = [
            ("b", b_mass, i, prefix),
            ("a", a_mass, i, prefix),
            ("c", c_mass, i, prefix),
            ("c-1", c_mass - H, i, prefix),
            ("y", y_mass, peptide_length - i, suffix),
            ("x", x_mass, peptide_length - i, suffix),
            ("z", z_mass, peptide_length - i, suffix),
            ("z+1", z_mass + H, peptide_length - i, suffix),
            ("MH", MH_mass, peptide_length, peptide_sequence)
        ]

        # Process each base ion type
        for ion_type, mass_val, num, seq in base_ions:
            if ion_type in ion_types:
                base_color = ion_colors.get(ion_type, "grey")

                # Add the base ion (no neutral loss)
                add_charged_isotopes(mass_val, num, ion_type, seq, "None", base_color, _clean_base_type(ion_type), "Standard-Ion-Series")

                # Generate multiple neutral loss variants
                if ion_type != "MH":
                    neutral_loss_variants = generate_multiple_neutral_losses(mass_val, seq, ion_type, max_losses=max_neutral_losses)
                    for loss_mass, loss_ion_type, loss_type, loss_count in neutral_loss_variants:
                        if loss_ion_type in ion_types:
                            add_charged_isotopes(loss_mass, num, loss_ion_type, seq, loss_type, base_color, _clean_base_type(ion_type), "Standard-Ion-Series")

                # Handle MH neutral losses separately
                elif ion_type == "MH":
                    simple_mh_losses = [
                        ("MH-H2O", mass_val - H2O, "H2O"),
                        ("MH-NH3", mass_val - NH3, "NH3")
                    ]

                    for loss_ion_type, loss_mass, loss_type in simple_mh_losses:
                        if loss_ion_type in ion_types:
                            add_charged_isotopes(loss_mass, num, loss_ion_type, seq, loss_type, base_color, "MH", "Standard-Ion-Series")

        # ---- Satellite ions: d (from a), w (from z), v (from y) ----
        # d ion: N-terminal, sidechain loss from last residue of prefix
        cleavage_aa_n = peptide_sequence[i - 1]  # last AA of prefix (N-terminal side)
        leaving_groups_d = SIDECHAIN_LEAVING_GROUPS.get(cleavage_aa_n, [])
        if "d" in ion_types:
            for suffix_label, leaving_mass in leaving_groups_d:
                d_type = f"d{suffix_label}"
                d_mass = a_mass - leaving_mass + H
                base_color = ion_colors.get(d_type, "teal")
                add_charged_isotopes(d_mass, i, d_type, prefix, "None", base_color, "d", "Satellite-Ion-Series")
                _add_satellite_neutral_losses(d_mass, i, d_type, prefix, "d", "teal", "Satellite-Ion-Series")

        # w ion: C-terminal, sidechain loss from first residue of suffix
        cleavage_aa_c = peptide_sequence[i]  # first AA of suffix (C-terminal side)
        leaving_groups_w = SIDECHAIN_LEAVING_GROUPS.get(cleavage_aa_c, [])
        if "w" in ion_types:
            for suffix_label, leaving_mass in leaving_groups_w:
                w_type = f"w{suffix_label}"
                w_mass = z_mass - leaving_mass
                base_color = ion_colors.get(w_type, "darkcyan")
                add_charged_isotopes(w_mass, peptide_length - i, w_type, suffix, "None", base_color, "w", "Satellite-Ion-Series")
                _add_satellite_neutral_losses(w_mass, peptide_length - i, w_type, suffix, "w", "darkcyan", "Satellite-Ion-Series")

        # v ion: C-terminal, full sidechain loss from y ion
        if "v" in ion_types and cleavage_aa_c not in V_ION_EXCLUDED_AA:
            v_mass_base = suffix_mod_mass - AMINO_ACID_MASSES[cleavage_aa_c] + C2H2NO + O
            # If the first AA of suffix has a modification, it is lost with the sidechain
            v_mod_mass = v_mass_base
            for mod_mass, mod_site in modifications:
                if mod_site == i + 1:
                    v_mod_mass -= mod_mass
            base_color = ion_colors.get("v", "magenta")
            add_charged_isotopes(v_mod_mass, peptide_length - i, "v", suffix, "None", base_color, "v", "Satellite-Ion-Series")
            _add_satellite_neutral_losses(v_mod_mass, peptide_length - i, "v", suffix, "v", "magenta", "Satellite-Ion-Series")

        # Handle custom ion series with conditional neutral losses
        custom_ion_series_types_for_this_fragment = []
        base_ion_dict = {
            "b": b_mass, "a": a_mass, "c": c_mass, "c-1": c_mass - H,
            "y": y_mass, "x": x_mass, "z": z_mass, "z+1": z_mass + H,
            "MH": MH_mass
        }

        for custom in custom_ion_series:
            custom_base_type = custom["base"]
            ion_name = custom["name"]
            offset = custom["offset"]
            ion_color = custom["color"]
            restriction = custom.get("restriction", "")

            if custom_base_type in ("b", "a", "c", "c-1"):
                fragment_seq = prefix
                ion_number = i
            elif custom_base_type in ("y", "x", "z", "z+1"):
                fragment_seq = suffix
                ion_number = peptide_length - i
            elif custom_base_type == "MH":
                fragment_seq = peptide_sequence
                ion_number = peptide_length
            else:
                continue

            # Apply restriction filter
            if not check_restriction(fragment_seq, restriction, custom_base_type, peptide_sequence):
                continue

            custom_base_mass = base_ion_dict[custom_base_type]
            custom_mass = custom_base_mass + offset
            custom_ion_series_types_for_this_fragment.append(
                (ion_name, custom_mass, ion_number, fragment_seq, ion_color, custom_base_type)
            )

        # Process custom ions with conditional neutral losses
        for ion_type, mass_val, num, seq, ion_color, custom_base_type in custom_ion_series_types_for_this_fragment:
            # Add base custom ion (no neutral loss)
            add_charged_isotopes(mass_val, num, ion_type, seq, "None", ion_color, custom_base_type, "Custom-Ion-Series")

            # Only add neutral loss variants if the corresponding neutral loss ion type is selected
            neutral_loss_variants = generate_multiple_neutral_losses(
                mass_val, seq, ion_type, max_losses=max_neutral_losses,
                selected_ion_types=ion_types, base_type=custom_base_type
            )

            for loss_mass, loss_ion_type, loss_type, loss_count in neutral_loss_variants:
                add_charged_isotopes(loss_mass, num, loss_ion_type, seq, loss_type, ion_color, custom_base_type, "Custom-Ion-Series")

        # ----------------------------------------------------------
        # Modification-specific neutral losses (*, **, ***, ~) and remainder ions (^, ^^, ^^^)
        # ----------------------------------------------------------
        if mod_neutral_losses and modifications:
            for mod_idx, (mod_mass, mod_site) in enumerate(modifications):
                nl_config = mod_neutral_losses[mod_idx] if mod_idx < len(mod_neutral_losses) else None
                if nl_config is None:
                    continue

                for ion_type, mass_val, num, seq in base_ions:
                    if ion_type not in ion_types:
                        continue

                    # Check if this fragment contains the modification site
                    if ion_type in ("b", "a", "c", "c-1"):
                        if mod_site > i:  # mod not in this N-terminal fragment
                            continue
                    elif ion_type in ("y", "x", "z", "z+1"):
                        if mod_site <= i:  # mod not in this C-terminal fragment
                            continue
                    # MH always contains all mods - no check needed

                    base_color = ion_colors.get(ion_type, "grey")
                    clean_base = _clean_base_type(ion_type)

                    # Dynamic neutral losses from list
                    nl_list = nl_config.get("neutral_losses", [])
                    for nl_idx, nl_mass in enumerate(nl_list):
                        if nl_mass <= 0:
                            continue
                        tag = _nl_tag(nl_idx)
                        label = f"ModNL{nl_idx + 1}"
                        nl_ion_type = _insert_mod_nl_tag(ion_type, tag)
                        add_charged_isotopes(mass_val - nl_mass, num, nl_ion_type, seq,
                                             label, base_color, clean_base, "Mod-NL-Series")
                        _add_standard_losses_for_mod_ion(mass_val - nl_mass, nl_ion_type, num, seq, base_color, clean_base)

                    # Labile loss (~) - entire modification mass removed
                    if nl_config.get("labile_loss", False):
                        labile_mass = nl_config.get("mod_mass", mod_mass)
                        if nl_config.get("generate_labile_ion", True):
                            nl_ion_type = _insert_mod_nl_tag(ion_type, "~")
                            add_charged_isotopes(mass_val - labile_mass, num, nl_ion_type, seq,
                                                 "LabileLoss", base_color, clean_base, "Mod-NL-Series")
                            _add_standard_losses_for_mod_ion(mass_val - labile_mass, nl_ion_type, num, seq, base_color, clean_base)

                        # Remainder ions (^, ^^, ^^^, ...)
                        rm_list = nl_config.get("remainder_ions", [])
                        for rm_idx, rm_mass in enumerate(rm_list):
                            if rm_mass <= 0:
                                continue
                            tag = _rm_tag(rm_idx)
                            label = f"ModRM{rm_idx + 1}"
                            rm_ion_type = _insert_mod_nl_tag(ion_type, tag)
                            rm_fragment_mass = mass_val - labile_mass + rm_mass
                            add_charged_isotopes(rm_fragment_mass, num, rm_ion_type, seq,
                                                 label, base_color, clean_base, "Mod-NL-Series")
                            _add_standard_losses_for_mod_ion(rm_fragment_mass, rm_ion_type, num, seq, base_color, clean_base)

            # ----------------------------------------------------------
            # Cumulative (stacked) mod neutral losses (2*,3*,2~, etc.)
            # When a fragment contains 2+ mod sites with active NLs,
            # generate combined losses: e.g. 2xNL1 for double AETMA.
            # ----------------------------------------------------------
            for ion_type, mass_val, num, seq in base_ions:
                if ion_type not in ion_types:
                    continue

                # Collect all NL configs for mods within this fragment
                configs_in_frag = []
                for mod_idx, (mod_mass_val, mod_site) in enumerate(modifications):
                    nl_cfg = mod_neutral_losses[mod_idx] if mod_idx < len(mod_neutral_losses) else None
                    if nl_cfg is None:
                        continue
                    if ion_type in ("b", "a", "c", "c-1"):
                        if mod_site > i:
                            continue
                    elif ion_type in ("y", "x", "z", "z+1"):
                        if mod_site <= i:
                            continue
                    configs_in_frag.append(nl_cfg)

                if len(configs_in_frag) < 2:
                    continue

                base_color = ion_colors.get(ion_type, "grey")
                clean_base = _clean_base_type(ion_type)

                # Dynamic NL type definitions from actual NL counts
                max_nl_count = max(
                    (len(cfg.get("neutral_losses", [])) for cfg in configs_in_frag),
                    default=0
                )
                for nl_idx in range(max_nl_count):
                    masses_for_nl = [
                        cfg["neutral_losses"][nl_idx]
                        for cfg in configs_in_frag
                        if len(cfg.get("neutral_losses", [])) > nl_idx
                        and cfg["neutral_losses"][nl_idx] > 0
                    ]
                    if len(masses_for_nl) < 2:
                        continue
                    tag = _nl_tag(nl_idx)
                    nl_label = f"ModNL{nl_idx + 1}"
                    for combo_size in range(2, len(masses_for_nl) + 1):
                        seen_sums = set()
                        for combo in combinations(masses_for_nl, combo_size):
                            total_loss = round(sum(combo), 6)
                            if total_loss in seen_sums:
                                continue
                            seen_sums.add(total_loss)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"{tag}{sup}"
                            cumul_nl_label = f"{nl_label}x{combo_size}"
                            nl_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            add_charged_isotopes(mass_val - total_loss, num, nl_ion_type, seq,
                                                 cumul_nl_label, base_color, clean_base, "Mod-NL-Series")
                            _add_standard_losses_for_mod_ion(mass_val - total_loss, nl_ion_type, num, seq, base_color, clean_base)

                # Cumulative labile losses
                labile_masses = [cfg.get("mod_mass", 0) for cfg in configs_in_frag
                                 if cfg.get("labile_loss", False) and cfg.get("generate_labile_ion", True)]
                if len(labile_masses) >= 2:
                    for combo_size in range(2, len(labile_masses) + 1):
                        seen_sums = set()
                        for combo in combinations(labile_masses, combo_size):
                            total_loss = round(sum(combo), 6)
                            if total_loss in seen_sums:
                                continue
                            seen_sums.add(total_loss)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"~{sup}"
                            cumul_labile_label = f"LabileLossx{combo_size}"
                            nl_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            add_charged_isotopes(mass_val - total_loss, num, nl_ion_type, seq,
                                                 cumul_labile_label, base_color, clean_base, "Mod-NL-Series")
                            _add_standard_losses_for_mod_ion(mass_val - total_loss, nl_ion_type, num, seq, base_color, clean_base)

                # Cumulative remainder ions
                max_rm_count = max(
                    (len(cfg.get("remainder_ions", []))
                     for cfg in configs_in_frag if cfg.get("labile_loss", False)),
                    default=0
                )
                for rm_idx in range(max_rm_count):
                    rm_data = []  # (rm_mass, mod_mass) pairs
                    for cfg in configs_in_frag:
                        if not cfg.get("labile_loss", False):
                            continue
                        rms = cfg.get("remainder_ions", [])
                        if len(rms) > rm_idx and rms[rm_idx] > 0:
                            rm_data.append((rms[rm_idx], cfg.get("mod_mass", 0)))
                    if len(rm_data) < 2:
                        continue
                    rm_tag_base = _rm_tag(rm_idx)
                    rm_label_base = f"ModRM{rm_idx + 1}"
                    for combo_size in range(2, len(rm_data) + 1):
                        seen_keys = set()
                        for combo in combinations(rm_data, combo_size):
                            total_mod_loss = round(sum(m for _, m in combo), 6)
                            total_rm_add = round(sum(r for r, _ in combo), 6)
                            key = (total_mod_loss, total_rm_add)
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"{rm_tag_base}{sup}"
                            cumul_label = f"{rm_label_base}x{combo_size}"
                            rm_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            cumul_rm_mass = mass_val - total_mod_loss + total_rm_add
                            add_charged_isotopes(cumul_rm_mass, num, rm_ion_type, seq,
                                                 cumul_label, base_color, clean_base, "Mod-NL-Series")
                            _add_standard_losses_for_mod_ion(cumul_rm_mass, rm_ion_type, num, seq, base_color, clean_base)

        # Mod-NL / labile / remainder for satellite ions at cleavage position i
        if mod_neutral_losses and modifications:
            # d ions - N-terminal: mod must be within prefix (mod_site <= i)
            if "d" in ion_types:
                for sfx, lv_mass in leaving_groups_d:
                    d_type = f"d{sfx}"
                    _apply_mod_nl_to_satellite(
                        d_type, a_mass - lv_mass + H, i, prefix,
                        "d", ion_colors.get(d_type, "teal"),
                        lambda ms, _i=i: ms <= _i,
                    )
            # w ions - C-terminal: mod must be within suffix (mod_site > i)
            if "w" in ion_types:
                for sfx, lv_mass in leaving_groups_w:
                    w_type = f"w{sfx}"
                    _apply_mod_nl_to_satellite(
                        w_type, z_mass - lv_mass, peptide_length - i, suffix,
                        "w", ion_colors.get(w_type, "darkcyan"),
                        lambda ms, _i=i: ms > _i,
                    )
            # v ions - mod_site > i+1 (position i+1's sidechain is already removed
            # from v_mod_mass, so only mods at i+2 and beyond are still in the ion)
            if "v" in ion_types and cleavage_aa_c not in V_ION_EXCLUDED_AA:
                _apply_mod_nl_to_satellite(
                    "v", v_mod_mass, peptide_length - i, suffix,
                    "v", ion_colors.get("v", "magenta"),
                    lambda ms, _i=i: ms > _i + 1,
                )

        # Internal fragments
        for j in range(i+1, peptide_length):
            internal_seq = peptide_sequence[i:j]

            if len(internal_seq) == 1:
                continue

            internal_mass = sum(AMINO_ACID_MASSES[aa] for aa in internal_seq)

            for mass, site in modifications:
                if i < site < j:
                    internal_mass += mass

            for ion_type in Internal:
                ion_mass = internal_mass + {
                    "b": H_ion,
                    "a": H_ion - CO,
                }.get(ion_type, 0)

                position_notation = f"{i+1}-{j}"

                # Only generate charge state 1 for internal fragments
                charge = 1
                charged_mass = (ion_mass + (charge - 1 - E) * H_ion) / charge
                fragment_ions.append((charged_mass, position_notation, f"int-{ion_type}", internal_seq, "None", charge, 0, ion_colors.get(ion_type, "grey"), ion_type, "Internal-Ion"))

                if calculate_isotopes:
                    for isotope in range(1, 5):
                        isotope_mass = charged_mass + (isotope * C13 / charge)
                        fragment_ions.append((isotope_mass, position_notation, f"int-{ion_type}", internal_seq, "None", charge, isotope, ion_colors.get(ion_type, "grey"), ion_type, "Internal-Ion"))

    # ---- Endpoint satellite ions (position n) ----
    # d at position n: sidechain loss from last residue (a_n = full peptide - CO)
    last_aa = peptide_sequence[-1]
    leaving_groups_d_n = SIDECHAIN_LEAVING_GROUPS.get(last_aa, [])
    if "d" in ion_types:
        a_n_mass = peptide_mass - CO  # peptide_mass already includes all mods
        for suffix_label, leaving_mass in leaving_groups_d_n:
            d_type = f"d{suffix_label}"
            d_mass = a_n_mass - leaving_mass + H
            base_color = ion_colors.get(d_type, "teal")
            add_charged_isotopes(d_mass, peptide_length, d_type, peptide_sequence,
                                 "None", base_color, "d", "Satellite-Ion-Series")
            _add_satellite_neutral_losses(d_mass, peptide_length, d_type, peptide_sequence, "d", "teal", "Satellite-Ion-Series")

    # w/v at position n: sidechain loss from first residue (z_n / y_n of full peptide)
    first_aa = peptide_sequence[0]
    full_suffix_mass = peptide_mass  # includes all modifications
    z_n_mass = full_suffix_mass + H2O - NH2

    leaving_groups_w_n = SIDECHAIN_LEAVING_GROUPS.get(first_aa, [])
    if "w" in ion_types:
        for suffix_label, leaving_mass in leaving_groups_w_n:
            w_type = f"w{suffix_label}"
            w_mass = z_n_mass - leaving_mass
            base_color = ion_colors.get(w_type, "darkcyan")
            add_charged_isotopes(w_mass, peptide_length, w_type, peptide_sequence,
                                 "None", base_color, "w", "Satellite-Ion-Series")
            _add_satellite_neutral_losses(w_mass, peptide_length, w_type, peptide_sequence, "w", "darkcyan", "Satellite-Ion-Series")

    if "v" in ion_types and first_aa not in V_ION_EXCLUDED_AA:
        v_mass_base = full_suffix_mass - AMINO_ACID_MASSES[first_aa] + C2H2NO + O
        v_mod_mass = v_mass_base
        for mod_mass_val, mod_site in modifications:
            if mod_site == 1:
                v_mod_mass -= mod_mass_val
        base_color = ion_colors.get("v", "magenta")
        add_charged_isotopes(v_mod_mass, peptide_length, "v", peptide_sequence,
                             "None", base_color, "v", "Satellite-Ion-Series")
        _add_satellite_neutral_losses(v_mod_mass, peptide_length, "v", peptide_sequence, "v", "magenta", "Satellite-Ion-Series")

    # Mod-NL / labile / remainder for endpoint satellite ions (position n)
    if mod_neutral_losses and modifications:
        # Endpoint d - all mods are in the full-peptide N-terminal ion
        if "d" in ion_types:
            a_n_end = peptide_mass - CO
            for sfx, lv_mass in leaving_groups_d_n:
                d_type = f"d{sfx}"
                _apply_mod_nl_to_satellite(
                    d_type, a_n_end - lv_mass + H, peptide_length, peptide_sequence,
                    "d", ion_colors.get(d_type, "teal"),
                    lambda ms: True,
                )
        # Endpoint w - all mods are in the full-peptide C-terminal ion
        if "w" in ion_types:
            for sfx, lv_mass in leaving_groups_w_n:
                w_type = f"w{sfx}"
                _apply_mod_nl_to_satellite(
                    w_type, z_n_mass - lv_mass, peptide_length, peptide_sequence,
                    "w", ion_colors.get(w_type, "darkcyan"),
                    lambda ms: True,
                )
        # Endpoint v - first residue's sidechain (and mod at site 1) already removed
        if "v" in ion_types and first_aa not in V_ION_EXCLUDED_AA:
            _apply_mod_nl_to_satellite(
                "v", v_mod_mass, peptide_length, peptide_sequence,
                "v", ion_colors.get("v", "magenta"),
                lambda ms: ms > 1,
            )

    # Convert to DataFrame with updated columns
    df = pd.DataFrame(fragment_ions, columns=["Theoretical Mass", "Ion Number", "Ion Type", "Fragment Sequence", "Neutral Loss", "Charge", "Isotope", "Color", "Base Type", "Ion Series Type"])
    df = df.sort_values(by=["Ion Type", "Ion Number"])
    return df


# ---------------------------------------------------------------------------
# Post-processing / filtering
# ---------------------------------------------------------------------------

def process_neutral_losses_and_base_types(df):
    """
    Process Base Type column to extract neutral losses and clean base types.
    Now handles multiple losses like y-2H2O, y-3NH3, etc.
    Fully vectorized for performance.
    """
    if df.empty:
        return df

    # Define known neutral losses
    neutral_losses = ['H2O', 'NH3', 'H3PO4', 'SOCH4']

    df = df.copy()

    # Pre-convert to strings
    base_type = df['Base Type'].astype(str)
    current_neutral_loss = df['Neutral Loss'].fillna('None').astype(str)

    # Track which rows need updates
    detected_loss = pd.Series(None, index=df.index, dtype=object)
    clean_base_type = base_type.copy()

    # Only process rows where we might find losses (not Custom-Ion-Series or already have loss info)
    needs_processing = (base_type.str.contains('-', na=False))

    if needs_processing.any():
        for loss in neutral_losses:
            # Pattern to match -H2O, -2H2O, -3H2O, etc.
            pattern = rf'-\d*{re.escape(loss)}'

            # Find rows with this loss pattern
            has_loss = base_type.str.contains(pattern, regex=True, na=False) & needs_processing

            if has_loss.any():
                # Update detected loss
                detected_loss[has_loss] = loss
                # Remove the loss pattern from base type
                clean_base_type[has_loss] = base_type[has_loss].str.replace(pattern, '', regex=True)
                # Don't process these rows again
                needs_processing &= ~has_loss

    # Update columns where we detected a loss
    has_detected_loss = detected_loss.notna()
    needs_update = has_detected_loss & (current_neutral_loss.isin(['None', 'nan', '', 'NaN']))
    df.loc[needs_update, 'Neutral Loss'] = detected_loss[needs_update]
    df.loc[has_detected_loss, 'Base Type'] = clean_base_type[has_detected_loss]

    # Handle ion variants
    base_type_replacements = {'z+1': 'z', 'c-1': 'c', 'wa': 'w', 'wb': 'w', 'da': 'd', 'db': 'd'}
    df['Base Type'] = df['Base Type'].replace(base_type_replacements)

    return df


def filter_ions(df):
    """
    Apply filtering conditions for neutral losses.
    Now handles multiple neutral losses with improved logic.
    Fully vectorized for maximum speed.
    """
    if df.empty:
        return df

    # Initialize keep mask (all True)
    keep_mask = pd.Series(True, index=df.index)

    # Pre-compute string columns as strings
    fragment_seq = df['Fragment Sequence'].astype(str)
    neutral_loss = df['Neutral Loss'].fillna("None").astype(str)
    ion_type = df['Ion Type'].astype(str)

    # Quick early filtering - if no neutral loss, skip complex checks
    has_no_loss = (neutral_loss == "None") | neutral_loss.isna()

    # Modification-specific neutral losses are pre-validated during generation
    # (fragment must contain the modification site).  Skip amino-acid checks.
    # Includes cumulative labels like ModNL1x2, LabileLossx3, etc.
    is_mod_nl = neutral_loss.str.startswith(("ModNL", "LabileLoss", "ModRM"), na=False)
    skip_aa_checks = has_no_loss | is_mod_nl

    # For rows with neutral losses, extract loss information
    loss_count = pd.Series(0, index=df.index)
    loss_type = pd.Series(None, index=df.index, dtype=object)

    # Only process rows that actually have standard losses (not mod-NL)
    loss_indices = df.index[~skip_aa_checks]
    if len(loss_indices) > 0:
        for idx in loss_indices:
            ion_t = ion_type[idx]
            neut_loss = neutral_loss[idx]
            match = re.search(r'-(\d*)(' + re.escape(neut_loss) + ')', ion_t)
            if match:
                count_str = match.group(1)
                loss_t = match.group(2)
                count = int(count_str) if count_str else 1
                loss_count[idx] = count
                loss_type[idx] = loss_t

                # Check if loss count exceeds maximum possible
                if count > 0:
                    max_possible = count_amino_acids_for_neutral_loss(fragment_seq[idx], loss_t)
                    if count > max_possible:
                        keep_mask[idx] = False

    # Vectorized amino acid checks for neutral losses
    has_loss = loss_type.notna()

    # H2O loss requires STED
    h2o_mask = has_loss & (loss_type == 'H2O')
    if h2o_mask.any():
        has_sted = fragment_seq.str.contains('[STED]', regex=True, na=False)
        keep_mask &= ~(h2o_mask & ~has_sted)

    # NH3 loss requires RKQN
    nh3_mask = has_loss & (loss_type == 'NH3')
    if nh3_mask.any():
        has_rkqn = fragment_seq.str.contains('[RKQN]', regex=True, na=False)
        keep_mask &= ~(nh3_mask & ~has_rkqn)

    # H3PO4 loss requires STY
    h3po4_mask = has_loss & (loss_type == 'H3PO4')
    if h3po4_mask.any():
        has_sty = fragment_seq.str.contains('[STY]', regex=True, na=False)
        keep_mask &= ~(h3po4_mask & ~has_sty)

    # SOCH4 loss requires M
    soch4_mask = has_loss & (loss_type == 'SOCH4')
    if soch4_mask.any():
        has_m = fragment_seq.str.contains('M', regex=False, na=False)
        keep_mask &= ~(soch4_mask & ~has_m)

    # z, z+1 ions starting with P
    z_ion_mask = ion_type.str.startswith('z', na=False)
    if z_ion_mask.any():
        starts_p = fragment_seq.str.startswith('P', na=False)
        keep_mask &= ~(z_ion_mask & starts_p)

    # w/wa/wb ions starting with P (derived from z)
    w_ion_mask = ion_type.str.startswith('w', na=False)
    if w_ion_mask.any():
        starts_p = fragment_seq.str.startswith('P', na=False)
        keep_mask &= ~(w_ion_mask & starts_p)

    # c-based ions ending with P
    c_ion_mask = ion_type.str.contains('c', regex=False, na=False)
    if c_ion_mask.any():
        ends_p = fragment_seq.str.endswith('P', na=False)
        keep_mask &= ~(c_ion_mask & ends_p)

    # Apply filtering
    df = df[keep_mask].copy()
    df = process_neutral_losses_and_base_types(df)
    df = df.drop_duplicates()

    return df
