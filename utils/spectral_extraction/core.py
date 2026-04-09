"""
Core utilities for raw mass spectrometry data extraction.
Provides shared helpers used by both single-scan and batch extraction modules.
"""

import numpy as np
from pathlib import Path

# Import resource path helper for PyInstaller compatibility
from utils.resource_path import get_resource_path

# --- .NET / RawFileReader setup ---
import clr

dll_base_path = Path(get_resource_path("RawFileReader-main/RawFileReader-main/Libs/Net471"))

clr.AddReference(str(dll_base_path / "ThermoFisher.CommonCore.Data.dll"))
clr.AddReference(str(dll_base_path / "ThermoFisher.CommonCore.RawFileReader.dll"))
clr.AddReference(str(dll_base_path / "ThermoFisher.CommonCore.BackgroundSubtraction.dll"))
clr.AddReference(str(dll_base_path / "ThermoFisher.CommonCore.MassPrecisionEstimator.dll"))

from ThermoFisher.CommonCore.Data.Business import Device
from ThermoFisher.CommonCore.RawFileReader import RawFileReaderAdapter


class RawFileManager:
    """Context manager for Thermo .raw files via RawFileReaderAdapter."""

    def __init__(self, file_path):
        self.file_path = file_path
        self._raw_file = None

    def __enter__(self):
        self._raw_file = RawFileReaderAdapter.FileFactory(self.file_path)
        if self._raw_file.IsOpen:
            self._raw_file.SelectInstrument(Device.MS, 1)
        return self._raw_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._raw_file is not None:
            self._raw_file.Dispose()
        return False


def create_error_result(scan_num, file_path, status):
    """Build a standardised error-result dict for a failed scan extraction."""
    return {
        'index': scan_num,
        'scan_number': scan_num,
        'file_path': file_path,
        'mz': None,
        'intensity': None,
        'header': None,
        'status': status,
        'num_peaks': 0,
    }


def build_success_result(scan_num, file_path, mz, intensity, header, lightweight):
    """
    Build a standardised success-result dict.

    Args:
        lightweight: If True, stores mz/intensity as plain lists.
                     If False, converts to float64 numpy arrays stored as tuples.
    """
    if lightweight:
        mz_out = list(mz)
        int_out = list(intensity)
        num_peaks = len(mz_out)
    else:
        mz_arr = np.array(mz, dtype=np.float64)
        int_arr = np.array(intensity, dtype=np.float64)
        mz_out = tuple(mz_arr)
        int_out = tuple(int_arr)
        num_peaks = len(mz_arr)

    return {
        'index': scan_num,
        'scan_number': scan_num,
        'file_path': file_path,
        'mz': mz_out,
        'intensity': int_out,
        'header': header,
        'status': 'success',
        'num_peaks': num_peaks,
    }
