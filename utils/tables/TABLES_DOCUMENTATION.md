# Tables Module Documentation

Documentation for the `utils/tables` module containing table editing, spectrum tracking, data display, and relocalisation widgets.

---

## File Overview

| File | Purpose |
|------|---------|
| `excel_table.py` | Excel-like table widget with copy/paste/fill-down functionality |
| `Color_selection.py` | Color picker delegate for table cells |
| `Custom_ion_series.py` | Restriction dialog and delegates for ion series configuration |
| `tableeditor.py` | Main dialog for editing modifications, diagnostic ions, and custom ion series |
| `spectrum_tracking.py` | Widget for tracking spectrum quality and managing exports |
| `relocalisation_widget.py` | Widget for testing modification positions and ranking by score |
| `psm_summary_widget.py` | Widget for displaying PSM summary and details with filtering |

---

## 1. excel_table.py

### ExcelLikeTableWidget

**Purpose:** QTableWidget with Excel-like functionality (copy, paste, fill-down, multi-cell selection)

#### `__init__(self, *args, **kwargs)`
- **Inputs:** Standard QTableWidget arguments
- **Outputs:** ExcelLikeTableWidget instance
- **Features:** Extended selection mode, keyboard shortcuts for Excel-like operations

#### `set_readonly_columns(self, columns)`
- **Inputs:** `columns` (list/set of 0-indexed column numbers)
- **Outputs:** None (sets internal state)
- **Purpose:** Mark specific columns as read-only to prevent editing

#### `keyPressEvent(self, event)`
- **Inputs:** `event` (QKeyEvent)
- **Outputs:** None
- **Shortcuts:**
  - `Ctrl+C`: Copy selected cells
  - `Ctrl+V`: Paste from clipboard
  - `Ctrl+D`: Fill down (copy first row to rows below)
  - `Delete/Backspace`: Clear selected cells

#### `_copy_selection(self)`
- **Inputs:** None (uses selected cells)
- **Outputs:** Clipboard text (tab-separated, newline per row)

#### `_paste_clipboard(self)`
- **Inputs:** Clipboard content (tab/newline separated)
- **Outputs:** Modified table cells
- **Logic:**
  - Single value → fills all selected cells
  - Multi-value → pastes starting at top-left of selection

#### `_fill_down(self)`
- **Inputs:** None (uses selection range)
- **Outputs:** Modified table rows
- **Logic:** Copies first row's values to all rows below in selection

#### `_clear_selection(self)`
- **Inputs:** None
- **Outputs:** Cleared editable cells
- **Logic:** Clears text in non-readonly selected cells

#### `_get_selected_range(self)`
- **Inputs:** None
- **Outputs:** Tuple `(min_row, max_row, min_col, max_col)` or None
- **Purpose:** Get bounding rectangle of selected cells

### create_search_bar Function

```python
create_search_bar(table, parent=None, placeholder="Search...")
```

- **Inputs:**
  - `table`: QTableWidget to filter
  - `parent`: Parent widget
  - `placeholder`: Search input placeholder text
- **Outputs:** QLineEdit widget with `_filter_func` attribute
- **Functionality:** Case-insensitive substring match filtering on table rows

---

## 2. Color_selection.py

### ColorDelegate

**Purpose:** Custom item delegate for color selection in table cells

