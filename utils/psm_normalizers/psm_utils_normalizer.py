"""
PSMUtilsNormalizer
==================
Generic normalizer that delegates file reading to the psm_utils library.

Any format with a psm_utils reader can be loaded here and converted to the
application's internal column schema via ProForma 2.0 parsing.

Supported format keys
---------------------
PEAKS       – PEAKS Studio export CSV
Sage        – Sage search engine TSV
Percolator  – Percolator .pin / .pout
mzIdentML   – mzIdentML (.mzid)
XTandem     – X!Tandem XML
IdXML       – OpenMS idXML

ProForma parsing
----------------
psm_utils stores the peptide + charge in a single ProForma string, e.g.:
    PEPTM[+15.9949]IDE/3   -> sequence=PEPTMIDE, mods=[(15.9949, 5)], charge=3
    C[+57.0215]EPTIDE/2    -> sequence=CEPTIDE,  mods=[(57.0215, 1)], charge=2
    [+42.0106]-PEPTIDE/2   -> n-term acetyl at position 1, charge=2

Named modifications (e.g. C[Carbamidomethyl]) are resolved via psm_utils'
internal mass database where possible.  Unresolvable named modifications are
still reported to the experiment manager so the user can supply masses.
"""

from __future__ import annotations

import importlib
import re
from typing import List, Tuple, Optional, Set

import pandas as pd

from .base_normalizer import PSMNormalizer

# ---------------------------------------------------------------------------
# ProForma parsing helpers
# ---------------------------------------------------------------------------

# Matches the content inside one pair of square brackets (non-nested)
_BRACKET_RE = re.compile(r'\[([^\[\]]*)\]')


# Default terminal group masses (monoisotopic)
_DEFAULT_NTERM_MASS = 1.00782503207  # H
_DEFAULT_CTERM_MASS = 18.01056468407  # OH2


def _parse_proforma_string(
    pf_str: str,
    correct_terminal_masses: bool = False,
) -> Tuple[str, List[Tuple[float, int]], Optional[int]]:
    """Parse a ProForma 2.0 string into internal components.

    Parameters
    ----------
    pf_str : str
        ProForma 2.0 string, e.g. ``"PEP[+79.966]TIDE/2"`` or
        ``"[+42.011]-PEPTIDE-[+102.115]/3"``.
    correct_terminal_masses : bool
        If *True*, terminal modification masses are assumed to be **total
        terminal-group masses** (as found in pepXML) rather than deltas.
        The default terminal-group mass (H for N-term, OH for C-term) is
        subtracted to yield the true modification delta.

    Returns
    -------
    bare_sequence : str
        Unmodified amino-acid sequence.
    parsed_mods : list of (mass: float, position: int)
        1-indexed residue positions.  N-terminal modifications are placed at
        position 1, C-terminal modifications at *len(sequence)*.
    charge : int or None
    """
    # --- split charge ---
    charge: Optional[int] = None
    if '/' in pf_str:
        seq_part, charge_str = pf_str.rsplit('/', 1)
        try:
            charge = int(charge_str.strip())
        except ValueError:
            seq_part = pf_str
    else:
        seq_part = pf_str

    bare_chars: List[str] = []
    # accumulate (mass, pos):  0 = n-term sentinel,  -1 = c-term sentinel
    raw_mods: List[Tuple[float, int]] = []

    position = 0  # 1-indexed residue counter
    i = 0

    while i < len(seq_part):
        ch = seq_part[i]

        if ch.isalpha() and ch.isupper():
            # Standard amino-acid residue
            position += 1
            bare_chars.append(ch)
            i += 1
            # Consume every bracket immediately following this residue
            while i < len(seq_part) and seq_part[i] == '[':
                close = seq_part.find(']', i)
                if close == -1:
                    break
                mod_content = seq_part[i + 1 : close]
                mass = _resolve_mod_mass(mod_content)
                if mass is not None:
                    raw_mods.append((mass, position))
                i = close + 1

        elif ch == '-' and i + 1 < len(seq_part) and seq_part[i + 1] == '[':
            # C-terminal modification: "-[mod]" after the last residue
            i += 1  # skip the '-'
            close = seq_part.find(']', i)
            if close == -1:
                i += 1
                continue
            mod_content = seq_part[i + 1 : close]
            mass = _resolve_mod_mass(mod_content)
            if mass is not None:
                raw_mods.append((mass, -1))  # -1 = C-terminal sentinel
            i = close + 1

        elif ch == '[':
            # Bracket before any residue → N-terminal modification
            close = seq_part.find(']', i)
            if close == -1:
                i += 1
                continue
            mod_content = seq_part[i + 1 : close]
            mass = _resolve_mod_mass(mod_content)
            if mass is not None:
                raw_mods.append((mass, 0))  # 0 = N-terminal sentinel
            i = close + 1
            # Consume the '-' separator that follows n-term brackets, e.g. "[mod]-SEQ"
            if i < len(seq_part) and seq_part[i] == '-':
                i += 1

        else:
            i += 1

    # Remap terminal sentinels to concrete positions and optionally
    # correct total-mass values from pepXML to delta masses.
    seq_len = len(bare_chars)
    parsed_mods: List[Tuple[float, int]] = []
    for mass, pos in raw_mods:
        if pos == 0:
            # N-terminal → position 1
            if correct_terminal_masses:
                mass -= _DEFAULT_NTERM_MASS
            parsed_mods.append((mass, 1))
        elif pos == -1:
            # C-terminal → last residue position
            if correct_terminal_masses:
                mass -= _DEFAULT_CTERM_MASS
            parsed_mods.append((mass, seq_len))
        else:
            parsed_mods.append((mass, pos))

    return ''.join(bare_chars), parsed_mods, charge


