"""Site localisation helpers for bulk rescoring.

Pure, picklable functions so they can run inside ProcessPoolExecutor workers.

Rules map a rounded modification mass to {"aa": "S,T", "stack": bool}:
  aa     comma-separated residues the mod may sit on (blank = any residue)
  stack  whether several copies of a mod may share one residue
"""

import itertools
from collections import Counter

MASS_TOLERANCE = 0.01  # Da – same tolerance as CentralModificationDatabase


def match_rule(mass, rules):
    """Return the rule key (rounded mass) matching *mass*, or None."""
    for key in rules:
        if abs(float(mass) - key) <= MASS_TOLERANCE:
            return key
    return None


def movable_indices(mods, rules):
    """Indices into *mods* whose mass is set to be relocalised."""
    if not mods or not rules:
        return []
    return [i for i, m in enumerate(mods) if match_rule(m[0], rules) is not None]


def _candidate_groups(peptide, mods, rules):
    """Group movable mods by rule -> [(rule_key, indices, candidate_positions)]."""
    movable = set(movable_indices(mods, rules))
    fixed_positions = {pos for i, (_, pos) in enumerate(mods) if i not in movable}

    groups = {}
    for i in sorted(movable):
        groups.setdefault(match_rule(mods[i][0], rules), []).append(i)

    result = []
    for key, indices in groups.items():
        allowed = {
            aa.strip().upper() for aa in rules[key]["aa"].split(",") if aa.strip()
        }
        candidates = [
            pos
            for pos, aa in enumerate(peptide.upper(), start=1)
            if (not allowed or aa in allowed) and pos not in fixed_positions
        ]
        result.append((key, indices, candidates))
    return result


def candidate_site_count(peptide, mods, rules):
    """Number of distinct residues any movable mod could be placed on."""
    mods = [(float(m[0]), int(m[1])) for m in mods]
    return len(
        {pos for _, _, cands in _candidate_groups(peptide, mods, rules) for pos in cands}
    )


def enumerate_isoforms(peptide, mods, rules, max_isoforms):
    """Enumerate every placement of the movable modifications.

    Args:
        peptide: bare sequence
        mods: list of (mass, position), 1-indexed positions
        rules: {rounded_mass: {"aa": str, "stack": bool}}
        max_isoforms: cap on the number of isoforms returned

    Returns:
        (isoforms, original_index)
          isoforms: list of mod lists, each in the same order as *mods* so that
                    per-mod configs (e.g. Mod_NL_Config) stay aligned
          original_index: index of the search-engine localisation in *isoforms*
        or None if the number of isoforms exceeds *max_isoforms*.
    """
    original = [(float(m[0]), int(m[1])) for m in mods]
    movable = movable_indices(original, rules)
    if not movable:
        return [original], 0

    groups = _candidate_groups(peptide, original, rules)

    # Identical mods are combined, not permuted; stackable mods may repeat a site
    group_choices = []
    for key, indices, candidates in groups:
        combine = (
            itertools.combinations_with_replacement
            if rules[key].get("stack")
            else itertools.combinations
        )
        group_choices.append((key, indices, list(combine(candidates, len(indices)))))

    original_key = _site_key(original, movable)
    isoforms = []
    original_index = None

    for combo in itertools.product(*(choices for _, _, choices in group_choices)):
        if not _stacking_allowed(group_choices, combo, rules):
            continue
        isoform = list(original)
        for (_, indices, _), sites in zip(group_choices, combo):
            for i, pos in zip(indices, sites):
                isoform[i] = (original[i][0], pos)
        if _site_key(isoform, movable) == original_key:
            original_index = len(isoforms)
        isoforms.append(isoform)
        if len(isoforms) > max_isoforms:
            return None

    # The search engine's own sites are always scored, even when they fall
    # outside the allowed residues.
    if original_index is None:
        original_index = len(isoforms)
        isoforms.append(original)
        if len(isoforms) > max_isoforms:
            return None

    return isoforms, original_index


