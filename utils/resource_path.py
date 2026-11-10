"""
Resource Path Helper for PyInstaller
Handles file path resolution for both development and bundled executable modes.
"""

import sys
import os
import logging

logger = logging.getLogger(__name__)


def _resolve_base_path() -> str:
    """Resolve bundled/execution base path once for resource helpers."""
    return getattr(sys, "_MEIPASS", os.path.abspath("."))


def get_resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for both development and PyInstaller bundled app.

    When running as a bundled executable, PyInstaller extracts files to a temporary folder
    and stores the path in sys._MEIPASS.

    Args:
        relative_path: Relative path to the resource (e.g., "data/modifications.csv")

    Returns:
        Absolute path to the resource

    Example:
        >>> csv_path = get_resource_path("data/modifications_list.csv")
        >>> image_path = get_resource_path("assets/up_arrow.png")
    """
    base_path = _resolve_base_path()
    return os.path.join(base_path, relative_path)


def resource_path(relative_path: str) -> str:
    """Alias for get_resource_path — backward compatibility."""
    return get_resource_path(relative_path)


def get_user_data_dir() -> str:
    """
    Get user-specific writable directory (used for log files in bundled mode).

    Returns:
        Path to user data directory (creates if doesn't exist)

    Locations:
        - Windows: C:\\Users\\<username>\\AppData\\Roaming\\MassSpectrumAnalyzer
        - macOS: ~/Library/Application Support/MassSpectrumAnalyzer
        - Linux: ~/.local/share/MassSpectrumAnalyzer
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.local/share")

    app_dir = os.path.join(base, "MassSpectrumAnalyzer")
    os.makedirs(app_dir, exist_ok=True)

    return app_dir


def is_bundled() -> bool:
    """
    Check if the application is running as a bundled executable.

    Returns:
        True if running as PyInstaller bundle, False if running as script
    """
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_data_file_path(filename: str) -> str:
    """
    Get the path for a data file (CSV, JSON, etc.) for both reading and writing.

    Always resolves to the application's own data folder:
        - Development mode: "data/{filename}"
        - Bundled mode: the data folder shipped with the build
          (dist/MassSpectrumAnalyzer/_internal/data), so each build uses the
          lists that were in data/ when it was compiled.

    Args:
        filename: Name of the file (e.g., "modifications_list.csv")

    Returns:
        Path to the data file

    Example:
        >>> csv_path = get_data_file_path("modifications_list.csv")
    """
    if is_bundled():
        return get_resource_path(f"data/{filename}")
    return os.path.join("data", filename)


def get_asset_path(filename: str) -> str:
    """
    Get the appropriate path for an asset file (images, icons, etc.).

    Args:
        filename: Name of the asset file (e.g., "up_arrow.png")

    Returns:
        Absolute path to the asset file

    Example:
        >>> icon_path = get_asset_path("up_arrow.png")
        >>> pixmap = QPixmap(icon_path)
    """
    if is_bundled():
        return get_resource_path(f"assets/{filename}")
    else:
        return os.path.join("assets", filename)


if __name__ == "__main__":
    # Test the functions
    logger.debug("Testing resource path helper...")
    logger.debug(f"Is bundled: {is_bundled()}")
    logger.debug(f"User data directory: {get_user_data_dir()}")
    logger.debug(
        f"Resource path test: {get_resource_path('data/modifications_list.csv')}"
    )
    logger.debug(f"Data file path test: {get_data_file_path('modifications_list.csv')}")
    logger.debug(f"Asset path test: {get_asset_path('up_arrow.png')}")
