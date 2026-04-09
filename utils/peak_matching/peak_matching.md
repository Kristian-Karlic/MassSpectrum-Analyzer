# peak_matching Module

Peptide fragment ion generation, filtering, and experimental peak matching for tandem mass spectrometry (MS/MS) analysis.

## Module Layout

```
utils/peak_matching/
    __init__.py                          # Package init
    constants.py                         # Mass constants, amino acid data, ion colors
    fragmentation.py                     # Fragment ion generation and filtering
    matching.py                          # Peak matching engine
    peptide_fragmentation.py             # Backward-compat re-export shim
    persistent_fragmentation_worker.py   # Threaded Qt worker with LRU cache
```

All public symbols are re-exported through `peptide_fragmentation.py`, so existing imports like `from utils.peak_matching.peptide_fragmentation import calculate_fragment_ions` continue to work.

---

## constants.py

Pure data module. No functions, no external dependencies.

### Key Exports

| Name | Type | Description |
|------|------|-------------|
| `AMINO_ACID_MASSES` | `dict[str, float]` | Monoisotopic masses for the 20 standard amino acids (single-letter codes). |
| `SIDECHAIN_LEAVING_GROUPS` | `dict[str, list[tuple]]` | Per-amino-acid sidechain radical losses for d/w satellite ions. Each entry is `(suffix_label, radical_mass)`. G/A/P have empty lists. |
| `V_ION_EXCLUDED_AA` | `set[str]` | Amino acids excluded from v-ion generation: `{"G", "A", "P"}`. |
| `H`, `O`, `C`, `N`, `S`, `P` | `float` | Elemental monoisotopic masses. |
| `E` | `float` | Electron mass (0.000549 Da). |
| `C13` | `float` | Carbon-13 mass shift (1.003355 Da). |
| `H2O`, `NH3`, `NH2`, `CO`, `H3PO4`, `SOCH4`, `C2H2NO` | `float` | Common compound masses derived from elemental masses. |
| `H_ion` | `float` | Proton mass (1.007276 Da). |
| `ion_colors` | `dict[str, str]` | Default display colors keyed by ion type (e.g. `"y"` -> `"red"`). |
| `_SUPERSCRIPT` | `str.maketrans` | Translation table for superscript digit rendering (used in NL/RM tags). |

---

## fragmentation.py

Core fragment ion generation and filtering logic.

### `calculate_fragment_ions`

The main workhorse. Generates all theoretical fragment ions for a peptide.