def _resolve_mod_mass(mod_content: str) -> Optional[float]:
    """Convert ProForma bracket content to a numeric mass.

    Handles:
    - Mass-shift:  ``+15.9949``, ``-17.0265``, ``+57.0215``
    - UNIMOD ID:   ``UNIMOD:21``
    - Named mod:   ``Oxidation``, ``Carbamidomethyl``  (via psm_utils database)
    """
    content = mod_content.strip()

    # 1. Mass-shift notation
    if content and content[0] in ('+', '-'):
        try:
            return float(content)
        except ValueError:
            pass

    # 2. Plain numeric (unlikely but handle it)
    try:
        return float(content)
    except ValueError:
        pass

    # 3. UNIMOD: prefix  (psm_utils uses this for named lookups)
    if content.upper().startswith('UNIMOD:'):
        return _unimod_mass(content[7:])

    # 4. Named modification – try psm_utils modification database
    return _named_mod_mass(content)


def _unimod_mass(unimod_id: str) -> Optional[float]:
    """Look up monoisotopic mass by UNIMOD accession number."""
    try:
        from psm_utils.proforma.proforma import Modification
        mod = Modification(f'UNIMOD:{unimod_id}')
        return float(mod.mass)
    except Exception:
        pass
    # Fallback via pyteomics if available
    try:
        from pyteomics import mass as pyteomics_mass
        db = pyteomics_mass.Unimod()
        entry = db.by_id(int(unimod_id))
        if entry:
            return float(entry['mono_mass'])
    except Exception:
        pass
    return None


# Cache for named-mod lookups to avoid repeated imports
_NAMED_MOD_CACHE: dict[str, Optional[float]] = {}

