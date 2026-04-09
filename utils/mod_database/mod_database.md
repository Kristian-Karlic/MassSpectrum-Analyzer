# Modification Database API Documentation

This module provides persistent storage and UI editing for protein modification definitions used in mass spectrometry analysis pipelines. Two database backends are supported: engine-specific (MaxQuant/MetaMorpheus) and central (unified).

---

## Database Classes

### `ModificationMassDatabase`

Simple key-value store mapping modification names to monoisotopic masses (Da). Uses JSON for persistence and supports separate instances per search engine.

#### `__init__(json_path: str)`

Create or load a modification database.

- **Inputs:**
  - `json_path`: Path to JSON file for persistence
- **Behavior:** Loads existing JSON if present; otherwise initializes with `DEFAULT_MODIFICATIONS` and saves
- **Output:** Instance with `mods` dict loaded

#### `get_mass(mod_name: str) -> Optional[float]`

Retrieve the monoisotopic mass for a modification name.

- **Inputs:** `mod_name` - modification name (e.g., "Phospho")
- **Output:** Mass in Da (float), or `None` if not found

#### `has_mod(mod_name: str) -> bool`

Check if modification exists in database.

- **Inputs:** `mod_name` - modification name
- **Output:** `True` if found, `False` otherwise

#### `get_all_mods() -> dict[str, float]`

Return a deep copy of all modifications.

- **Output:** Dict mapping modification names to masses

#### `add_mod(mod_name: str, mass: float)`

Add or update a modification. **Auto-saves to disk.**

- **Inputs:**
  - `mod_name` - modification name
  - `mass` - monoisotopic mass in Da
- **Side effects:** Modifies JSON file

#### `remove_mod(mod_name: str)`

Delete a modification if it exists. **Auto-saves to disk.**

- **Inputs:** `mod_name` - modification name
- **Side effects:** Modifies JSON file

#### `update_batch(mod_dict: dict[str, float])`

Update multiple modifications at once. **Auto-saves to disk.**

- **Inputs:** `mod_dict` - dict of `{name: mass}` pairs
- **Side effects:** Modifies JSON file

---

### `CentralModificationDatabase`

Unified database for all modifications, supporting neutral losses, remainder ions, and labile-loss flags. Serves as single source of truth. Automatically migrates from legacy formats.

#### `__init__(json_path: str, csv_fallback_path: str | None = None)`

Create or load the central modification database.

- **Inputs:**
  - `json_path` - JSON file path (primary storage)
  - `csv_fallback_path` - legacy CSV path (optional fallback for migration)
- **Behavior:**
  - If JSON exists: load and auto-migrate old format (neutral_loss_1/2/3 → neutral_losses)
  - Else if CSV exists: import from CSV
  - Else: initialize with `DEFAULT_MODIFICATIONS`
- **Output:** Instance with `mods` dict loaded

#### `get_entry(mod_name: str) -> Optional[dict]`

Retrieve full entry for a modification.

- **Inputs:** `mod_name` - modification name
- **Output:** Entry dict with keys `mass`, `neutral_losses`, `remainder_ions`, `labile_loss`; or `None` if not found

#### `get_mass(mod_name: str) -> Optional[float]`

Retrieve monoisotopic mass only.

- **Inputs:** `mod_name` - modification name
- **Output:** Mass in Da (float), or `None`

#### `get_all_entries() -> dict[str, dict]`

Return deep copy of all entries.

- **Output:** Dict mapping modification names to entry dicts

#### `find_by_mass(mass: float, tolerance: float | None = None) -> Optional[str]`

Reverse-lookup: find modification name by mass.

- **Inputs:**
  - `mass` - mass in Da
  - `tolerance` - search tolerance in Da (default: 0.01)
- **Output:** First matching modification name, or `None`

#### `get_neutral_losses_for_mass(mass: float, tolerance: float | None = None) -> Optional[dict]`

Retrieve full neutral-loss configuration for a mass.

- **Inputs:**
  - `mass` - mass in Da
  - `tolerance` - search tolerance (default: 0.01)
- **Output:** Dict with keys:
  - `neutral_losses`: list[float]
  - `remainder_ions`: list[float]
  - `labile_loss`: bool
  - `mod_mass`: float
  - Or `None` if no match

#### `has_active_neutral_loss(entry: dict, enable_labile: bool, enable_mod_nl: bool) -> bool` (static)

Check if an entry has neutral losses or labile loss enabled.

- **Inputs:**
  - `entry` - modification entry dict
  - `enable_labile` - control whether labile loss counts (default: `True`)
  - `enable_mod_nl` - control whether neutral losses count (default: `True`)
- **Output:** `True` if any loss is active and enabled

#### `as_modification_list() -> list[dict]`

Export as spectrum-viewer compatible format.

- **Output:** List of dicts with `Name` and `Mass` keys

#### `as_dataframe() -> pd.DataFrame`

Export as pandas DataFrame.

- **Output:** DataFrame with columns `['Name', 'Mass']`

#### `add_mod(name: str, mass: float, **kwargs)`

Add modification with optional neutral-loss fields. **Auto-saves to disk.**

- **Inputs:**
  - `name` - modification name
  - `mass` - monoisotopic mass
  - `**kwargs` - optional: `neutral_losses`, `remainder_ions`, `labile_loss`
- **Side effects:** Modifies JSON file

#### `update_mod(name: str, **kwargs)`

Update specific fields of an existing modification. **Auto-saves to disk.**

- **Inputs:**
  - `name` - modification name to update
  - `**kwargs` - fields to update (`mass`, `neutral_losses`, etc.)