```python
calculate_fragment_ions(
    peptide_sequence: str,
    modifications: list[tuple[float, int]] | None = None,
    max_charge: int = 2,
    ion_types: list[str] | None = None,
    Internal: list[str] | None = None,
    custom_ion_series: list[dict] | None = None,
    max_neutral_losses: int = 1,
    calculate_isotopes: bool = True,
    mod_neutral_losses: list[dict] | None = None,
) -> pd.DataFrame
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `peptide_sequence` | required | Amino acid sequence string (e.g. `"PEPTIDE"`). |
| `modifications` | `[]` | List of `(mass_delta, 1-based_position)` tuples. |
| `max_charge` | `2` | Maximum charge state to generate (1 through max_charge). |
| `ion_types` | `["y","b","MH"]` | Which ion series to generate. Standard: `a, b, c, c-1, x, y, z, z+1, MH`. Neutral losses: `y-H2O, b-NH3, ...`. Satellite: `d, w, v`. MH losses: `MH-H2O, MH-NH3`. |
| `Internal` | `[]` | Internal fragment types to generate (`"a"` and/or `"b"`). |
| `custom_ion_series` | `[]` | Custom ion definitions, each a dict with keys: `name`, `base` (parent ion type), `offset` (mass offset), `color`, `restriction` (optional filter string). |
| `max_neutral_losses` | `1` | Max number of stacked neutral losses of the same type (e.g. 2 means y-2H2O is allowed). |
| `calculate_isotopes` | `True` | Whether to generate isotope peaks (+1 through +4). |
| `mod_neutral_losses` | `None` | Per-modification neutral loss configs. Each entry is a dict with keys: `neutral_losses` (list of masses), `labile_loss` (bool), `mod_mass` (float), `generate_labile_ion` (bool), `remainder_ions` (list of masses). |

**Returns:** `pd.DataFrame` with columns:

| Column | Type | Description |
|--------|------|-------------|
| `Theoretical Mass` | float | Calculated m/z value. |
| `Ion Number` | int/str | Cleavage position (1-indexed), or `"3-5"` for internal fragments. |
| `Ion Type` | str | Full ion label (e.g. `"y"`, `"b-H2O"`, `"z**+1"`, `"da"`, `"v"`). |
| `Fragment Sequence` | str | Amino acid sequence of the fragment. |
| `Neutral Loss` | str | Loss type (`"None"`, `"H2O"`, `"NH3"`, `"ModNL1"`, `"LabileLoss"`, etc.). |
| `Charge` | int | Charge state. |
| `Isotope` | int | Isotope offset (-1, 0, 1, 2, 3, 4). 0 = monoisotopic. |
| `Color` | str | Display color string. |
| `Base Type` | str | Cleaned base ion type (e.g. `"y"`, `"b"`, `"d"`, `"w"`). |
| `Ion Series Type` | str | One of: `"Standard-Ion-Series"`, `"Satellite-Ion-Series"`, `"Custom-Ion-Series"`, `"Mod-NL-Series"`, `"Internal-Ion"`. |

**Ion generation pipeline within the function:**

1. Iterates over each cleavage position `i` (1 to n-1)
2. Computes prefix/suffix masses incrementally
3. Generates standard ions (a/b/c/x/y/z and variants) with neutral losses
4. Generates satellite ions (d from a-ion, w from z-ion, v from y-ion) with sidechain losses
5. Generates custom ion series with restriction filtering
6. Generates modification-specific neutral losses (*, ~, ^) including cumulative stacked losses
7. Generates endpoint satellite ions at position n
8. Generates internal fragments (nested loop over start/end positions)

---

### `filter_ions`

```python
filter_ions(df: pd.DataFrame) -> pd.DataFrame
```

Applies chemical validity filters to the output of `calculate_fragment_ions`:

- Removes neutral losses that exceed the available donor amino acids (e.g. 2xH2O loss but only 1 S/T/E/D in fragment).
- H2O loss requires S, T, E, or D in the fragment.
- NH3 loss requires R, K, Q, or N.
- H3PO4 loss requires S, T, or Y.
- SOCH4 loss requires M.
- z/z+1/w ions starting with Proline are removed.
- c-based ions ending with Proline are removed.
- Calls `process_neutral_losses_and_base_types` and deduplicates.

**Input/Output:** Same DataFrame schema as `calculate_fragment_ions`.

---

### `generate_multiple_neutral_losses`

```python
generate_multiple_neutral_losses(
    base_mass: float,
    sequence: str,
    ion_type: str,
    max_losses: int = 5,
    selected_ion_types: list[str] | None = None,
    base_type: str | None = None,
) -> list[tuple[float, str, str, int]]
```

Generates neutral loss variants (H2O, NH3, H3PO4, SOCH4) for a given ion.

When `selected_ion_types` and `base_type` are provided, only generates losses whose corresponding base loss type (e.g. `"y-H2O"`) is in the selected types. This is used for custom ion series.

**Returns:** List of `(modified_mass, loss_description, loss_type, loss_count)` tuples.

---

### Helper Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `check_restriction` | `(fragment_seq, restriction_str, base_type, peptide_sequence) -> bool` | Checks if a fragment meets custom ion series restriction criteria (amino acid presence, N/C-term context). |
| `count_amino_acids_for_neutral_loss` | `(sequence, loss_type) -> int` | Counts residues in `sequence` that can donate the given loss type. |
| `get_neutral_loss_mass` | `(loss_type) -> float` | Returns the mass for a loss type name (`"H2O"`, `"NH3"`, etc.). |
| `process_neutral_losses_and_base_types` | `(df) -> pd.DataFrame` | Cleans the `Base Type` column by extracting embedded neutral loss info and normalizing variant suffixes (e.g. `z+1` -> `z`). |
| `_nl_tag` | `(index: int) -> str` | Generates NL display tags: 0->`*`, 1->`**`, 2->`***`, 3->`*⁴`, etc. |
| `_rm_tag` | `(index: int) -> str` | Generates remainder display tags: 0->`^`, 1->`^^`, 2->`^^^`, 3->`^⁴`, etc. |
| `_insert_mod_nl_tag` | `(ion_type, tag) -> str` | Inserts a tag into ion names, handling `z+1` and `c-1` specially (e.g. `z+1` + `**` -> `z**+1`). |
| `_clean_base_type` | `(ion_type) -> str` | Strips `+1`/`-1` suffixes from ion type strings. |

---

## matching.py

Peak matching engine for comparing experimental m/z values against theoretical fragments.

### `match_fragment_ions`

```python
match_fragment_ions(
    calculated_ions: list[dict],
    user_mz_values: list[tuple[float, float]],
    ppm_tolerance: float = 10,
) -> pd.DataFrame
```

Full-featured matching used in the interactive GUI. Matches observed peaks to theoretical ions within a PPM tolerance window.

**Inputs:**

| Parameter | Description |
|-----------|-------------|
| `calculated_ions` | List of dicts (from `df.to_dict(orient='records')`), each with keys matching the DataFrame columns from `calculate_fragment_ions`. |
| `user_mz_values` | List of `(mz, intensity)` tuples from the experimental spectrum. |
| `ppm_tolerance` | Parts-per-million tolerance for matching (default 10). |

**Returns:** `pd.DataFrame` with columns:

| Column | Description |
|--------|-------------|
| `m/z` | Observed m/z value. |
| `intensity` | Observed intensity. |
| `Matched` | Theoretical mass if matched, `"No Match"` otherwise. |
| `error_ppm` | PPM error of the match (None if unmatched). |
| `Alternative Matches` | JSON string of other monoisotopic candidates within tolerance. |
| `Ion Number`, `Ion Type`, `Fragment Sequence`, `Neutral Loss`, `Charge`, `Isotope`, `Color`, `Base Type`, `Ion Series Type` | Ion metadata (None if unmatched). |

**Matching algorithm:**

1. Sorts theoretical masses and uses binary search (`np.searchsorted`) for O(log n) candidate lookup.
2. For each observed peak, finds all theoretical candidates within the PPM window.
3. Candidates are ranked by ascending PPM error.
4. Isotope peaks (Isotope > 0) are only matched if their monoisotopic base ion is already matched.
5. Each theoretical ion can only match one observed peak (greedy, first-come assignment).
6. Tracks alternative matches for ambiguity reporting.

---

### `match_fragment_ions_fast`

```python
match_fragment_ions_fast(
    theoretical_tuples: list[tuple],
    user_mz_values: list[tuple[float, float]],
    ppm_tolerance: float = 10,
    diagnostic_ions: list[tuple[str, float, str]] | None = None,
) -> list[tuple]
```

Optimized matching for the batch rescoring pipeline. Same algorithm as `match_fragment_ions` but:

- Accepts raw tuples instead of dicts (avoids DataFrame overhead).
- Skips alternative match tracking.
- Returns a list of 12-element tuples instead of a DataFrame.
- Can inject diagnostic ions directly.

**Tuple format (input):** `(mass, ion_num, ion_type, frag_seq, neutral_loss, charge, isotope, color, base_type)`

**Tuple format (output):** `(mz, intensity, matched_mass, error_ppm, ion_num, ion_type, frag_seq, neutral_loss, charge, isotope, color, base_type)`

---

### `fragment_and_match_peaks_cached`

```python
fragment_and_match_peaks_cached(
    peptide, modifications, max_charge, ppm_tolerance,
    selected_ions, selected_internal_ions, user_mz_values,
    diagnostic_ions=None, custom_ion_series_list=None,
    max_neutral_losses=1, mod_neutral_losses=None,
) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[None, None]
```

Convenience wrapper that runs the full pipeline synchronously:
1. `calculate_fragment_ions` -> 2. `filter_ions` -> 3. Append diagnostic ions -> 4. `match_fragment_ions`

Returns `(matched_data_df, theoretical_data_df)` or `(None, None)` on failure.

Used by `spectrum_tracking.py` and `relocalisation_widget.py` for synchronous (non-threaded) fragmentation.

---

## persistent_fragmentation_worker.py

Qt-threaded fragmentation worker with LRU caching. Used by the main GUI for interactive fragmentation.

### `FragmentationTask`

Data container holding all parameters for a single fragmentation job. Attributes mirror the parameters of `calculate_fragment_ions` plus `ppm_tolerance`, `user_mz_values`, and `diagnostic_ions`.

### `PersistentFragmentationWorker(QObject)`

Long-lived worker that runs in a dedicated `QThread`. Processes fragmentation tasks from a queue.

**Signals:**

| Signal | Signature | Description |
|--------|-----------|-------------|
| `progressChanged` | `(int, str)` | Progress percentage and task_id. |
| `finished` | `(object, str)` | Result tuple `(matched_df, theoretical_df)` and task_id. |
| `error` | `(str, str)` | Error message and task_id. |
| `cacheHit` | `()` | Emitted when a cached result is reused. |
| `cacheMiss` | `()` | Emitted when fresh computation is needed. |

**Cache:** Uses `collections.OrderedDict` for true LRU eviction. Cache keys are MD5 hashes of the task parameters. On cache hit, the entry is moved to the end (`move_to_end`). When the cache exceeds 100 entries, the least-recently-used entry is evicted via `popitem(last=False)`.

**Processing pipeline (per task):**
1. Check cache -> return cached result if available
2. `calculate_fragment_ions` -> `filter_ions` -> cache result
3. Append diagnostic ions
4. `match_fragment_ions` against experimental spectrum
5. Emit `(matched_data, theoretical_data)` via `finished` signal

### `PersistentFragmentationManager(QObject)`

Manager that owns the worker thread. Provides `submit_task(...)` for the GUI and forwards signals with task_id filtering (only the latest task's signals are forwarded).

**Key methods:**

| Method | Description |
|--------|-------------|
| `submit_task(...)` | Creates a `FragmentationTask`, enqueues it, returns `task_id`. Cancels any pending prior task. |
| `shutdown()` | Gracefully stops the worker thread with timeout and fallback termination. |

**Signals:** Same as worker but without `task_id` (filtered to current task): `progressChanged(int)`, `finished(object)`, `error(str)`, `cacheHit()`, `cacheMiss()`.

---

## Import Map

All existing import paths are preserved via the backward-compatibility shim in `peptide_fragmentation.py`:

| Consumer | Import |
|----------|--------|
| `utils/__init__.py` | `from .peak_matching.peptide_fragmentation import calculate_fragment_ions, match_fragment_ions, match_fragment_ions_fast, filter_ions` |
| `fragmentation_tab.py` | `from utils.peak_matching.peptide_fragmentation import calculate_fragment_ions, match_fragment_ions` |
| `threaded_fragmentation_functions.py` | `from utils import calculate_fragment_ions, filter_ions, match_fragment_ions, match_fragment_ions_fast` |
| `spectrum_tracking.py` | `from utils.peak_matching.peptide_fragmentation import fragment_and_match_peaks_cached` |
| `relocalisation_widget.py` | `from utils.peak_matching.peptide_fragmentation import fragment_and_match_peaks_cached` |
| `event_handlers.py` | `from utils.peak_matching.peptide_fragmentation import _nl_tag, _rm_tag` |
| `GUI.py` | `from utils.peak_matching.persistent_fragmentation_worker import PersistentFragmentationManager` |