# Minimal built-in fallback table for the most common named modifications
_COMMON_NAMED_MODS: dict[str, float] = {
    'carbamidomethyl':   57.02146,
    'carbamidomethylation': 57.02146,
    'oxidation':         15.99491,
    'phospho':           79.96633,
    'phosphorylation':   79.96633,
    'acetyl':            42.01057,
    'acetylation':       42.01057,
    'methylation':       14.01565,
    'methyl':            14.01565,
    'dimethyl':          28.03130,
    'trimethyl':         42.04695,
    'deamidation':        0.98402,
    'deamidated':         0.98402,
    'pyro-glu':         -17.02655,
    'pyro_glu':         -17.02655,
    'gln->pyro-glu':    -17.02655,
    'glu->pyro-glu':    -18.01056,
    'ammonia-loss':     -17.02655,
    'water-loss':       -18.01056,
    'tmt6plex':         229.16293,
    'tmt':              229.16293,
    'itraq4plex':       144.10207,
    'itraq8plex':       304.20536,
    'propionamide':      71.03711,
    'sulfo':             79.95681,
    'sulfation':         79.95681,
    'ubiquitination':   114.04293,
    'gg':               114.04293,  # GlyGly tag
    'nhs-lc-biotin':    339.16175,
    'formylation':       27.99491,
}


def _named_mod_mass(name: str) -> Optional[float]:
    """Resolve a named modification to its monoisotopic mass."""
    key = name.lower()
    if key in _NAMED_MOD_CACHE:
        return _NAMED_MOD_CACHE[key]

    # 1. Check built-in table
    if key in _COMMON_NAMED_MODS:
        mass = _COMMON_NAMED_MODS[key]
        _NAMED_MOD_CACHE[key] = mass
        return mass

    # 2. Try psm_utils Modification object
    try:
        from psm_utils.proforma.proforma import Modification
        mod = Modification(name)
        mass = float(mod.mass)
        _NAMED_MOD_CACHE[key] = mass
        return mass
    except Exception:
        pass

    # 3. Try pyteomics Unimod by name
    try:
        from pyteomics import mass as pyteomics_mass
        db = pyteomics_mass.Unimod()
        hit = db.by_title(name)
        if hit:
            mass = float(hit[0]['mono_mass'])
            _NAMED_MOD_CACHE[key] = mass
            return mass
    except Exception:
        pass

    _NAMED_MOD_CACHE[key] = None
    return None


def _collect_named_mods(pf_str: str) -> Set[str]:
    """Return any named (non-numeric) modification names in a ProForma string."""
    named: Set[str] = set()
    for content in _BRACKET_RE.findall(pf_str):
        content = content.strip()
        if not content:
            continue
        if content[0] in ('+', '-'):
            continue  # mass-shift
        if content.upper().startswith('UNIMOD:'):
            continue
        try:
            float(content)
            continue  # plain numeric
        except ValueError:
            pass
        if _named_mod_mass(content) is None:
            named.add(content)
    return named


# ---------------------------------------------------------------------------
# Spectrum-ID parsing
# ---------------------------------------------------------------------------

# Regex for NativeID "controllerType=0 controllerNumber=1 scan=12345"
_NATIVEID_SCAN_RE = re.compile(r'scan[=:](\d+)', re.IGNORECASE)

# Regex for pepXML-style "basename.startScan.endScan.charge"
# The last three dot-separated tokens must all be digits.
_PEPXML_SPEC_RE = re.compile(r'^(.+?)\.(\d+)\.(\d+)\.(\d+)$')


def _parse_spectrum_id(spec_id: str) -> Tuple[str, str]:
    """Parse a spectrum identifier into (scan_number, run_name).

    Handles the following common formats:

    1. Plain integer:            ``"26797"``
    2. NativeID key=value:       ``"controllerType=0 controllerNumber=1 scan=26797"``
    3. ``scan=N`` shorthand:     ``"scan=26797"``
    4. pepXML / Comet / TPP:     ``"basename.startScan.endScan.charge"``
       e.g. ``"20250128_KT-10169_D12_A1.26797.26797.3"``

    Returns
    -------
    scan_number : str
        The numeric scan number as a string (leading zeros stripped).
    run_name : str
        The run / raw-file basename extracted from the identifier, or ``""``
        if the identifier does not encode a run name.
    """
    spec_id = spec_id.strip()
    if not spec_id or spec_id.lower() in ('nan', 'none'):
        return '', ''

    # 1. Plain integer
    if spec_id.isdigit():
        return spec_id.lstrip('0') or '0', ''

    # 2. NativeID / "scan=N" style
    m = _NATIVEID_SCAN_RE.search(spec_id)
    if m:
        return m.group(1).lstrip('0') or '0', ''

    # 3. pepXML "basename.startScan.endScan.charge"
    m = _PEPXML_SPEC_RE.match(spec_id)
    if m:
        run_name = m.group(1)
        scan = m.group(2).lstrip('0') or '0'
        # Strip common extensions from the run name portion
        for ext in ('.raw', '.mzml', '.mzML', '.d', '.mgf'):
            if run_name.lower().endswith(ext.lower()):
                run_name = run_name[:len(run_name) - len(ext)]
                break
        return scan, run_name

    # 4. Fallback: return as-is
    return spec_id, ''


