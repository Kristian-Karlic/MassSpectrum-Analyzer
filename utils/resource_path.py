"""
Resource Path Helper for PyInstaller
Handles file path resolution for both development and bundled executable modes.
"""

import sys
import os
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # If not bundled, use the current directory
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)


def get_user_data_dir() -> str:
    """
    Get user-specific writable data directory.
    
    This is where user-editable CSV files and settings should be stored
    when running as a bundled executable.
    
    Returns:
        Path to user data directory (creates if doesn't exist)
    
    Locations:
        - Windows: C:\\Users\\<username>\\AppData\\Roaming\\MassSpectrumAnalyzer
        - macOS: ~/Library/Application Support/MassSpectrumAnalyzer
        - Linux: ~/.local/share/MassSpectrumAnalyzer
    """
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    elif sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.path.expanduser('~/.local/share')
    
    app_dir = os.path.join(base, 'MassSpectrumAnalyzer')
    os.makedirs(app_dir, exist_ok=True)
    
    return app_dir


def is_bundled() -> bool:
    """
    Check if the application is running as a bundled executable.
    
    Returns:
        True if running as PyInstaller bundle, False if running as script
    """
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def initialize_user_data_files(data_files: list = None) -> str:
    """
    Initialize user data directory with bundled CSV files on first run.
    
    Copies CSV files from the bundled resources to a user-writable location.
    Only copies files that don't already exist (preserves user edits).
    
    Args:
        data_files: List of filenames to copy (defaults to common CSV files)
    
    Returns:
        Path to user data directory
    
    Example:
        >>> data_dir = initialize_user_data_files()
        >>> # CSV files are now in user directory
    """
    if data_files is None:
        data_files = [
            'modifications_list.csv',
            'diagnostic_ions.csv',
            'custom_ion_series.csv',
            'maxquant_mods.json',
            'metamorpheus_mods.json',
            'central_modifications.json',
            'custom_presets.json',
            # Include backups
            'modifications_list.csv.backup',
            'diagnostic_ions.csv.backup',
            'custom_ion_series.csv.backup',
        ]
    
    user_dir = get_user_data_dir()
    data_dir = os.path.join(user_dir, 'data')
    
    # Create data directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    
    # Copy each data file from bundled resources to user directory
    for filename in data_files:
        user_file = os.path.join(data_dir, filename)
        
        # Only copy if file doesn't exist (preserve user edits)
        if not os.path.exists(user_file):
            bundled_file = get_resource_path(f'data/{filename}')
            
            if os.path.exists(bundled_file):
                try:
                    shutil.copy2(bundled_file, user_file)
                    logger.info(f"[INIT] Copied {filename} to user data directory")
                except Exception as e:
                    logger.warning(f"Failed to copy {filename}: {e}")
            else:
                logger.warning(f"Bundled file not found: {bundled_file}")
    
    return data_dir


def get_data_file_path(filename: str, prefer_user_dir: bool = True) -> str:
    """
    Get the appropriate path for a data file (CSV, etc.).
    
    In development mode: Returns "data/{filename}"
    In bundled mode with prefer_user_dir=True: Returns user data directory path
    In bundled mode with prefer_user_dir=False: Returns bundled resource path
    
    Args:
        filename: Name of the file (e.g., "modifications_list.csv")
        prefer_user_dir: If True, prefer user directory in bundled mode
    
    Returns:
        Absolute path to the data file
    
    Example:
        >>> # For reading (try user dir first, fall back to bundled)
        >>> csv_path = get_data_file_path("modifications_list.csv")
        >>> 
        >>> # For writing (always use user dir when bundled)
        >>> save_path = get_data_file_path("modifications_list.csv", prefer_user_dir=True)
    """
    if is_bundled():
        if prefer_user_dir:
            user_data_dir = get_user_data_dir()
            user_file_path = os.path.join(user_data_dir, 'data', filename)
            
            # If file exists in user directory, use it
            if os.path.exists(user_file_path):
                return user_file_path
            
            # Otherwise, check bundled resources
            bundled_path = get_resource_path(f'data/{filename}')
            if os.path.exists(bundled_path):
                return bundled_path
            
            # If neither exists, return user path for creation
            return user_file_path
        else:
            # Use bundled resource
            return get_resource_path(f'data/{filename}')
    else:
        # Development mode - use local data directory
        return os.path.join('data', filename)


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
        return get_resource_path(f'assets/{filename}')
    else:
        return os.path.join('assets', filename)


def ensure_user_data_structure() -> dict:
    """
    Ensure complete user data directory structure exists.
    
    Creates necessary folders for user data storage.
    
    Returns:
        Dictionary with paths to key directories
    
    Example:
        >>> paths = ensure_user_data_structure()
        >>> print(paths['data'])  # Path to data directory
        >>> print(paths['exports'])  # Path for user exports
    """
    user_dir = get_user_data_dir()
    
    directories = {
        'root': user_dir,
        'data': os.path.join(user_dir, 'data'),
        'exports': os.path.join(user_dir, 'exports'),
        'cache': os.path.join(user_dir, 'cache'),
        'logs': os.path.join(user_dir, 'logs'),
    }
    
    # Create all directories
    for dir_name, dir_path in directories.items():
        os.makedirs(dir_path, exist_ok=True)
    
    return directories


if __name__ == "__main__":
    # Test the functions
    print("Testing resource path helper...")
    print(f"Is bundled: {is_bundled()}")
    print(f"User data directory: {get_user_data_dir()}")
    print(f"Resource path test: {get_resource_path('data/modifications_list.csv')}")
    print(f"Data file path test: {get_data_file_path('modifications_list.csv')}")
    print(f"Asset path test: {get_asset_path('up_arrow.png')}")
    
    # Test directory structure creation
    paths = ensure_user_data_structure()
    print("\nUser data structure:")
    for name, path in paths.items():
        exists = "✓" if os.path.exists(path) else "✗"
        print(f"  {exists} {name}: {path}")
