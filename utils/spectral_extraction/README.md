# Spectral Extraction Module

Utilities for extracting mass spectrometry data from `.raw` (Thermo) and `.mzML` format files. Provides single-scan extraction, batch extraction, and high-performance parallel extraction with multiple processing modes.

## Overview

The module is composed of:
- **`spectral_extraction.py`** — Single-scan extraction wrapper
- **`batch_spectral_extraction.py`** — Batch and parallel extraction functions
- **`core.py`** — Shared utilities (file managers, result builders)
- **`__init__.py`** — Public API exports

Supported file formats:
- `.raw` — Thermo Fisher RAW files (via RawFileReader DLLs)
- `.mzml` — mzML XML files (via pymzml)

---

## Public API Functions

### `spectral_extraction(file_path: str, scan_number_str: str)`

Extract a single scan from a mass spectrometry file.

**Inputs:**
- `file_path` (str): Path to `.raw` or `.mzML` file
- `scan_number_str` (str): Scan number as a string (will be converted to int)

**Returns:**
- `tuple[np.ndarray, np.ndarray]` — `(mz_array, intensity_array)` on success
- `None` — if extraction fails (invalid scan number, file not found, etc.)

**Example:**
```python
from utils.spectral_extraction import spectral_extraction

mz, intensity = spectral_extraction("data.raw", "1234")
if mz is not None:
    print(f"Extracted {len(mz)} peaks")
```

---

### `extract_multiple_scans_from_file(file_path: str, scan_numbers: list)`

Extract multiple scans from a single file with full peak-level data tracking.

**Inputs:**
- `file_path` (str): Path to `.raw` or `.mzML` file
- `scan_numbers` (list[int]): List of scan numbers to extract

**Returns:**
- `tuple[list, list]` — `(results, peak_data)`
  - `results` (list[dict]): List of scan result dicts, each with keys:
    - `'index'` (int): Scan number
    - `'scan_number'` (int): Scan number
    - `'file_path'` (str): File path
    - `'mz'` (tuple[float] or None): m/z values as tuple of float64
    - `'intensity'` (tuple[float] or None): Intensity values as tuple of float64
    - `'header'` (str or None): Scan header/metadata info
    - `'status'` (str): `'success'` or error message (e.g., `'error - no centroid data'`)
    - `'num_peaks'` (int): Number of peaks found
  - `peak_data` (list[tuple]): Individual peak records for structured array creation, each tuple: `(scan_num, mz, intensity, file_path)`

**Use when:** You need detailed peak-level data for downstream analysis or need to build structured arrays.

---

### `extract_multiple_scans_from_file_lightweight(file_path: str, scan_numbers: list)`

Extract multiple scans from a single file with reduced memory overhead (no individual peak tracking).

**Inputs:**
- `file_path` (str): Path to `.raw` or `.mzML` file
- `scan_numbers` (list[int]): List of scan numbers to extract

**Returns:**
- `list[dict]` — List of scan result dicts (same keys as above, but `'mz'` and `'intensity'` are stored as plain lists instead of tuples)

**Use when:** You need fast extraction for GUI display or don't need peak-level data tracking. Slightly faster and lower memory than full mode.

---

### `ultra_fast_extract_lightweight(input_file: str, max_workers: int = 6)`

Parallel extraction of scans from multiple files using ThreadPoolExecutor.

**Inputs:**
- `input_file` (str): Path to tab-separated `.tsv` or `.txt` file with columns:
  - `'file_path'` — Path to .raw or .mzML file
  - `'index'` — Scan number
  - Additional columns are preserved in output
- `max_workers` (int, optional): Number of threads for parallel file extraction (default: 6)

**Returns:**
- `pd.DataFrame` — Results DataFrame with all input columns plus:
  - `'mz'` (list): m/z values
  - `'intensity'` (list): Intensity values
  - `'header'` (str or None): Scan header
  - `'status'` (str): `'success'` or error message
  - `'num_peaks'` (int): Number of peaks
  - sorted by `'index'` and reset to clean index

**Use when:** Batch processing large numbers of scans from multiple files. Files are processed in parallel, one thread per file.

**Example:**
```python
from utils.spectral_extraction import ultra_fast_extract_lightweight

# Input file: scans_to_extract.tsv
# file_path    index    scan_id
# data1.raw    100      PSM_001
# data1.raw    200      PSM_002
# data2.raw    150      PSM_003

results_df = ultra_fast_extract_lightweight("scans_to_extract.tsv", max_workers=4)
print(results_df[['scan_id', 'status', 'num_peaks']])
```

---

## Core Utilities (Internal)

### `RawFileManager(file_path: str)`

Context manager for opening/closing Thermo `.raw` files safely.

**Usage:**
```python
from utils.spectral_extraction.core import RawFileManager

with RawFileManager("data.raw") as raw_file:
    if raw_file.IsOpen:
        scan = raw_file.GetCentroidStream(100, False)
        # Process scan
```

---

### `create_error_result(scan_num: int, file_path: str, status: str)`

Build a standardized error result dict.

**Returns:**
```python
{
    'index': scan_num,
    'scan_number': scan_num,
    'file_path': file_path,
    'mz': None,
    'intensity': None,
    'header': None,
    'status': status,  # e.g., 'error - file access failed: ...'
    'num_peaks': 0,
}
```

---

### `build_success_result(scan_num: int, file_path: str, mz, intensity: str, header: str, lightweight: bool)`

Build a standardized success result dict.

**Inputs:**
- `lightweight` (bool): If `True`, stores m/z and intensity as lists; if `False`, converts to float64 numpy arrays stored as tuples

**Returns:**
```python
{
    'index': scan_num,
    'scan_number': scan_num,
    'file_path': file_path,
    'mz': list or tuple of m/z values,
    'intensity': list or tuple of intensity values,
    'header': header,
    'status': 'success',
    'num_peaks': number of peaks,
}
```

---

## Error Handling

All functions return structured results with a `'status'` field:
- `'success'` — Extraction successful
- `'error - ...'` — Error message describing the failure (e.g., `'error - scan not found in mzML'`, `'error - file access failed'`)

Check the `'status'` field to determine success:
```python
results = extract_multiple_scans_from_file("data.raw", [100, 200])
for result in results:
    if result['status'] == 'success':
        print(f"Scan {result['index']}: {result['num_peaks']} peaks")
    else:
        print(f"Scan {result['index']}: {result['status']}")
```

---

## Logging

All functions use Python's `logging` module with debug-level messages:
- Extraction progress
- File access status
- Performance metrics (scans/second)

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Dependencies

- `numpy` — Array handling
- `pandas` — DataFrame operations (for batch functions)
- `pymzml` — mzML file parsing
- `pythonnet` (clr) — .NET interop for Thermo RawFileReader
- `concurrent.futures` — Thread pooling for parallel extraction