# ---------------------------------------------------------------------------
# pepXML score-key priority
# ---------------------------------------------------------------------------

#: Preferred score keys for pepXML files, tried in order.
#: "hyperscore" (MSFragger / X!Tandem) is preferred over "expect" (E-value)
#: because hyperscore is a direct match-quality metric used for spectral
#: annotation, whereas expect is a statistical significance measure.
_PEPXML_SCORE_PRIORITY = [
    "hyperscore",    # MSFragger / X!Tandem
    "xcorr",         # Comet / SEQUEST
    "expect",        # X!Tandem E-value (fallback)
    "EValue",        # MS-GF+
    "SpecEValue",    # MS-GF+ spectral E-value
    "delta_dot",     # SpectraST
]


# ---------------------------------------------------------------------------
# Reader registry
# ---------------------------------------------------------------------------

#: Maps format key → (psm_utils module path, reader class name)
READER_REGISTRY: dict[str, tuple[str, str]] = {
    'PEAKS':      ('psm_utils.io.peaks',      'PEAKSReader'),
    'Sage':       ('psm_utils.io.sage',        'SageReader'),
    'Percolator': ('psm_utils.io.percolator',  'PercolatorReader'),
    'mzIdentML':  ('psm_utils.io.mzidentml',   'MzIdentMLReader'),
    'XTandem':    ('psm_utils.io.xtandem',     'XTandemReader'),
    'IdXML':      ('psm_utils.io.idxml',       'IdXMLReader'),
    'pepXML':     ('psm_utils.io.pepxml',      'PepXMLReader'),
}

#: Human-readable labels for the format selector dialog
FORMAT_LABELS: dict[str, str] = {
    'PEAKS':      'PEAKS Studio (CSV)',
    'Sage':       'Sage search engine (TSV)',
    'Percolator': 'Percolator (pin / pout)',
    'mzIdentML':  'mzIdentML (.mzid)',
    'XTandem':    'X!Tandem (XML)',
    'IdXML':      'OpenMS idXML',
    'pepXML':     'pepXML (.pep.xml / .pepxml)',
}


def available_formats() -> list[str]:
    """Return format keys for which psm_utils has a readable reader."""
    available = []
    for key, (module_path, class_name) in READER_REGISTRY.items():
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, class_name):
                available.append(key)
        except ImportError:
            pass
    return available


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

