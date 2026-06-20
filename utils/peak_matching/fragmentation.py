"""Fragment ion generation, neutral loss calculation, and filtering for peptide fragmentation."""

import re
import pandas as pd
from itertools import combinations

from .constants import (
    AMINO_ACID_MASSES,
    SIDECHAIN_LEAVING_GROUPS,
    V_ION_EXCLUDED_AA,
    MONOSACCHARIDE_MASSES,
    MONOSACCHARIDE_SHORT,
    H,
    E,
    C13,
    H2O,
    NH3,
    NH2,
    H_ion,
    H3PO4,
    CO,
    SOCH4,
    C2H2NO,
    O,
    ion_colors,
    _SUPERSCRIPT,
)

__all__ = [
    "calculate_fragment_ions",
    "filter_ions",
    "generate_multiple_neutral_losses",
    "count_amino_acids_for_neutral_loss",
    "get_neutral_loss_mass",
    "process_neutral_losses_and_base_types",
    "check_restriction",
    "_nl_tag",
    "_rm_tag",
    "_insert_mod_nl_tag",
    "_clean_base_type",
    "_build_modified_fragment",
    "parse_glycan_composition",
    "glycan_composition_mass",
    "generate_glycan_sub_compositions",
    "glycan_composition_label",
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
    "H2O": "STED",  # Serine, Threonine, Glutamic acid, Aspartic acid
    "NH3": "RKQN",  # Arginine, Lysine, Glutamine, Asparagine
    "H3PO4": "STY",  # Serine, Threonine, Tyrosine (phosphorylation sites)
    "SOCH4": "M",  # Methionine (oxidation)
}

_LOSS_MASSES = {
    "H2O": H2O,
    "NH3": NH3,
    "H3PO4": H3PO4,
    "SOCH4": SOCH4,
}

_LOSS_TYPES = ["H2O", "NH3", "H3PO4", "SOCH4"]


def count_amino_acids_for_neutral_loss(sequence, loss_type):
    """Count amino acids that can undergo specific neutral losses."""
    relevant_aas = _LOSS_AA_MAPPING.get(loss_type)
    if relevant_aas is None:
        return 0
    return sum(1 for aa in sequence if aa in relevant_aas)


def get_neutral_loss_mass(loss_type):
    """Get the mass of a neutral loss."""
    return _LOSS_MASSES.get(loss_type, 0)


def generate_multiple_neutral_losses(
    base_mass, sequence, ion_type, max_losses=5, selected_ion_types=None, base_type=None
):
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

            neutral_loss_variants.append(
                (modified_mass, loss_description, loss_type, loss_count)
            )

    return neutral_loss_variants


# ---------------------------------------------------------------------------
# Main fragmentation function
# ---------------------------------------------------------------------------


def _build_modified_fragment(seq, pos_mass_pairs):
    """Annotate a fragment sequence string with modification masses.

    Args:
        seq: Plain amino acid sequence (str), e.g. 'ALQHVLKDQ'
        pos_mass_pairs: Iterable of (0-indexed position in seq, mass) tuples.
                        Multiple entries at the same position are summed.

    Returns:
        Annotated string, e.g. 'ALQHVLK[+28.0313]D[+84.1054]Q'
        Returns unmodified seq if pos_mass_pairs is empty or None.
    """
    if not pos_mass_pairs:
        return seq

    by_pos = {}
    for pos, mass in pos_mass_pairs:
        if 0 <= pos < len(seq):
            by_pos[pos] = by_pos.get(pos, 0.0) + mass

    if not by_pos:
        return seq

    result = []
    for idx, aa in enumerate(seq):
        result.append(aa)
        if idx in by_pos:
            m = round(by_pos[idx], 4)
            sign = "+" if m >= 0 else ""
            result.append(f"[{sign}{m}]")
    return "".join(result)


# ---------------------------------------------------------------------------
# Glycan Y-ion helpers
# ---------------------------------------------------------------------------


def parse_glycan_composition(composition_str, extra_masses=None):
    """Parse a glycan composition string into a dict of monosaccharide counts.

    Example: 'Hex(5)HexNAc(2)NeuAc(1)' -> {'Hex': 5, 'HexNAc': 2, 'NeuAc': 1}
    extra_masses: optional dict of additional monosaccharide masses (e.g. custom entries).
    """
    known = set(MONOSACCHARIDE_MASSES)
    if extra_masses:
        known |= set(extra_masses)
    tokens = re.findall(r"([A-Za-z]+)\((\d+)\)", composition_str)
    result = {}
    for name, count in tokens:
        if name in known:
            n = int(count)
            if n > 0:
                result[name] = result.get(name, 0) + n
    return result


def glycan_composition_mass(composition, extra_masses=None):
    """Return the total residue mass (Da) for a monosaccharide composition dict."""
    masses = MONOSACCHARIDE_MASSES
    if extra_masses:
        masses = {**masses, **extra_masses}
    return sum(masses[name] * count for name, count in composition.items())


def generate_glycan_sub_compositions(full_composition):
    """Enumerate all sub-compositions (0..n_i for each monosaccharide type).

    Returns a list of composition dicts representing every possible partial
    glycan, including the empty composition (Y0 / bare peptide).
    The full composition itself is excluded (it equals the intact MH ion).
    """
    names = list(full_composition.keys())
    counts = [full_composition[n] for n in names]

    def _recurse(idx, current):
        if idx == len(names):
            comp = {names[i]: current[i] for i in range(len(names)) if current[i] > 0}
            yield comp
            return
        for c in range(counts[idx] + 1):
            current[idx] = c
            yield from _recurse(idx + 1, current)

    full_total = sum(counts)
    for sub in _recurse(0, [0] * len(names)):
        # Skip the full-glycan composition (it equals the precursor MH)
        if sum(sub.values()) < full_total:
            yield sub


def glycan_composition_label(composition, short=True, extra_shorts=None):
    """Build a human-readable label for a glycan composition.

    short=True  -> 'H5N2A1'  (compact, for on-spectrum display)
    short=False -> 'Hex5HexNAc2NeuAc1' (full, for tooltips / export)
    Returns 'Y0' when the composition is empty (bare peptide).
    extra_shorts: optional dict of custom monosaccharide shorthand codes.
    """
    if not composition:
        return "Y0"
    shorts = MONOSACCHARIDE_SHORT
    if extra_shorts:
        shorts = {**shorts, **extra_shorts}
    preferred = ("HexNAc", "Hex", "Fuc", "NeuAc", "NeuGc", "Pent")
    parts = []
    for name in preferred:
        n = composition.get(name, 0)
        if n == 0:
            continue
        parts.append(f"{shorts.get(name, name[:2])}{n}" if short else f"{name}{n}")
    for name, n in composition.items():
        if name not in preferred and n > 0:
            parts.append(f"{shorts.get(name, name[:2])}{n}" if short else f"{name}{n}")
    return "".join(parts) if parts else "Y0"


