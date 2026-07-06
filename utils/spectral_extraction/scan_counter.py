"""
Scan counter module for counting MS1 and MS2 scans in raw mass spectrometry files.
Supports Thermo .raw files (via RawFileReader) and .mzML files (via pymzml).
"""

import logging
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pymzml

from .core import RawFileManager, get_ms_order_type

logger = logging.getLogger(__name__)


def _is_raw_file(file_path):
    """Return True for Thermo RAW files."""
    return Path(file_path).suffix.lower() == ".raw"


def _process_raw_files_sequentially():
    """Avoid pythonnet/Mono work in worker threads on Unix-like platforms."""
    return sys.platform != "win32"


def _count_raw_scans(file_path):
    """Count MS1/MS2 scans in a Thermo .raw file by reading scan event metadata."""
    try:
        ms_order_type = get_ms_order_type()
    except Exception as exc:
        logger.warning(
            "Thermo RawFileReader not available; cannot count scans in .raw files: %s",
            exc,
        )
        return {"ms1": 0, "ms2": 0, "total": 0}

    ms1_count = 0
    ms2_count = 0

    with RawFileManager(file_path) as raw_file:
        if not raw_file.IsOpen:
            logger.error(f"Could not open raw file: {file_path}")
            return {"ms1": 0, "ms2": 0, "total": 0}

        first_scan = raw_file.RunHeaderEx.FirstSpectrum
        last_scan = raw_file.RunHeaderEx.LastSpectrum

        for scan_num in range(first_scan, last_scan + 1):
            try:
                scan_event = raw_file.GetScanEventForScanNumber(scan_num)
                ms_order = scan_event.MSOrder
                if ms_order == ms_order_type.Ms:
                    ms1_count += 1
                elif ms_order == ms_order_type.Ms2:
                    ms2_count += 1
            except Exception:
                continue

    total = last_scan - first_scan + 1
    return {"ms1": ms1_count, "ms2": ms2_count, "total": total}


def _count_mzml_scans(file_path):
    """Count MS1/MS2 scans in an mzML file."""
    ms1_count = 0
    ms2_count = 0
    total = 0

    try:
        run = pymzml.run.Reader(file_path, build_index_from_scratch=True)
        for spec in run:
            total += 1
            ms_level = spec.ms_level
            if ms_level == 1:
                ms1_count += 1
            elif ms_level == 2:
                ms2_count += 1
    except Exception as e:
        logger.error(f"Error counting scans in mzML file {file_path}: {e}")
        return {"ms1": 0, "ms2": 0, "total": 0}

    return {"ms1": ms1_count, "ms2": ms2_count, "total": total}


def count_scans(file_path):
    """Count MS1/MS2 scans in a raw or mzML file.

    Returns:
        dict with keys 'ms1', 'ms2', 'total'.
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".mzml":
        return _count_mzml_scans(file_path)
    return _count_raw_scans(file_path)


def count_scans_batch(file_paths, max_workers=4):
    """Count scans for multiple files in parallel.

    Returns:
        dict mapping file_path -> {'ms1': N, 'ms2': M, 'total': T}
    """
    results = {}

    if _process_raw_files_sequentially():
        raw_paths = [fp for fp in file_paths if _is_raw_file(fp)]
        for fp in raw_paths:
            try:
                results[fp] = count_scans(fp)
            except Exception as e:
                logger.error(f"Error counting scans for {fp}: {e}")
                results[fp] = {"ms1": 0, "ms2": 0, "total": 0}

        file_paths = [fp for fp in file_paths if not _is_raw_file(fp)]
        if not file_paths:
            return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(count_scans, fp): fp for fp in file_paths}
        for future in as_completed(future_to_path):
            fp = future_to_path[future]
            try:
                results[fp] = future.result()
            except Exception as e:
                logger.error(f"Error counting scans for {fp}: {e}")
                results[fp] = {"ms1": 0, "ms2": 0, "total": 0}

    return results