#### `createEditor(self, parent, option, index)`
- **Inputs:** Standard QStyledItemDelegate parameters
- **Outputs:** None (opens QColorDialog instead of inline editor)
- **Process:**
  1. Opens QColorDialog
  2. Pre-loads existing color if cell has one
  3. Updates cell with hex color (#RRGGBB) on selection
  4. Triggers immediate repaint

#### `paint(self, painter, option, index)`
- **Inputs:** `painter` (QPainter), `option` (style option), `index` (model index)
- **Outputs:** None (paints cell)
- **Behavior:**
  - Fills cell background with hex color value
  - Displays hex code as text
  - Uses contrasting text color (white for dark, black for light)

---

## 3. Custom_ion_series.py

### RestrictionDialog

**Purpose:** Dialog for configuring amino acid restrictions for custom ion series

#### `__init__(self, current_restriction="", parent=None)`
- **Inputs:**
  - `current_restriction`: String like "E,D" or "C-term,E" (comma-separated)
  - `parent`: Parent widget
- **Outputs:** Dialog instance

#### `_parse_restriction(self, text: str)`
- **Inputs:** `text` (restriction string)
- **Outputs:** None (updates UI checkboxes)
- **Format:**
  - "C-term" or "N-term" for terminus restrictions
  - Single letters (E, D, K, etc.) for amino acids
  - Backwards compatible with old format (e.g., "2E")

#### `get_restriction_string(self) -> str`
- **Inputs:** None (reads UI state)
- **Outputs:** Compact restriction string (e.g., "C-term,E,D")
- **Logic:** Combines checked terminus and amino acid selections

#### `_clear_all(self)`
- **Inputs:** None
- **Outputs:** None (resets all checkboxes)

### RestrictionDelegate

**Purpose:** Table cell delegate that opens RestrictionDialog on double-click

#### `editorEvent(self, event, model, option, index)`
- **Inputs:** Standard QStyledItemDelegate event parameters
- **Outputs:** Boolean (True if event handled)
- **Behavior:** Opens dialog on double-click, updates cell data with result

### BaseIonComboDelegate

**Purpose:** Dropdown delegate for selecting base ion types

#### `__init__(self, base_ions, parent=None)`
- **Inputs:**
  - `base_ions`: List of ion types (e.g., ["b","y","a","c","x","z"])
  - `parent`: Parent widget

#### `createEditor(self, parent, option, index)`
- **Inputs:** Standard parameters
- **Outputs:** QComboBox with ion options

#### `setEditorData(self, editor, index)` / `setModelData(self, editor, model, index)`
- **Purpose:** Sync editor with model data

---

## 4. tableeditor.py

### TableEditorDialog

**Purpose:** Main dialog for editing table data (modifications, diagnostic ions, custom ion series)

#### `__init__(self, data_type, data_df, file_path, parent=None)`
- **Inputs:**
  - `data_type`: "modifications" | "diagnostic_ions" | "custom_ion_series"
  - `data_df`: pandas DataFrame with current data
  - `file_path`: Path to CSV file for saving
  - `parent`: Parent widget
- **Outputs:** Dialog instance
- **Signals:** `data_changed` (emitted on table modifications)

#### `_setup_ui(self)`
- **Purpose:** Build dialog interface based on data_type
- **Column Setup:**
  - **Modifications:** Name, Mass
  - **Diagnostic Ions:** Name, HTML Name, Mass, Color
  - **Custom Ion Series:** Base Ion, Series Name, Mass Offset, Color, Restriction

#### `add_row(self)` / `delete_row(self)` / `duplicate_row(self)`
- **Inputs:** None
- **Outputs:** Modified table
- **add_row default values:**
  - Modifications: "New Modification", "0.0"
  - Diagnostic ions: "New Ion", "", "0.0", "#000000"
  - Custom series: "b", "New Series", "0.0", "#000000", ""

#### `import_csv(self)` / `export_csv(self)`
- **Purpose:** Import/export table data to/from CSV
- **import_csv Behavior:**
  - Validates column names
  - Asks replace vs. append
  - Updates table from imported data

#### `_get_table_data(self) -> pd.DataFrame`
- **Inputs:** None
- **Outputs:** DataFrame with current table data
- **Logic:**
  - Filters out empty rows
  - Auto-fills HTML Name for diagnostic ions if empty
  - Converts Mass columns to numeric
  - Excludes rows with no data

#### `save_changes(self)`
- **Inputs:** None
- **Outputs:** None (saves to CSV, emits data_changed)
- **Validation:**
  - Checks for duplicate names (except custom_ion_series)
  - Validates series names don't contain *, ~, ^
  - Creates backup before saving
  - Confirms empty file saves

#### `save_changes()` Validation Rules
| Rule | Applied to | Effect |
|------|-----------|--------|
| Duplicate name check | modifications, diagnostic_ions | Warning dialog, prevents save |
| Reserved character check | custom_ion_series (Series Name) | Prevents *, ~, ^ usage |
| Numeric conversion | Mass, Mass Offset columns | Converts to numeric type |

#### `get_updated_data(self) -> pd.DataFrame` / `get_data(self)`
- **Outputs:** Updated DataFrame for parent consumption

---

## 5. spectrum_tracking.py

### SpectrumTrackerWidget

**Purpose:** Widget for tracking spectrum quality (accepted/declined) and managing exports

#### `__init__(self, main_app=None, parent=None)`
- **Inputs:**
  - `main_app`: Reference to main application
  - `parent`: Parent widget

#### `set_current_spectrum(self, spectrum_data, settings_data=None)`
- **Inputs:**
  - `spectrum_data`: Dict with Peptide, Charge, M/Z, index, etc.
  - `settings_data`: Dict with user settings (modifications, ion types, etc.)
- **Outputs:** None (updates UI and enables accept/decline buttons)
- **Side Effects:** Updates info label, enables control buttons

#### `_accept_spectrum(self)` / `_decline_spectrum(self)`
- **Inputs:** None (uses current_spectrum_data)
- **Outputs:** None (adds to export list, emits signals)
- **Signals Emitted:**
  - `spectrumAccepted` / `spectrumDeclined`
  - `spectrumAddedToExport`

#### `_add_to_export_list_with_quality(self, quality)`
- **Inputs:** `quality` ("Accepted" or "Declined")
- **Outputs:** None (appends to export DataFrame)
- **Captured Data:**
  - Timestamp, Quality, Fragmented Bonds, Annotated TIC
  - Scoring metrics: XTandem, Consecutive, Complementary, Morpheus
  - All ion type selections (basic, neutral loss, internal, custom, diagnostic)
  - PPM tolerance, max neutral losses, etc.

#### Export list columns:
```python
['Timestamp', 'Peptide', 'Modified Peptide', 'Charge', 'Observed M/Z',
 'Quality', 'Original Modifications', 'User Modifications', 'PPM Tolerance',
 'Text Annotation Threshold', 'Max Neutral Losses', 'Hyperscore',
 'Spectrum File', 'Scan', 'Fragmented Bonds', 'Annotated TIC',
 'XTandem', 'Longest Consecutive', 'Complementary Pairs',
 'Morpheus Score', 'Raw Data Path', 'Selected Ion Types',
 'Selected Neutral Loss Types', 'Selected Internal Ion Types',
 'Selected Custom Ions', 'Selected Diagnostic Ions']
```

#### `_export_svg_and_excel(self, folder_path, main_window)`
- **Inputs:**
  - `folder_path`: Output directory
  - `main_window`: Reference to main app
- **Outputs:** `(svg_count, excel_filename)` tuple
- **Files Created:**
  - SVG files: Format `{idx:03d}_{peptide}-{spectrum_file}-{scan}.svg`
  - Excel: `spectrum_tracker_export_data.xlsx` with Export_List and Metadata sheets

#### `_export_pdf_and_excel(self, folder_path, main_window)`
- **Inputs:** Same as SVG export
- **Outputs:** `(pdf_filename, excel_filename)` tuple
- **Features:**
  - High-quality 300 DPI PNG images embedded in PDF
  - Individual spectrum pages with metadata
  - Export summary in header

#### `_export_excel_only(self, folder_path)`
- **Inputs:** `folder_path`
- **Outputs:** `excel_filename`
- **Data:** Export_List and Metadata sheets

#### `_generate_fragmentation_for_row(self, main_window, peptide, modifications, charge, ...)`
- **Inputs:**
  - Peptide sequence, modifications list
  - Charge, PPM tolerance, max neutral losses
  - m/z and intensity arrays
  - Row data containing stored ion selections
- **Outputs:** `(matched_data, theoretical_data)` DataFrames or `(None, None)`
- **Process:** Regenerates fragmentation using stored ion type selections

#### `_parse_stored_list(self, stored_string)`
- **Inputs:** String representation of list (e.g., "['b', 'y']")
- **Outputs:** Python list or empty list on failure
- **Method:** Uses `ast.literal_eval()` for safe parsing

#### `_create_modal_progress_dialog(self, title, total_items)`
- **Inputs:** Dialog title, total item count
- **Outputs:** QProgressDialog instance
- **Behavior:** Modal dialog (locks app), styled with custom colors

#### `_update_progress_percentage(self, progress, current_item, total_items, status="")`
- **Inputs:** Progress dialog, current/total counts, status text
- **Outputs:** None (updates dialog)
- **Calculation:** `percentage = (current / total) * 100`

#### Signals:
- `spectrumAccepted(dict)`: User accepted current spectrum
- `spectrumDeclined(dict)`: User declined current spectrum
- `spectrumAddedToExport(dict)`: Spectrum added to export list

---

## 6. relocalisation_widget.py

### RelocalisationWidget

**Purpose:** Test modification positions across allowed amino acids and rank by scoring metrics

#### `__init__(self, main_app, parent=None)`
- **Inputs:**
  - `main_app`: Reference to main application
  - `parent`: Parent widget

#### `refresh_modifications(self)`
- **Inputs:** None
- **Outputs:** None (populates mod_combo)
- **Source:** `main_app.current_interactive_mods` (list of (mass, position) tuples)
- **Display Format:** "ModName @ AA{position}" or "{mass:.4f} @ AA{position}"

#### `run_relocalisation(self)`
- **Inputs:** None (reads from UI: combo selection, allowed amino acids)
- **Outputs:** Opens RelocalisationResultsDialog
- **Process:**
  1. Parse allowed amino acids (comma-separated)
  2. Find all candidate positions in peptide
  3. For each candidate: generate fragmentation with mod at that position
  4. Score each candidate using enabled metrics
  5. Display results sorted by hyperscore (highest first)

#### `_gather_fragmentation_params(self, peptide)`
- **Inputs:** `peptide` (sequence string)
- **Outputs:** Dict with fragmentation parameters or None
- **Contents:**
  ```python
  {
    "max_charge": int,
    "ppm_tolerance": float,
    "max_neutral_losses": int,
    "user_mz_values": list of (mz, intensity) tuples,
    "selected_ions": list of ion type strings,
    "selected_internal_ions": list,
    "diagnostic_ions": list of (name, mass, color) tuples,
    "custom_ion_series_list": list of dicts,
    "ion_types": dict (from annotation_tab_manager)
  }
  ```

#### `_compute_scores(self, matched_data, ion_types, pep_len, scoring_flags)`
- **Inputs:**
  - `matched_data`: Fragmentation result DataFrame
  - `ion_types`: Selected ion types
  - `pep_len`: Peptide length
  - `scoring_flags`: Dict of enabled scoring methods
- **Outputs:** Score dict:
  ```python
  {
    "hyperscore": float,
    "consecutive": int,
    "complementary": "pairs/possible",
    "morpheus": float
  }
  ```

### RelocalisationResultsDialog

**Purpose:** Display relocalisation results in a table

#### `__init__(self, rows, peptide, mod_label, parent=None)`
- **Inputs:**
  - `rows`: List of (position, aa, scores, is_original) tuples
  - `peptide`: Sequence string
  - `mod_label`: Modification name or mass
- **Outputs:** Dialog instance

#### Table Columns:
Position | AA | Hyperscore | Consecutive | Complementary | Morpheus

- **Highlighting:** Best hyperscore row highlighted in green
- **Marker:** Original position marked with " (original)" suffix

---

## 7. psm_summary_widget.py

### PSMSummaryWidget

**Purpose:** Display PSM summary (aggregated) and details (individual) views with filtering and selection

#### `__init__(self, parent=None)`
- **Inputs:** `parent` widget
- **Outputs:** PSMSummaryWidget instance
- **Initialization:** Creates summary/details DataFrames, timers, filter state

#### `setData(self, df: pd.DataFrame)`
- **Inputs:** Combined PSM DataFrame (all columns)
- **Outputs:** None
- **Process:**
  1. Stores raw DataFrame
  2. Builds summary (unique peptide-protein pairs)
  3. Displays summary table
  4. Populates filter dropdowns with all columns

#### `_make_summary_df(self)`
- **Inputs:** None (uses self.raw_df)
- **Outputs:** None (sets self.summary_df, self.summary_df_unfiltered)
- **Grouping:** By (Peptide, Protein)
- **Aggregations:**
  - Modifications: Unique set (semicolon-separated)
  - Score: Average of Hyperscore
  - Count: Number of PSMs
  - Position info: Protein Start/End, Peptide Length, Prev/Next AA

#### `show_details_for_row(self, row, col)`
- **Inputs:** Summary table row and column indices
- **Outputs:** None (switches to details view, filters data)
- **Process:**
  1. Extracts Peptide and Protein from summary row
  2. Filters raw_df for matching rows
  3. Populates details table
  4. Shows details filter widget, hides summary filters

#### `_show_details_table(self)`
- **Purpose:** Populate details table with filtered data
- **Column Order:**
  1. Default columns (Modified Peptide, Charge, Hyperscore, Observed M/Z, etc.)
  2. Additional visible columns (user-selected)
- **Numeric Columns:** Charge, Hyperscore, Observed M/Z, Peptide Length, etc.
  - Set as numeric `DisplayRole` for proper sorting

#### `_on_details_table_singleclick(self, row, col)`
- **Inputs:** Details table row and column indices
- **Outputs:** None
- **Emissions:** `peptideSelected(peptide_str, parsed_mods, charge, row_data)` signal
- **Side Effect:** Attempts to load spectral data from cache

#### `get_spectral_data_from_cache(self, row_data)`
- **Inputs:** Row data dictionary
- **Outputs:** Emits `rawDataExtracted(mz_array, intensity_array)` signal
- **Cache Key:** `{spectrum_file_path}_{scan_str}`
- **Fallback:** Offers to extract single scan if not in cache

#### `extract_single_scan_fallback(self, raw_path, scan_str)`
- **Inputs:** Raw file path and scan number
- **Outputs:** Emits `rawDataExtracted()` signal, updates cache
- **Process:** Uses `spectral_extraction()` to extract missing scan

#### Filtering Methods:

`add_summary_filter()` / `add_details_filter()`
- **Inputs:** None (reads from combo and input fields)
- **Outputs:** None (adds to active_filters dict, applies filter)

`apply_summary_filter()` / `apply_details_filter()`
- **Logic:**
  - Numeric columns: >= comparison
  - Text columns: case-insensitive substring match
  - Applies all active filters (AND logic)

`clear_summary_filter()` / `clear_details_filter()`
- **Inputs:** None
- **Outputs:** None (clears active filters, resets display)

#### Header Context Menu:

`_show_summary_header_menu(pos)` / `_show_details_header_menu(pos)`
- **Functionality:** Right-click on column header to show/hide columns
- **Details menu:** Shows both default and additional columns
  - Default columns: Fixed list
  - Additional columns: Any other columns from raw_df (sorted)

#### Signals:
- `peptideSelected(str, list, int, dict)`: (Peptide, Mods, Charge, RowData)
- `rawDataExtracted(mz_array, intensity_array)`: Spectral data ready

#### Key Attributes:
| Attribute | Type | Purpose |
|-----------|------|---------|
| `raw_df` | DataFrame | All PSM data (unfiltered) |
| `summary_df` | DataFrame | Current summary (filtered) |
| `summary_df_unfiltered` | DataFrame | Original summary (backup) |
| `original_details_df` | DataFrame | Details for selected peptide |
| `current_details_df` | DataFrame | Details with active filters |
| `active_summary_filters` | dict | Current summary filters |
| `active_details_filters` | dict | Current details filters |
| `visible_details_columns` | set | Columns to display in details |

### DraggablePSMSummaryWidget

**Purpose:** Extended PSMSummaryWidget with drag-and-drop support from details table

#### `_start_details_drag(self, event)`
- **Inputs:** Mouse event
- **Outputs:** Initiates QDrag operation
- **MIME Data:**
  - Text: "Peptide (z=charge, score=score)"
  - Application data: JSON-encoded peptide data

#### `_extract_peptide_data_from_row(self, row)`
- **Inputs:** Details table row index
- **Outputs:** Peptide data dictionary:
  ```python
  {
    'Peptide': str,
    'Modified Peptide': str,
    'Charge': int,
    'Assigned Modifications': str,
    'Parsed Modifications': list,
    'Hyperscore': float,
    'Observed M/Z': float,
    'Spectrum file': str,
    'index': str,
    'spectrum_file_path': str,
    'row_data': dict,
    # Legacy aliases
    'peptide': str,
    'charge': int,
    'parsed_modifications': list
  }
  ```

---

## Data Flow Diagram

```
User Input (Table)
    ↓
TableEditorDialog ← ExcelLikeTableWidget + Delegates
    ├─ ColorDelegate (color selection)
    ├─ BaseIonComboDelegate (ion type dropdown)
    └─ RestrictionDelegate (restriction dialog)
    ↓
CSV File (saved)

PSMSummaryWidget
    ├─ Summary View (aggregated)
    │   └─ Filter by Peptide, Protein, Modifications, etc.
    └─ Details View (individual PSMs)
        ├─ Click row → Emit peptideSelected signal
        ├─ Load spectral data from cache
        └─ Drag to export

SpectrumTrackerWidget
    ├─ Accept/Decline spectrum
    │   └─ Add to export list
    └─ Export Options:
        ├─ Excel only
        ├─ PDF + Excel (high-quality images)
        └─ SVG + Excel (individual files)

RelocalisationWidget
    ├─ Select modification
    ├─ Specify allowed amino acids
    ├─ Test all positions
    └─ Display results ranked by score
```

---

## Key Data Structures

### Spectrum Data Dictionary
```python
{
    'Peptide': str,
    'Modified Peptide': str,
    'Charge': int,
    'Observed M/Z': float,
    'Hyperscore': float,
    'Spectrum file': str,
    'spectrum_file_path': str,
    'index': int,
    'Parsed Modifications': list[(mass, position)],
    # ... other columns
}
```

### Settings Data Dictionary
```python
{
    'user_modifications': list,
    'ppm_tolerance': float,
    'text_annotation_threshold': float,
    'max_neutral_losses': int,
    'selected_basic_ions': list[str],
    'selected_neutral_loss_ions': list[str],
    'selected_internal_ions': list[str],
    'selected_custom_ions_data': list[dict],
    'selected_diagnostic_ions_data': list[dict],
    'fragmented_bonds': str,
    'annotated_tic': str
}
```

### Fragmentation Result
```python
(matched_data: DataFrame, theoretical_data: DataFrame)
# matched_data columns: m/z, intensity, theoretical_mz, ppm_error, ion_type, matched, etc.
# theoretical_data columns: m/z, intensity, ion_type, charge, etc.
```

---

## Common Patterns

### Excel Table Operations
```python
# Copy selection
ctrl+c → _copy_selection() → clipboard.setText(tab-separated)

# Paste
ctrl+v → _paste_clipboard() → parse rows/cols → fill cells

# Fill down
ctrl+d → _fill_down() → copy first row to all rows below

# Clear
delete/backspace → _clear_selection() → clear editable cells
```

### Table Editor Data Flow
```python
1. User edits table (add row, modify cell, etc.)
2. itemChanged signal → _on_item_changed()
3. Debounce timer (500ms) → data_changed.emit()
4. Parent widget responds to signal

1. User clicks Save
2. _get_table_data() → extract and validate
3. save_changes() → CSV write + backup
4. Emits data_changed signal
```

### Spectrum Tracking Export
```python
1. User accepts/declines spectrum
2. _add_to_export_list_with_quality() → gather all data → append to export_list_df
3. User clicks Export
4. Select format (Excel/PDF/SVG)
5. For each row:
   a. Regenerate fragmentation with stored ion types
   b. Export image (PNG/SVG)
   c. Add to document/file
6. Write Excel with metadata
7. Show success message
```

---

## Performance Considerations

### PSMSummaryWidget
- **Debounce Timers:** 300ms filter delay to avoid excessive re-filtering
- **Column-based Numeric Handling:** Uses `DisplayRole` for proper sorting without string conversion
- **Visibility Tracking:** Separate sets for hidden columns to avoid full rebuild

### SpectrumTrackerWidget
- **Modal Progress Dialog:** Locks application during export to prevent conflicts
- **Event Loop Processing:** `QApplication.processEvents()` to maintain UI responsiveness
- **Render Waiting:** Custom delay logic to ensure proper image rendering before export

### TableEditorWidget
- **Debounce Signal:** 500ms timer prevents excessive parent updates

---

## Error Handling

| Scenario | Handler | Outcome |
|----------|---------|---------|
| Invalid CSV import | Column validation check | Warning dialog, import cancelled |
| Duplicate names | compare with existing | Warning dialog, save blocked |
| Reserved characters | check *, ~, ^ | Warning dialog, save blocked |
| Fragmentation failure | try/except + fallback | Returns None, user notified |
| Missing cache | fallback extraction | Offers to extract single scan |
| Export file conflicts | overwrite | No confirmation (overwrites) |

---

## Testing Notes

### Key Test Cases
1. **Excel Table:** Copy/paste multi-cell, fill down, readonly columns
2. **Color Picker:** Hex code validation, persistence
3. **Table Editor:** Add/delete/duplicate rows, import/export CSV, save validation
4. **Spectrum Tracker:** Accept/decline, export formats (Excel/PDF/SVG)
5. **Relocalisation:** Test positions, score calculations, results display
6. **PSM Summary:** Filtering (summary and details), column visibility, drag drag

