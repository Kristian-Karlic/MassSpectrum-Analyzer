"""
Core utilities for raw mass spectrometry data extraction.
Provides shared helpers used by both single-scan and batch extraction modules.
"""

import os
import sys
import logging
import shutil
import numpy as np
from pathlib import Path

# Import resource path helper for PyInstaller compatibility
from utils.resource_path import get_resource_path

logger = logging.getLogger(__name__)

_THERMO_INITIALIZED = False
_THERMO_INIT_ERROR = None
_Device = None
_RawFileReaderAdapter = None
_MSOrderType = None

_RAWFILEREADER_ASSEMBLIES = (
    "OpenMcdf.dll",
    "OpenMcdf.Extensions.dll",
    "ThermoFisher.CommonCore.Data.dll",
    "ThermoFisher.CommonCore.RawFileReader.dll",
    "ThermoFisher.CommonCore.BackgroundSubtraction.dll",
    "ThermoFisher.CommonCore.MassPrecisionEstimator.dll",
)


def _rawfilereader_candidate_dirs() -> list[tuple[str | None, Path]]:
    """Return (pythonnet runtime, assembly directory) candidates."""
    if sys.platform == "win32":
        candidates = (
            (None, "RawFileReader-main/RawFileReader-main/Libs/Net471"),
            (
                "coreclr",
                "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net8/Assemblies",
            ),
            ("coreclr", "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net5"),
        )
    else:
        configured_runtime = os.environ.get("PYTHONNET_RUNTIME")
        if configured_runtime == "mono":
            candidates = (
                ("mono", "RawFileReader-main/RawFileReader-main/Libs/Net471"),
                (
                    "coreclr",
                    "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net8/Assemblies",
                ),
                ("coreclr", "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net5"),
            )
        elif configured_runtime == "coreclr" or shutil.which("dotnet"):
            candidates = (
                (
                    "coreclr",
                    "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net8/Assemblies",
                ),
                ("coreclr", "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net5"),
                ("mono", "RawFileReader-main/RawFileReader-main/Libs/Net471"),
            )
        elif shutil.which("mono"):
            candidates = (
                ("mono", "RawFileReader-main/RawFileReader-main/Libs/Net471"),
                (
                    "coreclr",
                    "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net8/Assemblies",
                ),
                ("coreclr", "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net5"),
            )
        else:
            candidates = (
                (
                    "coreclr",
                    "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net8/Assemblies",
                ),
                ("coreclr", "RawFileReader-main/RawFileReader-main/Libs/NetCore/Net5"),
                ("mono", "RawFileReader-main/RawFileReader-main/Libs/Net471"),
            )

    return [
        (runtime, Path(get_resource_path(relative_dir)))
        for runtime, relative_dir in candidates
    ]


def _select_rawfilereader_runtime_and_dir() -> tuple[str | None, Path]:
    """Resolve the best available pythonnet runtime and assembly directory."""
    for runtime, candidate in _rawfilereader_candidate_dirs():
        if (candidate / "ThermoFisher.CommonCore.RawFileReader.dll").exists():
            return runtime, candidate

    searched = ", ".join(str(path) for _, path in _rawfilereader_candidate_dirs())
    raise RuntimeError(
        f"Thermo RawFileReader assemblies were not found. Searched: {searched}"
    )


def get_rawfilereader_dll_dir() -> Path:
    """Resolve the best available RawFileReader assembly directory."""
    _, dll_dir = _select_rawfilereader_runtime_and_dir()
    return dll_dir


def initialize_raw_file_reader():
    """Load Thermo RawFileReader assemblies on demand.

    mzML workflows do not need pythonnet or Thermo assemblies, so this setup is
    intentionally lazy. On Linux and macOS, pythonnet uses the configured
    runtime, CoreCLR when dotnet is available, or Mono with the bundled Net471
    assemblies as a fallback.
    """
    global _THERMO_INITIALIZED, _THERMO_INIT_ERROR
    global _Device, _RawFileReaderAdapter, _MSOrderType

    if _THERMO_INITIALIZED:
        return _Device, _RawFileReaderAdapter, _MSOrderType

    if _THERMO_INIT_ERROR is not None:
        raise RuntimeError(
            f"Thermo RawFileReader is unavailable: {_THERMO_INIT_ERROR}"
        ) from _THERMO_INIT_ERROR

    try:
        runtime, dll_dir = _select_rawfilereader_runtime_and_dir()

        if runtime:
            os.environ.setdefault("PYTHONNET_RUNTIME", runtime)

        if str(dll_dir) not in sys.path:
            sys.path.insert(0, str(dll_dir))

        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dll_dir))

        import clr

        for assembly_name in _RAWFILEREADER_ASSEMBLIES:
            assembly_path = dll_dir / assembly_name
            if assembly_path.exists():
                clr.AddReference(str(assembly_path))

        from ThermoFisher.CommonCore.Data.Business import Device
        from ThermoFisher.CommonCore.Data.FilterEnums import MSOrderType
        from ThermoFisher.CommonCore.RawFileReader import RawFileReaderAdapter

        _Device = Device
        _RawFileReaderAdapter = RawFileReaderAdapter
        _MSOrderType = MSOrderType
        _THERMO_INITIALIZED = True
        logger.debug("Loaded Thermo RawFileReader assemblies from %s", dll_dir)
        return _Device, _RawFileReaderAdapter, _MSOrderType
    except Exception as exc:
        _THERMO_INIT_ERROR = exc
        raise RuntimeError(f"Thermo RawFileReader is unavailable: {exc}") from exc


def get_ms_order_type():
    """Return Thermo MSOrderType enum, loading RawFileReader if needed."""
    _, _, ms_order_type = initialize_raw_file_reader()
    return ms_order_type


class RawFileManager:
    """Context manager for Thermo .raw files via RawFileReaderAdapter."""

    def __init__(self, file_path):
        self.file_path = file_path
        self._raw_file = None

    def __enter__(self):
        device, raw_file_reader_adapter, _ = initialize_raw_file_reader()
        self._raw_file = raw_file_reader_adapter.FileFactory(self.file_path)
        if self._raw_file.IsOpen:
            self._raw_file.SelectInstrument(device.MS, 1)
        return self._raw_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._raw_file is not None:
            self._raw_file.Dispose()
        return False


def create_error_result(scan_num, file_path, status):
    """Build a standardised error-result dict for a failed scan extraction."""
    return {
        "index": scan_num,
        "scan_number": scan_num,
        "file_path": file_path,
        "mz": None,
        "intensity": None,
        "header": None,
        "status": status,
        "num_peaks": 0,
    }


def build_success_result(scan_num, file_path, mz, intensity, header, lightweight):
    """
    Build a standardised success-result dict.

    Args:
        lightweight: If True, stores mz/intensity as plain lists.
                     If False, converts to float64 numpy arrays stored as tuples.
    """
    if lightweight:
        mz_out = np.asarray(mz, dtype=np.float64)
        int_out = np.asarray(intensity, dtype=np.float64)
        num_peaks = len(mz_out)
    else:
        mz_arr = np.array(mz, dtype=np.float64)
        int_arr = np.array(intensity, dtype=np.float64)
        mz_out = tuple(mz_arr)
        int_out = tuple(int_arr)
        num_peaks = len(mz_arr)

    return {
        "index": scan_num,
        "scan_number": scan_num,
        "file_path": file_path,
        "mz": mz_out,
        "intensity": int_out,
        "header": header,
        "status": "success",
        "num_peaks": num_peaks,
    }