def _stacking_allowed(group_choices, combo, rules):
    """A residue may hold several movable mods only if all of them stack."""
    counts = Counter()
    non_stacking = set()
    for (key, _, _), sites in zip(group_choices, combo):
        counts.update(sites)
        if not rules[key].get("stack"):
            non_stacking.update(sites)
    return all(n == 1 or pos not in non_stacking for pos, n in counts.items())


def _site_key(mods, movable):
    return tuple(sorted((round(mods[i][0], 4), mods[i][1]) for i in movable))


def format_sites(peptide, mods, indices):
    """Format movable-mod sites, e.g. 'S5;T9' or 'S11x2' for stacked mods
    (mass added when the movable mods differ)."""
    if not indices:
        return ""
    show_mass = len({round(mods[i][0], 2) for i in indices}) > 1
    counts = Counter((mods[i][1], round(mods[i][0], 2)) for i in indices)
    parts = []
    for pos, mass in sorted(counts):
        aa = peptide[pos - 1] if 0 < pos <= len(peptide) else "?"
        label = f"{aa}{pos}({mass:.2f})" if show_mass else f"{aa}{pos}"
        n = counts[(pos, mass)]
        parts.append(f"{label}x{n}" if n > 1 else label)
    return ";".join(parts)


def site_evidence(peptide, mods, movable, rules, n_ions, c_ions):
    """Direct fragment evidence for each movable-mod site, in format_sites order.

    Args:
        n_ions / c_ions: {ion number: display label} of matched N-/C-terminal ions

    Returns:
        (n_evidence, c_evidence, excluded)
          n_evidence: 'c2/c3;c9/-' – nearest matched N-terminal ion without the
                      site / nearest with it ('-' when absent), so the mod is
                      confined between the two
          c_evidence: 'z18/z19;-/-' – the same for C-terminal ions
          excluded:   '2/2;0/1' – alternative candidate sites ruled out by an
                      ion that covers the site but not the alternative
    """
    if not movable:
        return "", "", ""
    pep_len = len(peptide)
    # C-terminal ion number k starts at residue L - k + 1
    c_starts = {pep_len - k + 1 for k in c_ions}

    alternatives = {}
    for _, indices, candidates in _candidate_groups(peptide, mods, rules):
        occupied = {mods[i][1] for i in indices}
        for i in indices:
            alternatives[i] = [q for q in candidates if q not in occupied]

    def bracket(ions, first_with_site):
        without = max((k for k in ions if k < first_with_site), default=None)
        with_site = min((k for k in ions if k >= first_with_site), default=None)
        return "/".join(
            ions[k] if k is not None else "-" for k in (without, with_site)
        )

    n_evidence, c_evidence, excluded = [], [], []
    for pos, mass in sorted({(mods[i][1], round(mods[i][0], 2)) for i in movable}):
        i = next(
            j for j in movable if mods[j][1] == pos and round(mods[j][0], 2) == mass
        )
        n_evidence.append(bracket(n_ions, pos))
        c_evidence.append(bracket(c_ions, pep_len - pos + 1))

        alts = alternatives.get(i, [])
        ruled_out = sum(
            1
            for q in alts
            if (q > pos and any(pos <= n < q for n in n_ions))
            or (q < pos and any(q < s <= pos for s in c_starts))
        )
        excluded.append(f"{ruled_out}/{len(alts)}")
    return ";".join(n_evidence), ";".join(c_evidence), ";".join(excluded)


def format_modified_peptide(peptide, mods):
    """Canonical modified sequence, e.g. 'PEPS[79.9663]TIDE'."""
    by_pos = {}
    for mass, pos in mods or []:
        by_pos.setdefault(int(pos), []).append(float(mass))
    out = []
    for pos, aa in enumerate(peptide, start=1):
        out.append(aa)
        for mass in sorted(by_pos.get(pos, [])):
            out.append(f"[{mass:.4f}]")
    return "".join(out)