class PSMUtilsNormalizer(PSMNormalizer):
    """Normalizer backed by a psm_utils reader for any supported format."""

    def __init__(self, format_key: str, source_file_path: str):
        if format_key not in READER_REGISTRY:
            raise ValueError(
                f"Unknown psm_utils format key '{format_key}'. "
                f"Valid keys: {list(READER_REGISTRY)}"
            )
        self.format_key = format_key
        self.source_file_path = source_file_path

    # ------------------------------------------------------------------
    # PSMNormalizer interface
    # ------------------------------------------------------------------

    def get_engine_name(self) -> str:
        return FORMAT_LABELS.get(self.format_key, self.format_key)

    def normalize(self, df=None) -> pd.DataFrame:
        """Read the file via psm_utils and return the internal column schema."""
        psms = self._read_psms()
        rows = [self._psm_to_row(psm) for psm in psms]
        result = pd.DataFrame(rows, columns=PSMNormalizer.INTERNAL_COLUMNS)
        self.validate_output(result)
        return result

    def get_unknown_modifications(self, df=None) -> Set[str]:
        """Pre-scan all PSMs and return modification names that cannot be resolved."""
        psms = self._read_psms()
        unresolved: Set[str] = set()
        for psm in psms:
            if psm.peptidoform is None:
                continue
            pf_str = str(psm.peptidoform)
            unresolved.update(_collect_named_mods(pf_str))
        return unresolved

    def extract_spectrum_files(self, df=None) -> set[str]:
        """Return unique run names (raw file stems) from the file."""
        try:
            psms = self._read_psms()
            return {psm.run for psm in psms if psm.run}
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_psms(self) -> list:
        module_path, class_name = READER_REGISTRY[self.format_key]
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise ImportError(
                f"Cannot load psm_utils reader for '{self.format_key}'. "
                f"Make sure psm_utils is installed: {exc}"
            ) from exc
        reader_cls = getattr(mod, class_name)

        # pepXML: try preferred score keys before falling back to default
        # auto-inference (which picks "expect" over "hyperscore")
        if self.format_key == 'pepXML':
            for score_key in _PEPXML_SCORE_PRIORITY:
                try:
                    with reader_cls(self.source_file_path, score_key=score_key) as reader:
                        return list(reader)
                except (KeyError, ValueError, Exception) as exc:
                    # score_key not found in this file's search_scores — try next
                    if 'score' in str(exc).lower() or isinstance(exc, KeyError):
                        print(f"[DEBUG] pepXML score_key '{score_key}' not available, trying next...")
                        continue
                    raise
            # All preferred keys failed — fall back to psm_utils default
            print("[DEBUG] No preferred pepXML score key found; using psm_utils default")

        with reader_cls(self.source_file_path) as reader:
            return list(reader)

    def _psm_to_row(self, psm) -> dict:
        """Convert a single psm_utils PSM object to the internal row dict."""
        pf_str = str(psm.peptidoform) if psm.peptidoform is not None else ''
        bare_seq, parsed_mods, charge = _parse_proforma_string(
            pf_str,
            correct_terminal_masses=(self.format_key == 'pepXML'),
        )

        # Encode parsed_mods as list-of-tuples (consistent with other normalizers)
        parsed_mods_out = [(round(m, 6), p) for m, p in parsed_mods]

        # Assigned Modifications: store the ProForma sequence section for display
        seq_section = pf_str.rsplit('/', 1)[0]
        assigned_mods_str = seq_section if parsed_mods else ''

        # Run / spectrum file (stem without extension)
        run = (psm.run or '').strip()
        if run in ('', 'nan', 'None', 'none'):
            run = ''
        if run.lower().endswith(('.raw', '.mzml', '.d')):
            run = run.rsplit('.', 1)[0]

        # Spectrum ID — parse scan number (and optionally run name) from
        # various identifier formats used by different search engines
        spectrum_id = str(psm.spectrum_id or '').strip()
        scan_number, parsed_run = _parse_spectrum_id(spectrum_id)

        # If the reader didn't provide a run name, use the one parsed from
        # the spectrum_id (common for pepXML where spectrum="file.scan.scan.charge")
        if not run and parsed_run:
            run = parsed_run

        # Protein list
        proteins = psm.protein_list or []
        protein_str = '; '.join(str(p) for p in proteins) if proteins else ''

        return {
            'Peptide':               bare_seq,
            'Modified Peptide':      pf_str.rsplit('/', 1)[0],
            'Charge':                charge if charge is not None else 0,
            'Observed M/Z':          float(psm.precursor_mz) if psm.precursor_mz is not None else 0.0,
            'Assigned Modifications': assigned_mods_str,
            'Parsed Modifications':  parsed_mods_out,
            'Hyperscore':            float(psm.score) if psm.score is not None else 0.0,
            'Protein':               protein_str,
            'Peptide Length':        len(bare_seq),
            'Prev AA':               '',
            'Next AA':               '',
            'Protein Start':         '',
            'Protein End':           '',
            'Spectrum file':         run,
            'index':                 scan_number,
        }
