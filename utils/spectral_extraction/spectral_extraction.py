import logging

import numpy as np

from .batch_spectral_extraction import extract_multiple_scans_from_file_lightweight

logger = logging.getLogger(__name__)


def spectral_extraction(file_path: str, scan_number_str: str):
    """
    Opens the given mass spectrometry data file (.raw or .mzML),
    retrieves mass list for the specified scan number, and
    returns the (m/z, intensity) tuple.

    Args:
        file_path: Path to .raw or .mzML file
        scan_number_str: Scan number as string

    Returns:
        Tuple of (m/z_array, intensity_array), or None if extraction fails
    """
    try:
        scan_num = int(scan_number_str)
    except ValueError:
        logger.debug(f"Invalid scan number: {scan_number_str}")
        return None

    results = extract_multiple_scans_from_file_lightweight(file_path, [scan_num])

    if results and results[0]['status'] == 'success':
        return np.array(results[0]['mz']), np.array(results[0]['intensity'])

    if results:
        logger.debug(f"Extraction failed for scan {scan_num}: {results[0]['status']}")
    return None
