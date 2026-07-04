import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
from pathlib import Path
from collections import defaultdict
import pymzml
import logging

from .core import RawFileManager, create_error_result, build_success_result

logger = logging.getLogger(__name__)


def _resolve_worker_count(total_files, max_workers):
    """Resolve an efficient thread count for file-level parallel extraction."""
    if total_files <= 0:
        return 1

    if max_workers is None or max_workers <= 0:
        cpu_count = os.cpu_count() or 1
        # I/O-bound workloads usually benefit from more threads than CPU cores.
        auto_workers = min(32, max(2, cpu_count * 2))
        return min(total_files, auto_workers)

    return min(total_files, max_workers)


def _extract_mzml_scans_common(file_path, scan_numbers, lightweight=False):
    """
    Extract multiple scans from a .mzML file using pymzml.
    Iterates the file once to collect all requested scans efficiently.

    Args:
        file_path: Path to mzML file
        scan_numbers: List of scan numbers to extract
        lightweight: If True, returns only results; if False, returns (results, peak_data)
    """
    results = []
    peak_data = [] if not lightweight else None
    scan_set = set(scan_numbers)
    found = {}

    try:
        run = pymzml.run.Reader(file_path, build_index_from_scratch=True)
        requested_count = len(scan_set)
        for spec in run:
            if spec.ID in scan_set:
                mz_array = spec.mz
                intensity_array = spec.i
                if mz_array is not None and len(mz_array) > 0:
                    found[spec.ID] = {
                        "mz": mz_array,
                        "intensity": intensity_array,
                        "header": f"mzML scan={spec.ID} ms_level={spec.ms_level}",
                        "status": "success",
                    }
                else:
                    found[spec.ID] = {
                        "mz": None,
                        "intensity": None,
                        "header": None,
                        "status": "error - no centroid data",
                    }
                if len(found) == requested_count:
                    break
    except Exception as e:
        error_results = [
            create_error_result(
                scan_num, file_path, f"error - file access failed: {str(e)}"
            )
            for scan_num in scan_numbers
        ]
        return error_results if lightweight else (error_results, peak_data)

    for scan_num in scan_numbers:
        if scan_num in found:
            data = found[scan_num]
            if data["status"] == "success":
                result = build_success_result(
                    scan_num,
                    file_path,
                    data["mz"],
                    data["intensity"],
                    data["header"],
                    lightweight,
                )
                results.append(result)
                if not lightweight:
                    mz_arr = np.array(data["mz"], dtype=np.float64)
                    int_arr = np.array(data["intensity"], dtype=np.float64)
                    for mz, intensity in zip(mz_arr, int_arr):
                        peak_data.append((scan_num, mz, intensity, file_path))
            else:
                results.append(create_error_result(scan_num, file_path, data["status"]))
        else:
            results.append(
                create_error_result(
                    scan_num, file_path, f"error - scan {scan_num} not found in mzML"
                )
            )

    return results if lightweight else (results, peak_data)


def _extract_raw_scans_common(file_path, scan_numbers, lightweight=False):
    """
    Common extraction logic for .raw files.

    Args:
        file_path: Path to .raw file
        scan_numbers: List of scan numbers to extract
        lightweight: If True, returns only results; if False, returns (results, peak_data)
    """
    results = []
    peak_data = [] if not lightweight else None

    try:
        with RawFileManager(file_path) as raw_file:
            if not raw_file.IsOpen:
                error_results = [
                    create_error_result(
                        scan_num, file_path, "error - could not open file"
                    )
                    for scan_num in scan_numbers
                ]
                return error_results if lightweight else (error_results, peak_data)

            # Get scan range once
            first_scan = raw_file.RunHeaderEx.FirstSpectrum
            last_scan = raw_file.RunHeaderEx.LastSpectrum

            # Avoid repeated native calls when the same scan is requested multiple times.
            # Sort ascending so reads follow the file's sequential scan order (reduces seeks).
            requested_scans = sorted(dict.fromkeys(scan_numbers))
            found = {}

            count = 0
            for scan_num in requested_scans:
                try:
                    if scan_num < first_scan or scan_num > last_scan:
                        found[scan_num] = {
                            "status": f"error - scan out of range ({first_scan}-{last_scan})"
                        }
                        continue

                    # Get the scan data and header
                    scan = raw_file.GetCentroidStream(scan_num, False)
                    header = raw_file.GetScanEventForScanNumber(scan_num)

                    if scan.Masses is not None and scan.Intensities is not None:
                        header_info = str(header) if header else None
                        found[scan_num] = {
                            "status": "success",
                            "mz": list(scan.Masses),
                            "intensity": list(scan.Intensities),
                            "header": header_info,
                        }
                    else:
                        found[scan_num] = {"status": "error - no centroid data"}

                except Exception as e:
                    found[scan_num] = {"status": f"error - {str(e)}"}

                count += 1
                if count % 1000 == 0:
                    logger.debug(
                        f"[{Path(file_path).name}] {count}/{len(requested_scans)} scans extracted"
                    )

            for scan_num in scan_numbers:
                scan_data = found[scan_num]
                if scan_data["status"] == "success":
                    result = build_success_result(
                        scan_num,
                        file_path,
                        scan_data["mz"],
                        scan_data["intensity"],
                        scan_data["header"],
                        lightweight,
                    )
                    results.append(result)
                    if not lightweight:
                        mz_array = np.array(scan_data["mz"], dtype=np.float64)
                        intensity_array = np.array(scan_data["intensity"], dtype=np.float64)
                        for mz, intensity in zip(mz_array, intensity_array):
                            peak_data.append((scan_num, mz, intensity, file_path))
                else:
                    results.append(
                        create_error_result(scan_num, file_path, scan_data["status"])
                    )

    except Exception as e:
        error_results = [
            create_error_result(
                scan_num, file_path, f"error - file access failed: {str(e)}"
            )
            for scan_num in scan_numbers
        ]
        return error_results if lightweight else (error_results, peak_data)

    return results if lightweight else (results, peak_data)