def calculate_fragment_ions(
    peptide_sequence,
    modifications=None,
    max_charge=2,
    ion_types=None,
    Internal=None,
    custom_ion_series=None,
    max_neutral_losses=1,
    calculate_isotopes=True,
    isotope_max=4,
    mod_neutral_losses=None,
    glycan_composition_str=None,
    glycan_max_charge=None,
):
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
    def add_charged_isotopes(
        mass_val,
        num,
        ion_type,
        seq,
        loss_type,
        base_color,
        base_type,
        ion_series_type,
        modified_fragment=None,
    ):
        """Generate all charge states and isotopes for a given ion."""
        if modified_fragment is None:
            modified_fragment = seq
        charge_limit = max_charge + 1 if base_type == "MH" else max_charge
        for charge in range(1, charge_limit):
            charged_mass = (mass_val + charge * H_ion) / charge

            # For z+1 ions, also calculate the -1 isotope
            # z+1 has nearly the same mass as z isotope 1, so -1 isotope of z+1 ~ z monoisotopic
            if ion_type == "z+1":
                minus1_isotope_mass = charged_mass - (C13 / charge)
                fragment_ions.append(
                    (
                        minus1_isotope_mass,
                        num,
                        ion_type,
                        seq,
                        loss_type,
                        charge,
                        -1,
                        base_color,
                        base_type,
                        ion_series_type,
                        modified_fragment,
                    )
                )

            # For c ions, also calculate the -1 isotope for hydrogen transfer detection
            if ion_type == "c":
                minus1_isotope_mass = charged_mass - (C13 / charge)
                fragment_ions.append(
                    (
                        minus1_isotope_mass,
                        num,
                        ion_type,
                        seq,
                        loss_type,
                        charge,
                        -1,
                        base_color,
                        base_type,
                        ion_series_type,
                        modified_fragment,
                    )
                )

            # Monoisotopic
            fragment_ions.append(
                (
                    charged_mass,
                    num,
                    ion_type,
                    seq,
                    loss_type,
                    charge,
                    0,
                    base_color,
                    base_type,
                    ion_series_type,
                    modified_fragment,
                )
            )
            # Isotopes 1-N (only when calculate_isotopes is enabled)
            if calculate_isotopes:
                for isotope in range(1, isotope_max + 1):
                    isotope_mass = charged_mass + (isotope * C13 / charge)
                    fragment_ions.append(
                        (
                            isotope_mass,
                            num,
                            ion_type,
                            seq,
                            loss_type,
                            charge,
                            isotope,
                            base_color,
                            base_type,
                            ion_series_type,
                            modified_fragment,
                        )
                    )

    # Helper to add H2O/NH3 neutral losses for satellite ion variants (d/w/v)
    def _add_satellite_neutral_losses(
        sat_mass,
        ion_num,
        sat_type,
        seq,
        base_key,
        default_color,
        ion_series_type,
        modified_fragment=None,
    ):
        for loss_type in ("H2O", "NH3"):
            nl_ion_type = f"{base_key}-{loss_type}"
            if nl_ion_type not in ion_types:
                continue
            loss_mass = get_neutral_loss_mass(loss_type)
            if _cached_nl_count(seq, loss_type) <= 0:
                continue
            nl_label = f"{sat_type}-{loss_type}"
            nl_color = ion_colors.get(nl_ion_type, default_color)
            add_charged_isotopes(
                sat_mass - loss_mass,
                ion_num,
                nl_label,
                seq,
                loss_type,
                nl_color,
                base_key,
                ion_series_type,
                modified_fragment=modified_fragment,
            )

    # Helper: generate standard neutral losses (H2O, NH3, ...) for a
    # mod-series ion, mirroring the custom-ion logic.
    def _add_standard_losses_for_mod_ion(
        mod_ion_mass,
        mod_ion_type,
        num,
        seq,
        base_color,
        clean_base,
        modified_fragment=None,
    ):
        for loss_mass_val, loss_desc, loss_type, _ in generate_multiple_neutral_losses(
            mod_ion_mass,
            seq,
            mod_ion_type,
            max_losses=max_neutral_losses,
            selected_ion_types=ion_types,
            base_type=clean_base,
        ):
            if loss_desc in ion_types:
                add_charged_isotopes(
                    loss_mass_val,
                    num,
                    loss_desc,
                    seq,
                    loss_type,
                    base_color,
                    clean_base,
                    "Mod-NL-Series",
                    modified_fragment=modified_fragment,
                )

    def _apply_mod_nl_to_satellite(
        sat_type,
        sat_mass,
        sat_num,
        sat_seq,
        clean_base,
        base_color,
        is_in_frag,
        seq_start=0,
    ):
        """Apply mod-specific NL/labile/remainder tags to one satellite ion variant."""
        if not mod_neutral_losses or not modifications:
            return
        # Build base mod pairs for this satellite fragment (0-indexed within sat_seq)
        base_sat_pairs = [
            (mod_site - 1 - seq_start, mod_mass_val)
            for mod_mass_val, mod_site in modifications
            if is_in_frag(mod_site) and 0 <= mod_site - 1 - seq_start < len(sat_seq)
        ]
        for mod_idx, (mod_mass_val, mod_site) in enumerate(modifications):
            nl_cfg = (
                mod_neutral_losses[mod_idx]
                if mod_idx < len(mod_neutral_losses)
                else None
            )
            if nl_cfg is None or not is_in_frag(mod_site):
                continue
            mod_pos = mod_site - 1 - seq_start
            # Dynamic neutral losses (*, **, ***)
            for nl_i, nl_mass in enumerate(nl_cfg.get("neutral_losses", [])):
                if nl_mass <= 0:
                    continue
                tag = _nl_tag(nl_i)
                nl_ion = _insert_mod_nl_tag(sat_type, tag)
                nl_pairs = [
                    (p, m - nl_mass) if p == mod_pos else (p, m)
                    for p, m in base_sat_pairs
                ]
                nl_mf = _build_modified_fragment(sat_seq, nl_pairs)
                add_charged_isotopes(
                    sat_mass - nl_mass,
                    sat_num,
                    nl_ion,
                    sat_seq,
                    f"ModNL{nl_i + 1}",
                    base_color,
                    clean_base,
                    "Mod-NL-Series",
                    modified_fragment=nl_mf,
                )
                _add_standard_losses_for_mod_ion(
                    sat_mass - nl_mass,
                    nl_ion,
                    sat_num,
                    sat_seq,
                    base_color,
                    clean_base,
                    modified_fragment=nl_mf,
                )
            # Labile loss (~)
            if nl_cfg.get("labile_loss", False):
                labile = nl_cfg.get("mod_mass", mod_mass_val)
                if nl_cfg.get("generate_labile_ion", True):
                    labile_ion = _insert_mod_nl_tag(sat_type, "~")
                    labile_pairs = [(p, m) for p, m in base_sat_pairs if p != mod_pos]
                    labile_mf = _build_modified_fragment(sat_seq, labile_pairs)
                    add_charged_isotopes(
                        sat_mass - labile,
                        sat_num,
                        labile_ion,
                        sat_seq,
                        "LabileLoss",
                        base_color,
                        clean_base,
                        "Mod-NL-Series",
                        modified_fragment=labile_mf,
                    )
                    _add_standard_losses_for_mod_ion(
                        sat_mass - labile,
                        labile_ion,
                        sat_num,
                        sat_seq,
                        base_color,
                        clean_base,
                        modified_fragment=labile_mf,
                    )
                # Remainder ions (^, ^^, ^^^)
                for rm_i, rm_mass in enumerate(nl_cfg.get("remainder_ions", [])):
                    if rm_mass <= 0:
                        continue
                    tag = _rm_tag(rm_i)
                    rm_ion = _insert_mod_nl_tag(sat_type, tag)
                    rm_frag_mass = sat_mass - labile + rm_mass
                    rm_pairs = [
                        (p, rm_mass) if p == mod_pos else (p, m)
                        for p, m in base_sat_pairs
                    ]
                    rm_mf = _build_modified_fragment(sat_seq, rm_pairs)
                    add_charged_isotopes(
                        rm_frag_mass,
                        sat_num,
                        rm_ion,
                        sat_seq,
                        f"ModRM{rm_i + 1}",
                        base_color,
                        clean_base,
                        "Mod-NL-Series",
                        modified_fragment=rm_mf,
                    )
                    _add_standard_losses_for_mod_ion(
                        rm_frag_mass,
                        rm_ion,
                        sat_num,
                        sat_seq,
                        base_color,
                        clean_base,
                        modified_fragment=rm_mf,
                    )

    # Prefix sums for O(1) internal fragment mass lookup
    prefix_sums = [0.0] * (peptide_length + 1)
    for _k, _aa in enumerate(peptide_sequence):
        prefix_sums[_k + 1] = prefix_sums[_k] + AMINO_ACID_MASSES[_aa]

    # MH modified fragment annotation never changes — compute once
    _mh_mf = (
        _build_modified_fragment(
            peptide_sequence, [(ms - 1, mv) for mv, ms in modifications]
        )
        if modifications
        else peptide_sequence
    )

    # Cache clean-base-type results for fixed ion types (avoids repeated string ops)
    _clean_base_cache = {
        t: _clean_base_type(t)
        for t in ("b", "a", "c", "c-1", "y", "x", "z", "z+1", "MH")
    }

    # ---- MH (precursor) ion — constant, computed once outside per-cleavage loop ----
    if "MH" in ion_types:
        _mh_color = ion_colors.get("MH", "grey")
        add_charged_isotopes(
            MH_mass,
            peptide_length,
            "MH",
            peptide_sequence,
            "None",
            _mh_color,
            "MH",
            "Standard-Ion-Series",
            modified_fragment=_mh_mf,
        )
        for _mh_loss_name, _mh_loss_val in (("H2O", H2O), ("NH3", NH3)):
            _mh_loss_ion = f"MH-{_mh_loss_name}"
            if _mh_loss_ion in ion_types:
                add_charged_isotopes(
                    MH_mass - _mh_loss_val,
                    peptide_length,
                    _mh_loss_ion,
                    peptide_sequence,
                    _mh_loss_name,
                    _mh_color,
                    "MH",
                    "Standard-Ion-Series",
                    modified_fragment=_mh_mf,
                )

    # ---- MH (precursor) mod-NL — constant, computed once outside per-cleavage loop ----
    if mod_neutral_losses and modifications and "MH" in ion_types:
        _mh_base_pairs = [(ms - 1, mv) for mv, ms in modifications]
        _mh_base_color = ion_colors.get("MH", "grey")
        for _mh_mod_idx, (_mh_mod_mass, _mh_mod_site) in enumerate(modifications):
            _mh_nl_config = (
                mod_neutral_losses[_mh_mod_idx]
                if _mh_mod_idx < len(mod_neutral_losses)
                else None
            )
            if _mh_nl_config is None:
                continue
            _mh_mod_pos = _mh_mod_site - 1
            for _mh_nl_idx, _mh_nl_mass in enumerate(
                _mh_nl_config.get("neutral_losses", [])
            ):
                if _mh_nl_mass <= 0:
                    continue
                _mh_tag = _nl_tag(_mh_nl_idx)
                _mh_label = f"ModNL{_mh_nl_idx + 1}"
                _mh_nl_ion_type = _insert_mod_nl_tag("MH", _mh_tag)
                _mh_nl_pairs = [
                    (p, m - _mh_nl_mass) if p == _mh_mod_pos else (p, m)
                    for p, m in _mh_base_pairs
                ]
                _mh_nl_mf = _build_modified_fragment(peptide_sequence, _mh_nl_pairs)
                add_charged_isotopes(
                    MH_mass - _mh_nl_mass,
                    peptide_length,
                    _mh_nl_ion_type,
                    peptide_sequence,
                    _mh_label,
                    _mh_base_color,
                    "MH",
                    "Mod-NL-Series",
                    modified_fragment=_mh_nl_mf,
                )
                _add_standard_losses_for_mod_ion(
                    MH_mass - _mh_nl_mass,
                    _mh_nl_ion_type,
                    peptide_length,
                    peptide_sequence,
                    _mh_base_color,
                    "MH",
                    modified_fragment=_mh_nl_mf,
                )
            if _mh_nl_config.get("labile_loss", False):
                _mh_labile = _mh_nl_config.get("mod_mass", _mh_mod_mass)
                if _mh_nl_config.get("generate_labile_ion", True):
                    _mh_labile_ion = _insert_mod_nl_tag("MH", "~")
                    _mh_labile_pairs = [
                        (p, m) for p, m in _mh_base_pairs if p != _mh_mod_pos
                    ]
                    _mh_labile_mf = _build_modified_fragment(
                        peptide_sequence, _mh_labile_pairs
                    )
                    add_charged_isotopes(
                        MH_mass - _mh_labile,
                        peptide_length,
                        _mh_labile_ion,
                        peptide_sequence,
                        "LabileLoss",
                        _mh_base_color,
                        "MH",
                        "Mod-NL-Series",
                        modified_fragment=_mh_labile_mf,
                    )
                    _add_standard_losses_for_mod_ion(
                        MH_mass - _mh_labile,
                        _mh_labile_ion,
                        peptide_length,
                        peptide_sequence,
                        _mh_base_color,
                        "MH",
                        modified_fragment=_mh_labile_mf,
                    )
                for _mh_rm_idx, _mh_rm_mass in enumerate(
                    _mh_nl_config.get("remainder_ions", [])
                ):
                    if _mh_rm_mass <= 0:
                        continue
                    _mh_rm_tag = _rm_tag(_mh_rm_idx)
                    _mh_rm_label = f"ModRM{_mh_rm_idx + 1}"
                    _mh_rm_ion_type = _insert_mod_nl_tag("MH", _mh_rm_tag)
                    _mh_rm_frag_mass = MH_mass - _mh_labile + _mh_rm_mass
                    _mh_rm_pairs = [
                        (p, _mh_rm_mass) if p == _mh_mod_pos else (p, m)
                        for p, m in _mh_base_pairs
                    ]
                    _mh_rm_mf = _build_modified_fragment(peptide_sequence, _mh_rm_pairs)
                    add_charged_isotopes(
                        _mh_rm_frag_mass,
                        peptide_length,
                        _mh_rm_ion_type,
                        peptide_sequence,
                        _mh_rm_label,
                        _mh_base_color,
                        "MH",
                        "Mod-NL-Series",
                        modified_fragment=_mh_rm_mf,
                    )
                    _add_standard_losses_for_mod_ion(
                        _mh_rm_frag_mass,
                        _mh_rm_ion_type,
                        peptide_length,
                        peptide_sequence,
                        _mh_base_color,
                        "MH",
                        modified_fragment=_mh_rm_mf,
                    )
        # Cumulative MH mod-NL
        _mh_mods_in_frag = []
        for _mh_mod_idx2, (_mh_mod_mass_val2, _mh_mod_site2) in enumerate(
            modifications
        ):
            _mh_nl_cfg2 = (
                mod_neutral_losses[_mh_mod_idx2]
                if _mh_mod_idx2 < len(mod_neutral_losses)
                else None
            )
            if _mh_nl_cfg2 is None:
                continue
            _mh_mods_in_frag.append((_mh_nl_cfg2, _mh_mod_site2 - 1, _mh_mod_mass_val2))
        if len(_mh_mods_in_frag) >= 2:
            _mh_all_frag_pairs = [(ms - 1, mv) for mv, ms in modifications]
            _mh_max_nl_count = max(
                (len(cfg.get("neutral_losses", [])) for cfg, _, _ in _mh_mods_in_frag),
                default=0,
            )
            for _mh_nl_idx2 in range(_mh_max_nl_count):
                _mh_entries_for_nl = [
                    (cfg, pos, mass, cfg["neutral_losses"][_mh_nl_idx2])
                    for cfg, pos, mass in _mh_mods_in_frag
                    if len(cfg.get("neutral_losses", [])) > _mh_nl_idx2
                    and cfg["neutral_losses"][_mh_nl_idx2] > 0
                ]
                if len(_mh_entries_for_nl) < 2:
                    continue
                _mh_tag2 = _nl_tag(_mh_nl_idx2)
                _mh_nl_label2 = f"ModNL{_mh_nl_idx2 + 1}"
                for _mh_combo_size in range(2, len(_mh_entries_for_nl) + 1):
                    _mh_seen_sums = set()
                    for _mh_combo in combinations(_mh_entries_for_nl, _mh_combo_size):
                        _mh_total_loss = round(
                            sum(nl_m for _, _, _, nl_m in _mh_combo), 6
                        )
                        if _mh_total_loss in _mh_seen_sums:
                            continue
                        _mh_seen_sums.add(_mh_total_loss)
                        _mh_cumul_pairs = list(_mh_all_frag_pairs)
                        for _, pos, _, nl_m in _mh_combo:
                            _mh_cumul_pairs = [
                                (p, m - nl_m) if p == pos else (p, m)
                                for p, m in _mh_cumul_pairs
                            ]
                        _mh_cumul_mf = _build_modified_fragment(
                            peptide_sequence, _mh_cumul_pairs
                        )
                        sup = str(_mh_combo_size).translate(_SUPERSCRIPT)
                        _mh_cumul_tag = f"{_mh_tag2}{sup}"
                        _mh_cumul_nl_label = f"{_mh_nl_label2}x{_mh_combo_size}"
                        _mh_cumul_nl_ion = _insert_mod_nl_tag("MH", _mh_cumul_tag)
                        add_charged_isotopes(
                            MH_mass - _mh_total_loss,
                            peptide_length,
                            _mh_cumul_nl_ion,
                            peptide_sequence,
                            _mh_cumul_nl_label,
                            _mh_base_color,
                            "MH",
                            "Mod-NL-Series",
                            modified_fragment=_mh_cumul_mf,
                        )
                        _add_standard_losses_for_mod_ion(
                            MH_mass - _mh_total_loss,
                            _mh_cumul_nl_ion,
                            peptide_length,
                            peptide_sequence,
                            _mh_base_color,
                            "MH",
                            modified_fragment=_mh_cumul_mf,
                        )
            # Cumulative labile losses for MH
            _mh_labile_entries = [
                (cfg, pos, cfg.get("mod_mass", mass))
                for cfg, pos, mass in _mh_mods_in_frag
                if cfg.get("labile_loss", False)
                and cfg.get("generate_labile_ion", True)
            ]
            if len(_mh_labile_entries) >= 2:
                for _mh_combo_size in range(2, len(_mh_labile_entries) + 1):
                    _mh_seen_sums = set()
                    for _mh_combo in combinations(_mh_labile_entries, _mh_combo_size):
                        _mh_total_loss = round(sum(m for _, _, m in _mh_combo), 6)
                        if _mh_total_loss in _mh_seen_sums:
                            continue
                        _mh_seen_sums.add(_mh_total_loss)
                        _mh_labile_positions = {pos for _, pos, _ in _mh_combo}
                        _mh_cumul_pairs = [
                            (p, m)
                            for p, m in _mh_all_frag_pairs
                            if p not in _mh_labile_positions
                        ]
                        _mh_cumul_mf = _build_modified_fragment(
                            peptide_sequence, _mh_cumul_pairs
                        )
                        sup = str(_mh_combo_size).translate(_SUPERSCRIPT)
                        _mh_cumul_tag = f"~{sup}"
                        _mh_cumul_labile_label = f"LabileLossx{_mh_combo_size}"
                        _mh_cumul_nl_ion = _insert_mod_nl_tag("MH", _mh_cumul_tag)
                        add_charged_isotopes(
                            MH_mass - _mh_total_loss,
                            peptide_length,
                            _mh_cumul_nl_ion,
                            peptide_sequence,
                            _mh_cumul_labile_label,
                            _mh_base_color,
                            "MH",
                            "Mod-NL-Series",
                            modified_fragment=_mh_cumul_mf,
                        )
                        _add_standard_losses_for_mod_ion(
                            MH_mass - _mh_total_loss,
                            _mh_cumul_nl_ion,
                            peptide_length,
                            peptide_sequence,
                            _mh_base_color,
                            "MH",
                            modified_fragment=_mh_cumul_mf,
                        )
            # Cumulative remainder ions for MH
            _mh_max_rm_count = max(
                (
                    len(cfg.get("remainder_ions", []))
                    for cfg, _, _ in _mh_mods_in_frag
                    if cfg.get("labile_loss", False)
                ),
                default=0,
            )
            for _mh_rm_idx2 in range(_mh_max_rm_count):
                _mh_rm_entries = []
                for cfg, pos, mod_mass_val in _mh_mods_in_frag:
                    if not cfg.get("labile_loss", False):
                        continue
                    rms = cfg.get("remainder_ions", [])
                    if len(rms) > _mh_rm_idx2 and rms[_mh_rm_idx2] > 0:
                        _mh_rm_entries.append(
                            (
                                cfg,
                                pos,
                                cfg.get("mod_mass", mod_mass_val),
                                rms[_mh_rm_idx2],
                            )
                        )
                if len(_mh_rm_entries) < 2:
                    continue
                _mh_rm_tag_base = _rm_tag(_mh_rm_idx2)
                _mh_rm_label_base = f"ModRM{_mh_rm_idx2 + 1}"
                for _mh_combo_size in range(2, len(_mh_rm_entries) + 1):
                    _mh_seen_keys = set()
                    for _mh_combo in combinations(_mh_rm_entries, _mh_combo_size):
                        _mh_total_mod_loss = round(
                            sum(m for _, _, m, _ in _mh_combo), 6
                        )
                        _mh_total_rm_add = round(sum(r for _, _, _, r in _mh_combo), 6)
                        _mh_key = (_mh_total_mod_loss, _mh_total_rm_add)
                        if _mh_key in _mh_seen_keys:
                            continue
                        _mh_seen_keys.add(_mh_key)
                        _mh_cumul_pairs = list(_mh_all_frag_pairs)
                        for _, pos, mod_m, rm_m in _mh_combo:
                            _mh_cumul_pairs = [
                                (p, m - mod_m + rm_m) if p == pos else (p, m)
                                for p, m in _mh_cumul_pairs
                            ]
                        _mh_cumul_mf = _build_modified_fragment(
                            peptide_sequence, _mh_cumul_pairs
                        )
                        sup = str(_mh_combo_size).translate(_SUPERSCRIPT)
                        _mh_cumul_tag = f"{_mh_rm_tag_base}{sup}"
                        _mh_cumul_label = f"{_mh_rm_label_base}x{_mh_combo_size}"
                        _mh_rm_ion_type2 = _insert_mod_nl_tag("MH", _mh_cumul_tag)
                        _mh_cumul_rm_mass = (
                            MH_mass - _mh_total_mod_loss + _mh_total_rm_add
                        )
                        add_charged_isotopes(
                            _mh_cumul_rm_mass,
                            peptide_length,
                            _mh_rm_ion_type2,
                            peptide_sequence,
                            _mh_cumul_label,
                            _mh_base_color,
                            "MH",
                            "Mod-NL-Series",
                            modified_fragment=_mh_cumul_mf,
                        )
                        _add_standard_losses_for_mod_ion(
                            _mh_cumul_rm_mass,
                            _mh_rm_ion_type2,
                            peptide_length,
                            peptide_sequence,
                            _mh_base_color,
                            "MH",
                            modified_fragment=_mh_cumul_mf,
                        )

    # ---- Main loop: iterate over cleavage positions ----
    prefix_mass = 0.0
    for i in range(1, peptide_length):
        prefix = peptide_sequence[:i]
        suffix = peptide_sequence[i:]

        # Incremental prefix/suffix mass computation
        prefix_mass += AMINO_ACID_MASSES[peptide_sequence[i - 1]]
        suffix_mass = peptide_mass - prefix_mass

        # Single pass over modifications — derive all per-cleavage values
        prefix_mod_pairs = [(ms - 1, mv) for mv, ms in modifications if ms <= i]
        suffix_mod_pairs = [(ms - 1 - i, mv) for mv, ms in modifications if ms > i]
        prefix_mod_mass = prefix_mass + sum(mv for _, mv in prefix_mod_pairs)
        suffix_mod_mass = suffix_mass + sum(mv for _, mv in suffix_mod_pairs)

        _prefix_mf = (
            _build_modified_fragment(prefix, prefix_mod_pairs)
            if modifications
            else prefix
        )
        _suffix_mf = (
            _build_modified_fragment(suffix, suffix_mod_pairs)
            if modifications
            else suffix
        )
        _base_mf = {
            "b": _prefix_mf,
            "a": _prefix_mf,
            "c": _prefix_mf,
            "c-1": _prefix_mf,
            "y": _suffix_mf,
            "x": _suffix_mf,
            "z": _suffix_mf,
            "z+1": _suffix_mf,
            "MH": _mh_mf,
        }

        # Calculate base ion masses
        b_mass = prefix_mod_mass
        a_mass = b_mass - CO
        c_mass = prefix_mod_mass + NH3
        y_mass = suffix_mod_mass + H2O
        x_mass = y_mass + (CO - 2 * H)
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
        ]

        # Process each base ion type
        for ion_type, mass_val, num, seq in base_ions:
            if ion_type in ion_types:
                base_color = ion_colors.get(ion_type, "grey")
                mf = _base_mf[ion_type]

                # Add the base ion (no neutral loss)
                add_charged_isotopes(
                    mass_val,
                    num,
                    ion_type,
                    seq,
                    "None",
                    base_color,
                    _clean_base_cache.get(ion_type, _clean_base_type(ion_type)),
                    "Standard-Ion-Series",
                    modified_fragment=mf,
                )

                neutral_loss_variants = generate_multiple_neutral_losses(
                    mass_val,
                    seq,
                    ion_type,
                    max_losses=max_neutral_losses,
                    selected_ion_types=ion_types,
                    base_type=_clean_base_cache.get(ion_type, ion_type),
                )
                for (
                    loss_mass,
                    loss_ion_type,
                    loss_type,
                    loss_count,
                ) in neutral_loss_variants:
                    if loss_ion_type in ion_types:
                        add_charged_isotopes(
                            loss_mass,
                            num,
                            loss_ion_type,
                            seq,
                            loss_type,
                            base_color,
                            _clean_base_cache.get(ion_type, _clean_base_type(ion_type)),
                            "Standard-Ion-Series",
                            modified_fragment=mf,
                        )

        # ---- Satellite ions: d (from a), w (from z), v (from y) ----
        # d ion: N-terminal, sidechain loss from last residue of prefix
        cleavage_aa_n = peptide_sequence[i - 1]  # last AA of prefix (N-terminal side)
        leaving_groups_d = SIDECHAIN_LEAVING_GROUPS.get(cleavage_aa_n, [])
        if "d" in ion_types:
            for suffix_label, leaving_mass in leaving_groups_d:
                d_type = f"d{suffix_label}"
                d_mass = a_mass - leaving_mass + H
                base_color = ion_colors.get(d_type, "teal")
                add_charged_isotopes(
                    d_mass,
                    i,
                    d_type,
                    prefix,
                    "None",
                    base_color,
                    "d",
                    "Satellite-Ion-Series",
                    modified_fragment=_prefix_mf,
                )
                _add_satellite_neutral_losses(
                    d_mass,
                    i,
                    d_type,
                    prefix,
                    "d",
                    "teal",
                    "Satellite-Ion-Series",
                    modified_fragment=_prefix_mf,
                )

        # w ion: C-terminal, sidechain loss from first residue of suffix
        cleavage_aa_c = peptide_sequence[i]  # first AA of suffix (C-terminal side)
        leaving_groups_w = SIDECHAIN_LEAVING_GROUPS.get(cleavage_aa_c, [])
        if "w" in ion_types:
            for suffix_label, leaving_mass in leaving_groups_w:
                w_type = f"w{suffix_label}"
                w_mass = z_mass - leaving_mass
                base_color = ion_colors.get(w_type, "darkcyan")
                add_charged_isotopes(
                    w_mass,
                    peptide_length - i,
                    w_type,
                    suffix,
                    "None",
                    base_color,
                    "w",
                    "Satellite-Ion-Series",
                    modified_fragment=_suffix_mf,
                )
                _add_satellite_neutral_losses(
                    w_mass,
                    peptide_length - i,
                    w_type,
                    suffix,
                    "w",
                    "darkcyan",
                    "Satellite-Ion-Series",
                    modified_fragment=_suffix_mf,
                )

        # v ion: C-terminal, full sidechain loss from y ion
        if "v" in ion_types and cleavage_aa_c not in V_ION_EXCLUDED_AA:
            v_mass_base = (
                suffix_mod_mass - AMINO_ACID_MASSES[cleavage_aa_c] + C2H2NO + O
            )
            # If the first AA of suffix has a modification, it is lost with the sidechain
            v_mod_mass = v_mass_base
            for mod_mass, mod_site in modifications:
                if mod_site == i + 1:
                    v_mod_mass -= mod_mass
            base_color = ion_colors.get("v", "magenta")
            # v ion loses sidechain (and mod) at site i+1, so exclude that from annotation
            if modifications:
                _v_mf = _build_modified_fragment(
                    suffix,
                    [
                        (ms - 1 - i, mv)
                        for mv, ms in modifications
                        if ms > i and ms != i + 1
                    ],
                )
            else:
                _v_mf = suffix
            add_charged_isotopes(
                v_mod_mass,
                peptide_length - i,
                "v",
                suffix,
                "None",
                base_color,
                "v",
                "Satellite-Ion-Series",
                modified_fragment=_v_mf,
            )
            _add_satellite_neutral_losses(
                v_mod_mass,
                peptide_length - i,
                "v",
                suffix,
                "v",
                "magenta",
                "Satellite-Ion-Series",
                modified_fragment=_v_mf,
            )

        # Handle custom ion series with conditional neutral losses
        base_ion_dict = {
            "b": b_mass,
            "a": a_mass,
            "c": c_mass,
            "c-1": c_mass - H,
            "y": y_mass,
            "x": x_mass,
            "z": z_mass,
            "z+1": z_mass + H,
            "MH": MH_mass,
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

            if not check_restriction(
                fragment_seq, restriction, custom_base_type, peptide_sequence
            ):
                continue

            custom_base_mass = base_ion_dict[custom_base_type]
            custom_mass = custom_base_mass + offset
            mf = _base_mf.get(custom_base_type, fragment_seq)

            add_charged_isotopes(
                custom_mass,
                ion_number,
                ion_name,
                fragment_seq,
                "None",
                ion_color,
                custom_base_type,
                "Custom-Ion-Series",
                modified_fragment=mf,
            )

            neutral_loss_variants = generate_multiple_neutral_losses(
                custom_mass,
                fragment_seq,
                ion_name,
                max_losses=max_neutral_losses,
                selected_ion_types=ion_types,
                base_type=custom_base_type,
            )
            for (
                loss_mass,
                loss_ion_type,
                loss_type,
                loss_count,
            ) in neutral_loss_variants:
                add_charged_isotopes(
                    loss_mass,
                    ion_number,
                    loss_ion_type,
                    fragment_seq,
                    loss_type,
                    ion_color,
                    custom_base_type,
                    "Custom-Ion-Series",
                    modified_fragment=mf,
                )

        # ----------------------------------------------------------
        # Modification-specific neutral losses (*, **, ***, ~) and remainder ions (^, ^^, ^^^)
        # ----------------------------------------------------------
        if mod_neutral_losses and modifications:
            for mod_idx, (mod_mass, mod_site) in enumerate(modifications):
                nl_config = (
                    mod_neutral_losses[mod_idx]
                    if mod_idx < len(mod_neutral_losses)
                    else None
                )
                if nl_config is None:
                    continue

                for ion_type, mass_val, num, seq in base_ions:
                    if ion_type not in ion_types:
                        continue

                    # Check if this fragment contains the modification site; compute mod position in seq
                    if ion_type in ("b", "a", "c", "c-1"):
                        if mod_site > i:  # mod not in this N-terminal fragment
                            continue
                        mod_pos_in_seq = mod_site - 1
                        base_pairs = prefix_mod_pairs
                    elif ion_type in ("y", "x", "z", "z+1"):
                        if mod_site <= i:  # mod not in this C-terminal fragment
                            continue
                        mod_pos_in_seq = mod_site - 1 - i
                        base_pairs = suffix_mod_pairs
                    else:
                        continue

                    base_color = ion_colors.get(ion_type, "grey")
                    clean_base = _clean_base_cache.get(
                        ion_type, _clean_base_type(ion_type)
                    )

                    # Dynamic neutral losses from list
                    nl_list = nl_config.get("neutral_losses", [])
                    for nl_idx, nl_mass in enumerate(nl_list):
                        if nl_mass <= 0:
                            continue
                        tag = _nl_tag(nl_idx)
                        label = f"ModNL{nl_idx + 1}"
                        nl_ion_type = _insert_mod_nl_tag(ion_type, tag)
                        nl_pairs = [
                            (p, m - nl_mass) if p == mod_pos_in_seq else (p, m)
                            for p, m in base_pairs
                        ]
                        nl_mf = _build_modified_fragment(seq, nl_pairs)
                        add_charged_isotopes(
                            mass_val - nl_mass,
                            num,
                            nl_ion_type,
                            seq,
                            label,
                            base_color,
                            clean_base,
                            "Mod-NL-Series",
                            modified_fragment=nl_mf,
                        )
                        _add_standard_losses_for_mod_ion(
                            mass_val - nl_mass,
                            nl_ion_type,
                            num,
                            seq,
                            base_color,
                            clean_base,
                            modified_fragment=nl_mf,
                        )

                    # Labile loss (~) - entire modification mass removed
                    if nl_config.get("labile_loss", False):
                        labile_mass = nl_config.get("mod_mass", mod_mass)
                        if nl_config.get("generate_labile_ion", True):
                            nl_ion_type = _insert_mod_nl_tag(ion_type, "~")
                            labile_pairs = [
                                (p, m) for p, m in base_pairs if p != mod_pos_in_seq
                            ]
                            labile_mf = _build_modified_fragment(seq, labile_pairs)
                            add_charged_isotopes(
                                mass_val - labile_mass,
                                num,
                                nl_ion_type,
                                seq,
                                "LabileLoss",
                                base_color,
                                clean_base,
                                "Mod-NL-Series",
                                modified_fragment=labile_mf,
                            )
                            _add_standard_losses_for_mod_ion(
                                mass_val - labile_mass,
                                nl_ion_type,
                                num,
                                seq,
                                base_color,
                                clean_base,
                                modified_fragment=labile_mf,
                            )

                        # Remainder ions (^, ^^, ^^^, ...)
                        rm_list = nl_config.get("remainder_ions", [])
                        for rm_idx, rm_mass in enumerate(rm_list):
                            if rm_mass <= 0:
                                continue
                            tag = _rm_tag(rm_idx)
                            label = f"ModRM{rm_idx + 1}"
                            rm_ion_type = _insert_mod_nl_tag(ion_type, tag)
                            rm_fragment_mass = mass_val - labile_mass + rm_mass
                            rm_pairs = [
                                (p, rm_mass) if p == mod_pos_in_seq else (p, m)
                                for p, m in base_pairs
                            ]
                            rm_mf = _build_modified_fragment(seq, rm_pairs)
                            add_charged_isotopes(
                                rm_fragment_mass,
                                num,
                                rm_ion_type,
                                seq,
                                label,
                                base_color,
                                clean_base,
                                "Mod-NL-Series",
                                modified_fragment=rm_mf,
                            )
                            _add_standard_losses_for_mod_ion(
                                rm_fragment_mass,
                                rm_ion_type,
                                num,
                                seq,
                                base_color,
                                clean_base,
                                modified_fragment=rm_mf,
                            )

            # ----------------------------------------------------------
            # Cumulative (stacked) mod neutral losses (2*,3*,2~, etc.)
            # When a fragment contains 2+ mod sites with active NLs,
            # generate combined losses: e.g. 2xNL1 for double AETMA.
            # ----------------------------------------------------------
            for ion_type, mass_val, num, seq in base_ions:
                if ion_type not in ion_types:
                    continue

                # Collect all NL configs + positions for mods within this fragment
                # Each entry: (nl_cfg, mod_pos_in_seq, mod_mass_val)
                mods_in_frag = []
                for mod_idx, (mod_mass_val, mod_site) in enumerate(modifications):
                    nl_cfg = (
                        mod_neutral_losses[mod_idx]
                        if mod_idx < len(mod_neutral_losses)
                        else None
                    )
                    if nl_cfg is None:
                        continue
                    if ion_type in ("b", "a", "c", "c-1"):
                        if mod_site > i:
                            continue
                        mod_pos_in_seq = mod_site - 1
                    elif ion_type in ("y", "x", "z", "z+1"):
                        if mod_site <= i:
                            continue
                        mod_pos_in_seq = mod_site - 1 - i
                    else:
                        continue
                    mods_in_frag.append((nl_cfg, mod_pos_in_seq, mod_mass_val))

                if len(mods_in_frag) < 2:
                    continue

                # All mod positions/masses in this fragment (for annotation base)
                if ion_type in ("b", "a", "c", "c-1"):
                    all_frag_pairs = prefix_mod_pairs
                else:
                    all_frag_pairs = suffix_mod_pairs

                base_color = ion_colors.get(ion_type, "grey")
                clean_base = _clean_base_cache.get(ion_type, _clean_base_type(ion_type))

                # Dynamic NL type definitions from actual NL counts
                max_nl_count = max(
                    (len(cfg.get("neutral_losses", [])) for cfg, _, _ in mods_in_frag),
                    default=0,
                )
                for nl_idx in range(max_nl_count):
                    # Each entry: (nl_cfg, mod_pos_in_seq, mod_mass_val, nl_mass)
                    entries_for_nl = [
                        (cfg, pos, mass, cfg["neutral_losses"][nl_idx])
                        for cfg, pos, mass in mods_in_frag
                        if len(cfg.get("neutral_losses", [])) > nl_idx
                        and cfg["neutral_losses"][nl_idx] > 0
                    ]
                    if len(entries_for_nl) < 2:
                        continue
                    tag = _nl_tag(nl_idx)
                    nl_label = f"ModNL{nl_idx + 1}"
                    for combo_size in range(2, len(entries_for_nl) + 1):
                        seen_sums = set()
                        for combo in combinations(entries_for_nl, combo_size):
                            total_loss = round(sum(nl_m for _, _, _, nl_m in combo), 6)
                            if total_loss in seen_sums:
                                continue
                            seen_sums.add(total_loss)
                            # Build annotation: subtract each NL from its mod position
                            cumul_pairs = list(all_frag_pairs)
                            for _, pos, _, nl_m in combo:
                                cumul_pairs = [
                                    (p, m - nl_m) if p == pos else (p, m)
                                    for p, m in cumul_pairs
                                ]
                            cumul_mf = _build_modified_fragment(seq, cumul_pairs)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"{tag}{sup}"
                            cumul_nl_label = f"{nl_label}x{combo_size}"
                            nl_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            add_charged_isotopes(
                                mass_val - total_loss,
                                num,
                                nl_ion_type,
                                seq,
                                cumul_nl_label,
                                base_color,
                                clean_base,
                                "Mod-NL-Series",
                                modified_fragment=cumul_mf,
                            )
                            _add_standard_losses_for_mod_ion(
                                mass_val - total_loss,
                                nl_ion_type,
                                num,
                                seq,
                                base_color,
                                clean_base,
                                modified_fragment=cumul_mf,
                            )

                # Cumulative labile losses
                labile_entries = [
                    (cfg, pos, cfg.get("mod_mass", mass))
                    for cfg, pos, mass in mods_in_frag
                    if cfg.get("labile_loss", False)
                    and cfg.get("generate_labile_ion", True)
                ]
                if len(labile_entries) >= 2:
                    for combo_size in range(2, len(labile_entries) + 1):
                        seen_sums = set()
                        for combo in combinations(labile_entries, combo_size):
                            total_loss = round(sum(m for _, _, m in combo), 6)
                            if total_loss in seen_sums:
                                continue
                            seen_sums.add(total_loss)
                            # Remove labile mod positions from annotation
                            labile_positions = {pos for _, pos, _ in combo}
                            cumul_pairs = [
                                (p, m)
                                for p, m in all_frag_pairs
                                if p not in labile_positions
                            ]
                            cumul_mf = _build_modified_fragment(seq, cumul_pairs)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"~{sup}"
                            cumul_labile_label = f"LabileLossx{combo_size}"
                            nl_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            add_charged_isotopes(
                                mass_val - total_loss,
                                num,
                                nl_ion_type,
                                seq,
                                cumul_labile_label,
                                base_color,
                                clean_base,
                                "Mod-NL-Series",
                                modified_fragment=cumul_mf,
                            )
                            _add_standard_losses_for_mod_ion(
                                mass_val - total_loss,
                                nl_ion_type,
                                num,
                                seq,
                                base_color,
                                clean_base,
                                modified_fragment=cumul_mf,
                            )

                # Cumulative remainder ions
                max_rm_count = max(
                    (
                        len(cfg.get("remainder_ions", []))
                        for cfg, _, _ in mods_in_frag
                        if cfg.get("labile_loss", False)
                    ),
                    default=0,
                )
                for rm_idx in range(max_rm_count):
                    # Each entry: (nl_cfg, mod_pos_in_seq, mod_mass_val, rm_mass)
                    rm_entries = []
                    for cfg, pos, mod_mass_val in mods_in_frag:
                        if not cfg.get("labile_loss", False):
                            continue
                        rms = cfg.get("remainder_ions", [])
                        if len(rms) > rm_idx and rms[rm_idx] > 0:
                            rm_entries.append(
                                (
                                    cfg,
                                    pos,
                                    cfg.get("mod_mass", mod_mass_val),
                                    rms[rm_idx],
                                )
                            )
                    if len(rm_entries) < 2:
                        continue
                    rm_tag_base = _rm_tag(rm_idx)
                    rm_label_base = f"ModRM{rm_idx + 1}"
                    for combo_size in range(2, len(rm_entries) + 1):
                        seen_keys = set()
                        for combo in combinations(rm_entries, combo_size):
                            total_mod_loss = round(sum(m for _, _, m, _ in combo), 6)
                            total_rm_add = round(sum(r for _, _, _, r in combo), 6)
                            key = (total_mod_loss, total_rm_add)
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            # Replace labile mod mass with RM mass at each position
                            cumul_pairs = list(all_frag_pairs)
                            for _, pos, mod_m, rm_m in combo:
                                cumul_pairs = [
                                    (p, m - mod_m + rm_m) if p == pos else (p, m)
                                    for p, m in cumul_pairs
                                ]
                            cumul_mf = _build_modified_fragment(seq, cumul_pairs)
                            sup = str(combo_size).translate(_SUPERSCRIPT)
                            cumul_tag = f"{rm_tag_base}{sup}"
                            cumul_label = f"{rm_label_base}x{combo_size}"
                            rm_ion_type = _insert_mod_nl_tag(ion_type, cumul_tag)
                            cumul_rm_mass = mass_val - total_mod_loss + total_rm_add
                            add_charged_isotopes(
                                cumul_rm_mass,
                                num,
                                rm_ion_type,
                                seq,
                                cumul_label,
                                base_color,
                                clean_base,
                                "Mod-NL-Series",
                                modified_fragment=cumul_mf,
                            )
                            _add_standard_losses_for_mod_ion(
                                cumul_rm_mass,
                                rm_ion_type,
                                num,
                                seq,
                                base_color,
                                clean_base,
                                modified_fragment=cumul_mf,
                            )

        # Mod-NL / labile / remainder for satellite ions at cleavage position i
        if mod_neutral_losses and modifications:
            # d ions - N-terminal: mod must be within prefix (mod_site <= i)
            if "d" in ion_types:
                for sfx, lv_mass in leaving_groups_d:
                    d_type = f"d{sfx}"
                    _apply_mod_nl_to_satellite(
                        d_type,
                        a_mass - lv_mass + H,
                        i,
                        prefix,
                        "d",
                        ion_colors.get(d_type, "teal"),
                        lambda ms, _i=i: ms <= _i,
                        seq_start=0,
                    )
            # w ions - C-terminal: mod must be within suffix (mod_site > i)
            if "w" in ion_types:
                for sfx, lv_mass in leaving_groups_w:
                    w_type = f"w{sfx}"
                    _apply_mod_nl_to_satellite(
                        w_type,
                        z_mass - lv_mass,
                        peptide_length - i,
                        suffix,
                        "w",
                        ion_colors.get(w_type, "darkcyan"),
                        lambda ms, _i=i: ms > _i,
                        seq_start=i,
                    )
            # v ions - mod_site > i+1 (position i+1's sidechain is already removed
            # from v_mod_mass, so only mods at i+2 and beyond are still in the ion)
            if "v" in ion_types and cleavage_aa_c not in V_ION_EXCLUDED_AA:
                _apply_mod_nl_to_satellite(
                    "v",
                    v_mod_mass,
                    peptide_length - i,
                    suffix,
                    "v",
                    ion_colors.get("v", "magenta"),
                    lambda ms, _i=i: ms > _i + 1,
                    seq_start=i,
                )

        # Internal fragments
        for j in range(i + 1, peptide_length):
            internal_seq = peptide_sequence[i:j]

            if len(internal_seq) == 1:
                continue

            internal_mass = prefix_sums[j] - prefix_sums[i]
            internal_mod_pairs = []
            for mass, site in modifications:
                if i < site < j:
                    internal_mass += mass
                    internal_mod_pairs.append((site - 1 - i, mass))

            internal_mf = _build_modified_fragment(internal_seq, internal_mod_pairs)

            for ion_type in Internal:
                ion_mass = internal_mass + {
                    "b": H_ion,
                    "a": H_ion - CO,
                }.get(ion_type, 0)

                position_notation = f"{i+1}-{j}"

                # Only generate charge state 1 for internal fragments
                charge = 1
                charged_mass = (ion_mass + (charge - 1 - E) * H_ion) / charge
                fragment_ions.append(
                    (
                        charged_mass,
                        position_notation,
                        f"int-{ion_type}",
                        internal_seq,
                        "None",
                        charge,
                        0,
                        ion_colors.get(ion_type, "grey"),
                        ion_type,
                        "Internal-Ion",
                        internal_mf,
                    )
                )

                if calculate_isotopes:
                    for isotope in range(1, isotope_max + 1):
                        isotope_mass = charged_mass + (isotope * C13 / charge)
                        fragment_ions.append(
                            (
                                isotope_mass,
                                position_notation,
                                f"int-{ion_type}",
                                internal_seq,
                                "None",
                                charge,
                                isotope,
                                ion_colors.get(ion_type, "grey"),
                                ion_type,
                                "Internal-Ion",
                                internal_mf,
                            )
                        )

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
            add_charged_isotopes(
                d_mass,
                peptide_length,
                d_type,
                peptide_sequence,
                "None",
                base_color,
                "d",
                "Satellite-Ion-Series",
                modified_fragment=_mh_mf,
            )
            _add_satellite_neutral_losses(
                d_mass,
                peptide_length,
                d_type,
                peptide_sequence,
                "d",
                "teal",
                "Satellite-Ion-Series",
                modified_fragment=_mh_mf,
            )

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
            add_charged_isotopes(
                w_mass,
                peptide_length,
                w_type,
                peptide_sequence,
                "None",
                base_color,
                "w",
                "Satellite-Ion-Series",
                modified_fragment=_mh_mf,
            )
            _add_satellite_neutral_losses(
                w_mass,
                peptide_length,
                w_type,
                peptide_sequence,
                "w",
                "darkcyan",
                "Satellite-Ion-Series",
                modified_fragment=_mh_mf,
            )

    if "v" in ion_types and first_aa not in V_ION_EXCLUDED_AA:
        v_mass_base = full_suffix_mass - AMINO_ACID_MASSES[first_aa] + C2H2NO + O
        v_mod_mass = v_mass_base
        for mod_mass_val, mod_site in modifications:
            if mod_site == 1:
                v_mod_mass -= mod_mass_val
        base_color = ion_colors.get("v", "magenta")
        _endpoint_v_mf = (
            _build_modified_fragment(
                peptide_sequence, [(ms - 1, mv) for mv, ms in modifications if ms != 1]
            )
            if modifications
            else peptide_sequence
        )
        add_charged_isotopes(
            v_mod_mass,
            peptide_length,
            "v",
            peptide_sequence,
            "None",
            base_color,
            "v",
            "Satellite-Ion-Series",
            modified_fragment=_endpoint_v_mf,
        )
        _add_satellite_neutral_losses(
            v_mod_mass,
            peptide_length,
            "v",
            peptide_sequence,
            "v",
            "magenta",
            "Satellite-Ion-Series",
            modified_fragment=_endpoint_v_mf,
        )

    # Mod-NL / labile / remainder for endpoint satellite ions (position n)
    if mod_neutral_losses and modifications:
        # Endpoint d - all mods are in the full-peptide N-terminal ion
        if "d" in ion_types:
            a_n_end = peptide_mass - CO
            for sfx, lv_mass in leaving_groups_d_n:
                d_type = f"d{sfx}"
                _apply_mod_nl_to_satellite(
                    d_type,
                    a_n_end - lv_mass + H,
                    peptide_length,
                    peptide_sequence,
                    "d",
                    ion_colors.get(d_type, "teal"),
                    lambda ms: True,
                    seq_start=0,
                )
        # Endpoint w - all mods are in the full-peptide C-terminal ion
        if "w" in ion_types:
            for sfx, lv_mass in leaving_groups_w_n:
                w_type = f"w{sfx}"
                _apply_mod_nl_to_satellite(
                    w_type,
                    z_n_mass - lv_mass,
                    peptide_length,
                    peptide_sequence,
                    "w",
                    ion_colors.get(w_type, "darkcyan"),
                    lambda ms: True,
                    seq_start=0,
                )
        # Endpoint v - first residue's sidechain (and mod at site 1) already removed
        if "v" in ion_types and first_aa not in V_ION_EXCLUDED_AA:
            _apply_mod_nl_to_satellite(
                "v",
                v_mod_mass,
                peptide_length,
                peptide_sequence,
                "v",
                ion_colors.get("v", "magenta"),
                lambda ms: ms > 1,
                seq_start=0,
            )

    # ---- Glycan Y-ions -------------------------------------------------------
    # Precursor-level ions representing the intact peptide backbone carrying a
    # partial glycan composition.  Mass formula:
    #   Y-ion neutral = MH_neutral - full_glycan_mass + partial_glycan_mass
    # where MH_neutral = peptide_mass + total_mod_mass + H2O (already computed).
    if glycan_composition_str and "GlycanY" in ion_types:
        from utils.peak_matching.constants import load_custom_monosaccharides

        _extra_masses, _extra_shorts = load_custom_monosaccharides()
        _full_comp = parse_glycan_composition(
            glycan_composition_str, extra_masses=_extra_masses
        )
        if _full_comp:
            _full_glycan_mass = glycan_composition_mass(
                _full_comp, extra_masses=_extra_masses
            )
            _glycan_y_color = ion_colors.get("GlycanY", "#8B008B")
            for _sub_comp in generate_glycan_sub_compositions(_full_comp):
                _partial_mass = glycan_composition_mass(
                    _sub_comp, extra_masses=_extra_masses
                )
                _y_neutral = MH_mass - _full_glycan_mass + _partial_mass
                _comp_short = glycan_composition_label(
                    _sub_comp, short=True, extra_shorts=_extra_shorts
                )
                _comp_long = glycan_composition_label(
                    _sub_comp, short=False, extra_shorts=_extra_shorts
                )
                _short_label = _comp_short if not _sub_comp else f"Y[{_comp_short}]"
                _long_label = _comp_long if not _sub_comp else f"Y[{_comp_long}]"
                _ion_num = sum(_sub_comp.values())
                # Charge states up to glycan_max_charge (explicit) or max_charge + 1
                _glycan_charge_limit = (
                    glycan_max_charge
                    if glycan_max_charge is not None
                    else max_charge + 1
                )
                for _charge in range(1, _glycan_charge_limit + 1):
                    _mz = (_y_neutral + _charge * H_ion) / _charge
                    fragment_ions.append(
                        (
                            _mz,
                            _ion_num,
                            _short_label,
                            peptide_sequence,
                            "None",
                            _charge,
                            0,
                            _glycan_y_color,
                            "GlycanY",
                            "GlycanY-Ion-Series",
                            _long_label,
                        )
                    )
                    if calculate_isotopes:
                        for _iso in range(1, isotope_max + 1):
                            fragment_ions.append(
                                (
                                    _mz + (_iso * C13 / _charge),
                                    _ion_num,
                                    _short_label,
                                    peptide_sequence,
                                    "None",
                                    _charge,
                                    _iso,
                                    _glycan_y_color,
                                    "GlycanY",
                                    "GlycanY-Ion-Series",
                                    _long_label,
                                )
                            )

    # Convert to DataFrame with updated columns
    df = pd.DataFrame(
        fragment_ions,
        columns=[
            "Theoretical Mass",
            "Ion Number",
            "Ion Type",
            "Fragment Sequence",
            "Neutral Loss",
            "Charge",
            "Isotope",
            "Color",
            "Base Type",
            "Ion Series Type",
            "Modified Fragment",
        ],
    )
    df = df.sort_values(by=["Ion Type", "Ion Number"])
    # Drop rows that are identical in all columns except Modified Fragment (same m/z, same neutral loss,
    # different site ambiguity). Keep the first occurrence which has a valid annotation.
    _dedup_cols = [
        "Theoretical Mass",
        "Ion Number",
        "Ion Type",
        "Fragment Sequence",
        "Neutral Loss",
        "Charge",
        "Isotope",
        "Color",
        "Base Type",
        "Ion Series Type",
    ]
    df = df.drop_duplicates(subset=_dedup_cols, keep="first")
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
    neutral_losses = ["H2O", "NH3", "H3PO4", "SOCH4"]

    df = df.copy()

    # Pre-convert to strings
    base_type = df["Base Type"].astype(str)
    current_neutral_loss = df["Neutral Loss"].fillna("None").astype(str)

    # Track which rows need updates
    detected_loss = pd.Series(None, index=df.index, dtype=object)
    clean_base_type = base_type.copy()

    # Only process rows where we might find losses (not Custom-Ion-Series or already have loss info)
    needs_processing = base_type.str.contains("-", na=False)

    if needs_processing.any():
        for loss in neutral_losses:
            # Pattern to match -H2O, -2H2O, -3H2O, etc.
            pattern = rf"-\d*{re.escape(loss)}"

            # Find rows with this loss pattern
            has_loss = (
                base_type.str.contains(pattern, regex=True, na=False) & needs_processing
            )

            if has_loss.any():
                # Update detected loss
                detected_loss[has_loss] = loss
                # Remove the loss pattern from base type
                clean_base_type[has_loss] = base_type[has_loss].str.replace(
                    pattern, "", regex=True
                )
                # Don't process these rows again
                needs_processing &= ~has_loss

    # Update columns where we detected a loss
    has_detected_loss = detected_loss.notna()
    needs_update = has_detected_loss & (
        current_neutral_loss.isin(["None", "nan", "", "NaN"])
    )
    df.loc[needs_update, "Neutral Loss"] = detected_loss[needs_update]
    df.loc[has_detected_loss, "Base Type"] = clean_base_type[has_detected_loss]

    # Handle ion variants
    base_type_replacements = {
        "z+1": "z",
        "c-1": "c",
        "wa": "w",
        "wb": "w",
        "da": "d",
        "db": "d",
    }
    df["Base Type"] = df["Base Type"].replace(base_type_replacements)

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
    fragment_seq = df["Fragment Sequence"].astype(str)
    neutral_loss = df["Neutral Loss"].fillna("None").astype(str)
    ion_type = df["Ion Type"].astype(str)

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
    loss_mask = ~skip_aa_checks
    if loss_mask.any():
        for known_loss, aa_set in _LOSS_AA_MAPPING.items():
            this_loss = loss_mask & (neutral_loss == known_loss)
            if not this_loss.any():
                continue
            # Extract optional count prefix from ion type string e.g. "y-2H2O" -> "2", "y-H2O" -> ""
            extracted = ion_type[this_loss].str.extract(
                rf"-(\d*){re.escape(known_loss)}", expand=False
            )
            counts = extracted.fillna("").replace("", "1").astype(int)
            loss_count[this_loss] = counts
            loss_type[this_loss] = known_loss

            # Vectorized max-possible check
            pattern = f"[{aa_set}]" if len(aa_set) > 1 else aa_set
            max_poss = fragment_seq[this_loss].str.count(pattern)
            over_max = (counts > max_poss).reindex(keep_mask.index, fill_value=False)
            keep_mask &= ~over_max

    # Vectorized amino acid checks for neutral losses
    has_loss = loss_type.notna()

    # H2O loss requires STED
    h2o_mask = has_loss & (loss_type == "H2O")
    if h2o_mask.any():
        has_sted = fragment_seq.str.contains("[STED]", regex=True, na=False)
        keep_mask &= ~(h2o_mask & ~has_sted)

    # NH3 loss requires RKQN
    nh3_mask = has_loss & (loss_type == "NH3")
    if nh3_mask.any():
        has_rkqn = fragment_seq.str.contains("[RKQN]", regex=True, na=False)
        keep_mask &= ~(nh3_mask & ~has_rkqn)

    # H3PO4 loss requires STY
    h3po4_mask = has_loss & (loss_type == "H3PO4")
    if h3po4_mask.any():
        has_sty = fragment_seq.str.contains("[STY]", regex=True, na=False)
        keep_mask &= ~(h3po4_mask & ~has_sty)

    # SOCH4 loss requires M
    soch4_mask = has_loss & (loss_type == "SOCH4")
    if soch4_mask.any():
        has_m = fragment_seq.str.contains("M", regex=False, na=False)
        keep_mask &= ~(soch4_mask & ~has_m)

    # z, z+1 ions starting with P
    z_ion_mask = ion_type.str.startswith("z", na=False)
    if z_ion_mask.any():
        starts_p = fragment_seq.str.startswith("P", na=False)
        keep_mask &= ~(z_ion_mask & starts_p)

    # w/wa/wb ions starting with P (derived from z)
    w_ion_mask = ion_type.str.startswith("w", na=False)
    if w_ion_mask.any():
        starts_p = fragment_seq.str.startswith("P", na=False)
        keep_mask &= ~(w_ion_mask & starts_p)

    # c-based ions ending with P
    c_ion_mask = ion_type.str.contains("c", regex=False, na=False)
    if c_ion_mask.any():
        ends_p = fragment_seq.str.endswith("P", na=False)
        keep_mask &= ~(c_ion_mask & ends_p)

    # Apply filtering
    df = df[keep_mask].copy()
    df = process_neutral_losses_and_base_types(df)
    df = df.drop_duplicates()

    return df