- **Side effects:** Modifies JSON file

#### `remove_mod(name: str)`

Delete a modification. **Auto-saves to disk.**

- **Inputs:** `name` - modification name
- **Side effects:** Modifies JSON file

#### `ensure_mass_exists(mass: float, default_name: str | None = None) -> str`

Ensure a mass is in the database (creates entry if needed).

- **Inputs:**
  - `mass` - mass in Da
  - `default_name` - name for new entry (default: `+{mass:.4f}`)
- **Output:** Existing or newly-created modification name
- **Side effects:** Modifies JSON file if creating new entry

---

## UI Dialog Classes

### `UnknownModificationsDialog`

Dialog for user input when unknown modifications are detected during data preparation.

#### `__init__(unknown_mods: set, engine_name: str, parent=None)`

Create dialog for gathering masses for unknown modifications.

- **Inputs:**
  - `unknown_mods` - set of modification names with no database entry
  - `engine_name` - search engine name (e.g., "MaxQuant") for display
  - `parent` - parent widget
- **Output:** Modal dialog instance

#### `get_masses() -> dict[str, float]`

Retrieve user-entered masses after dialog acceptance.

- **Output:** Dict mapping modification names to masses, or empty dict if rejected

---

### `ModDatabaseEditorDialog`

Tabbed editor for MaxQuant and MetaMorpheus engine-specific databases.

#### `__init__(maxquant_db: ModificationMassDatabase, metamorpheus_db: ModificationMassDatabase, parent=None)`

Create tabbed editor for both databases.

- **Inputs:**
  - `maxquant_db` - MaxQuant database instance
  - `metamorpheus_db` - MetaMorpheus database instance
  - `parent` - parent widget
- **Output:** Modal dialog instance

#### User Actions

- **Add Entry:** Inserts blank row with 0.0 mass; focuses name field
- **Delete Selected:** Removes selected rows
- **Save Changes:** Validates all rows, shows error dialog if invalid, saves to JSON if valid

---

### `CentralModEditorDialog`

Editor for the central modification database with 5 columns: Name | Mass | Neutral Losses | Remainder Ions | Labile.

#### `__init__(central_db: CentralModificationDatabase, parent=None)`

Create central database editor.

- **Inputs:**
  - `central_db` - central database instance
  - `parent` - parent widget
- **Output:** Modal dialog instance

#### User Actions

- **Add Entry:** Inserts blank row; focuses name field
- **Delete Selected:** Removes selected rows
- **Double-click Labile column:** Toggles Yes/No value
- **Save Changes:** Validates all rows (including CSV float lists), saves if valid

#### Helper Methods

##### `_read_float(row: int, col: int, label: str) -> float`

Parse cell value as float (empty → 0.0).

- **Inputs:**
  - `row`, `col` - table cell coordinates
  - `label` - field name for error messages
- **Output:** Parsed float
- **Raises:** `ValueError` if parsing fails

##### `_read_csv_floats(row: int, col: int, label: str) -> str`

Validate and return comma-separated float string.

- **Inputs:**
  - `row`, `col` - table cell coordinates
  - `label` - field name for error messages
- **Output:** Validated string (unchanged format)
- **Raises:** `ValueError` if any float invalid

---

## Shared Helper Functions

### `_make_filter_func(table) -> Callable[[str], None]`

Create a row-filter closure for search inputs.

- **Inputs:** `table` - QTableWidget instance
- **Output:** Closure that takes search text and shows/hides rows based on substring match across all columns

### `_wire_search(search_input, table) -> None`

Wire a search input widget to row filtering on a table.

- **Inputs:**
  - `search_input` - QLineEdit instance (search field)
  - `table` - QTableWidget instance
- **Side effects:**
  - Disconnects default signal from search_input
  - Re-connects with row-filter closure
  - Stores closure on `search_input._filter_func` for re-filtering after adds/deletes

### `_create_button_bar(add_cb, delete_cb, save_cb, close_cb) -> QHBoxLayout`

Create standardized button bar with Add / Delete / (stretch) / Save / Close.

- **Inputs:**
  - `add_cb`, `delete_cb`, `save_cb`, `close_cb` - callback functions for button clicks
- **Output:** QHBoxLayout ready to add to dialog

### `_delete_selected_rows(table) -> None`

Remove all selected rows from a table.

- **Inputs:** `table` - QTableWidget instance
- **Side effects:** Deletes selected rows in reverse order (prevents index shifts)

---

## Database Schema

### ModificationMassDatabase JSON

```json
{
  "Phospho": 79.9663,
  "Oxidation": 15.9949,
  "Carbamidomethyl": 57.02146
}
```

### CentralModificationDatabase JSON

```json
{
  "Phospho": {
    "mass": 79.9663,
    "neutral_losses": "97.977,0.0,0.0",
    "remainder_ions": "",
    "labile_loss": false
  },
  "Oxidation": {
    "mass": 15.9949,
    "neutral_losses": "",
    "remainder_ions": "",
    "labile_loss": false
  }
}
```

---

## Error Handling

- **Invalid mass entry:** Dialog warning listing rows with parse errors; user must fix before saving
- **Missing modification name:** Row is skipped; no entry created
- **CSV migration failure:** Falls back to DEFAULT_MODIFICATIONS and logs warning
- **Mass-based lookups:** Returns `None` if no match within tolerance

---

## Logging

Migrate events (format conversion, CSV import) are logged at DEBUG level:
- `"Migrated {count} entries to new NL/RM format"`
- `"Migrated {count} entries from {csv_path}"`
- `"CSV migration failed: {error} – using defaults"`

Configure logging to capture these messages.
