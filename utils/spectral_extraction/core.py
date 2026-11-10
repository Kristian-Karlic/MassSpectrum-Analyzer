"""
Core utilities for raw mass spectrometry data extraction.
Provides shared helpers used by both single-scan and batch extraction modules.
"""

import os
import sys
import logging
import shutil
import threading
import numpy as np
from pathlib import Path

# Import resource path helper for PyInstaller compatibility
from utils.resource_path import get_resource_path

logger = logging.getLogger(__name__)

_THERMO_INIT_LOCK = threading.Lock()
_THERMO_INITIALIZED = False
_THERMO_INIT_ERROR = None
_Device = None
_RawFileReaderAdapter = None
_MSOrderType = None
_Scan = None

_RAWFILEREADER_ASSEMBLIES = (
    "OpenMcdf.dll",
    "OpenMcdf.Extensions.dll",
    "ThermoFisher.CommonCore.Data.dll",
    "ThermoFisher.CommonCore.RawFileReader.dll",
    "ThermoFisher.CommonCore.BackgroundSubtraction.dll",
    "ThermoFisher.CommonCore.MassPrecisionEstimator.dll",
)

_WINDOWS_DOTNET_HINT = (
    "Thermo .raw support is hosted by .NET Framework, which is part of Windows "
    "10/11 and does not need a separate install. If loading the .NET assemblies "
    "fails, the files are usually blocked by Windows: unblock the downloaded "
    "archive (Properties -> Unblock) before extracting it, or run "
    "'Get-ChildItem -Recurse <app folder> | Unblock-File' in PowerShell. Running "
    "the application straight from a network share or a cloud-synced placeholder "
    "folder fails for the same reason. mzML files are unaffected."
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


def _configure_pythonnet_runtime(runtime: str | None) -> None:
    """Choose the .NET host before ``clr`` is imported.

    On Windows the host is .NET Framework, which ships with the OS, so a frozen
    build runs on a machine with neither Python nor a .NET install.
    """
    if runtime:
        os.environ.setdefault("PYTHONNET_RUNTIME", runtime)
    elif sys.platform == "win32":
        os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")


def _unblock_netfx_assemblies(dll_dir: Path) -> None:
    """Remove the mark of the web from the assemblies .NET Framework will load.

    Windows tags every file extracted from a downloaded archive with a
    ``Zone.Identifier`` stream, and .NET Framework refuses to load such
    assemblies (``Failed to resolve Python.Runtime.Loader.Initialize`` or
    ``loadFromRemoteSources``). The switch that allows them only works in the
    host executable's own ``.exe.config``, so instead strip the tag, as
    ``Unblock-File`` would. Best effort: a read-only install keeps its tags.
    """
    import pythonnet

    pythonnet_runtime_dir = Path(pythonnet.__file__).parent / "runtime"
    for directory in (pythonnet_runtime_dir, dll_dir):
        for assembly_path in directory.glob("*.dll"):
            try:
                os.remove(f"{assembly_path}:Zone.Identifier")
                logger.debug("Unblocked %s", assembly_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("Could not unblock %s: %s", assembly_path, exc)


def _import_clr():
    """Import pythonnet's ``clr`` and return the module that owns ``AddReference``.

    The installed ``clr.py`` is only a shim that calls ``pythonnet.load()``; the
    runtime then replaces ``sys.modules["clr"]`` with the native module built by
    Python.Runtime. A thread that reaches ``import clr`` while another thread is
    still inside ``load()`` is handed the shim instead of the replacement, so
    ``clr.AddReference`` raises ``AttributeError``. Reading the module back out
    of ``sys.modules`` always yields the real one.
    """
    import clr  # noqa: F401  (bound name may be the pre-swap shim)

    return sys.modules["clr"]


def configure_pymzml():
    """Point pymzml at its bundled OBO files in a PyInstaller build.

    When ``sys.frozen`` is set, pymzml looks for ``obo/`` beside the executable
    (the cx_Freeze layout), but PyInstaller keeps it inside the package folder.
    The missing file makes pymzml try to download it, and a bare ``except`` in
    pymzml then turns that failure into ``'NoneType' object is not
    subscriptable`` while decoding every spectrum. ``pymzml.obo`` only reads
    ``sys`` for that check, so hiding ``frozen`` from it restores the
    ``__file__``-relative lookup.
    """
    if not getattr(sys, "frozen", False):
        return

    import types
    import pymzml.obo

    pymzml.obo.sys = types.SimpleNamespace(executable=sys.executable)


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

    Initialisation is serialised: the batch extractor and the scan counter both
    call this from worker threads, and ``clr`` cannot be imported concurrently
    (see ``_import_clr``).
    """
    global _THERMO_INITIALIZED, _THERMO_INIT_ERROR
    global _Device, _RawFileReaderAdapter, _MSOrderType, _Scan

    if _THERMO_INITIALIZED:
        return _Device, _RawFileReaderAdapter, _MSOrderType

    with _THERMO_INIT_LOCK:
        # Another thread may have finished while this one waited for the lock.
        if _THERMO_INITIALIZED:
            return _Device, _RawFileReaderAdapter, _MSOrderType

        if _THERMO_INIT_ERROR is not None:
            message = f"Thermo RawFileReader is unavailable: {_THERMO_INIT_ERROR}"
            if sys.platform == "win32":
                message = f"{message}\n\n{_WINDOWS_DOTNET_HINT}"
            raise RuntimeError(message) from _THERMO_INIT_ERROR

        try:
            runtime, dll_dir = _select_rawfilereader_runtime_and_dir()

            _configure_pythonnet_runtime(runtime)

            if str(dll_dir) not in sys.path:
                sys.path.insert(0, str(dll_dir))

            if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(dll_dir))

            if sys.platform == "win32" and runtime is None:
                _unblock_netfx_assemblies(dll_dir)

            clr = _import_clr()

            for assembly_name in _RAWFILEREADER_ASSEMBLIES:
                assembly_path = dll_dir / assembly_name
                if assembly_path.exists():
                    clr.AddReference(str(assembly_path))

            from ThermoFisher.CommonCore.Data.Business import Device, Scan
            from ThermoFisher.CommonCore.Data.FilterEnums import MSOrderType
            from ThermoFisher.CommonCore.RawFileReader import RawFileReaderAdapter

            _Device = Device
            _Scan = Scan
            _RawFileReaderAdapter = RawFileReaderAdapter
            _MSOrderType = MSOrderType
            _THERMO_INITIALIZED = True
            logger.debug("Loaded Thermo RawFileReader assemblies from %s", dll_dir)
            return _Device, _RawFileReaderAdapter, _MSOrderType
        except Exception as exc:
            _THERMO_INIT_ERROR = exc
            message = f"Thermo RawFileReader is unavailable: {exc}"
            if sys.platform == "win32":
                message = f"{message}\n\n{_WINDOWS_DOTNET_HINT}"
            logger.error(message)
            raise RuntimeError(message) from exc


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


def read_raw_scan_peaks(raw_file, scan_num):
    """Return ``(masses, intensities)`` for a scan, or ``(None, None)``.

    FTMS scans carry a centroid (label) stream. Ion-trap scans do not: their
    peaks live in the segmented scan, stored either as centroids or as
    profile data that has to be centroided here.
    """
    centroid = raw_file.GetCentroidStream(scan_num, False)
    if centroid is not None and centroid.Masses is not None and centroid.Length > 0:
        return list(centroid.Masses), list(centroid.Intensities)

    stats = raw_file.GetScanStatsForScanNumber(scan_num)
    if stats.IsCentroidScan:
        segmented = raw_file.GetSegmentedScanFromScanNumber(scan_num, stats)
        masses, intensities = segmented.Positions, segmented.Intensities
    else:
        centroided = _Scan.ToCentroid(_Scan.FromFile(raw_file, scan_num))
        if centroided is None:
            return None, None
        masses, intensities = centroided.PreferredMasses, centroided.PreferredIntensities

    if masses is None or intensities is None or len(masses) == 0:
        return None, None
    return list(masses), list(intensities)


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