def extract_multiple_scans_from_file(file_path, scan_numbers):
    """
    Extract multiple scans from a single file more efficiently.
    Opens the file once and extracts all requested scans.
    Returns (results, peak_data) with individual peak data for structured array creation.
    """
    if Path(file_path).suffix.lower() == ".mzml":
        return _extract_mzml_scans_common(file_path, scan_numbers, lightweight=False)

    return _extract_raw_scans_common(file_path, scan_numbers, lightweight=False)


def extract_multiple_scans_from_file_lightweight(file_path, scan_numbers):
    """
    Extract multiple scans from a single file with optimized data structure.
    Returns only results without individual peak tracking (lightweight).
    """
    if Path(file_path).suffix.lower() == ".mzml":
        return _extract_mzml_scans_common(file_path, scan_numbers, lightweight=True)

    return _extract_raw_scans_common(file_path, scan_numbers, lightweight=True)


def ultra_fast_extract_lightweight(input_file, max_workers=None):
    """
    Lightweight extraction that skips structured array creation and optimizes merging.
    Returns only the results DataFrame needed for the GUI.
    """
    logger.debug(f"Loading input file: {input_file}")
    df = pd.read_csv(input_file, sep="\t")

    # Group all scans by file
    file_scan_map = defaultdict(list)
    if not df.empty:
        grouped = df.groupby("file_path", sort=False)["index"].agg(list)
        for file_path, scan_numbers in grouped.items():
            file_scan_map[file_path] = scan_numbers

    logger.debug(f"Processing {len(df)} scans from {len(file_scan_map)} files")
    if not file_scan_map:
        return pd.DataFrame(columns=["index", "scan_number", "file_path", "mz", "intensity", "header", "status", "num_peaks"])

    start_time = time.time()
    worker_count = _resolve_worker_count(len(file_scan_map), max_workers)
    logger.debug(f"Using {worker_count} worker threads for extraction")

    # Use ThreadPoolExecutor with file-level parallelization
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_file = {
            executor.submit(
                extract_multiple_scans_from_file_lightweight, file_path, scan_numbers
            ): (file_path, scan_numbers)
            for file_path, scan_numbers in file_scan_map.items()
        }

        all_results = []

        for i, future in enumerate(as_completed(future_to_file)):
            file_path, scan_numbers = future_to_file[future]
            try:
                results = future.result()
            except Exception as e:
                logger.error(f"Extraction failed for {file_path}: {e}")
                results = [
                    create_error_result(
                        scan_num, file_path, f"error - extraction worker failed: {str(e)}"
                    )
                    for scan_num in scan_numbers
                ]

            all_results.extend(results)

            elapsed = time.time() - start_time
            rate = len(all_results) / elapsed if elapsed > 0 else 0
            logger.debug(
                f"File {i+1}/{len(future_to_file)} done - {len(all_results)} scans - {rate:.1f} scans/sec"
            )

    # Create results DataFrame
    results_df = pd.DataFrame(all_results)
    results_df = results_df.sort_values(["file_path", "index"]).reset_index(drop=True)

    total_time = time.time() - start_time
    success_count = len(results_df[results_df["status"] == "success"])

    logger.debug("\n=== LIGHTWEIGHT EXTRACTION SUMMARY ===")
    logger.debug(
        f"Success: {success_count}/{len(results_df)} scans in {total_time:.1f}s"
    )
    logger.debug(f"Rate: {len(results_df)/total_time:.1f} scans/second")

    return results_df
