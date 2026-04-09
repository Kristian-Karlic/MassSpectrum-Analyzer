import logging

logger = logging.getLogger(__name__)

class WindowSizeManager:
    """Utility class for managing application window sizing and presets"""

    @staticmethod
    def apply_size_preset(window, preset_name: str):
        """
        Apply a size preset to the window.

        Args:
            window: QWidget/QMainWindow to resize
            preset_name: One of 'small', 'medium', 'large', 'xlarge'
        """
        from utils.style.GUI_dimensions import LayoutConstants

        if preset_name not in LayoutConstants.WINDOW_PRESETS:
            logger.warning(f"Unknown preset: {preset_name}")
            return

        size = LayoutConstants.WINDOW_PRESETS[preset_name]
        window.resize(size['width'], size['height'])

        # Center the window on screen
        WindowSizeManager.center_window(window)

        logger.debug(f"[Window] Applied '{preset_name}' preset: {size['width']}x{size['height']}")

    @staticmethod
    def center_window(window):
        """Center the window on the primary screen"""
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtCore import Qt

        screen = QGuiApplication.primaryScreen().geometry()
        window_geo = window.geometry()

        x = (screen.width() - window_geo.width()) // 2
        y = (screen.height() - window_geo.height()) // 2

        window.move(x, y)

    @staticmethod
    def set_fullscreen_windowed(window):
        """Set window to maximized state (fullscreen-windowed)"""
        window.showMaximized()
        logger.debug("[Window] Set to fullscreen-windowed mode")

    @staticmethod
    def save_geometry(window, settings_key="window_geometry"):
        """
        Save window geometry to QSettings.

        Args:
            window: QWidget/QMainWindow to save
            settings_key: Key to store geometry under
        """
        from PyQt6.QtCore import QSettings

        settings = QSettings("YourCompany", "MassSpecAnalyzer")
        settings.setValue(settings_key, window.saveGeometry())
        logger.debug(f"[Window] Saved geometry to settings")

    @staticmethod
    def restore_geometry(window, settings_key="window_geometry"):
        """
        Restore window geometry from QSettings.

        Args:
            window: QWidget/QMainWindow to restore
            settings_key: Key to retrieve geometry from

        Returns:
            bool: True if geometry was restored, False otherwise
        """
        from PyQt6.QtCore import QSettings

        settings = QSettings("YourCompany", "MassSpecAnalyzer")
        geometry = settings.value(settings_key)

        if geometry:
            window.restoreGeometry(geometry)
            logger.debug(f"[Window] Restored geometry from settings")
            return True
        return False

    @staticmethod
    def get_available_presets():
        """Get list of available preset names"""
        from utils.style.GUI_dimensions import LayoutConstants
        return list(LayoutConstants.WINDOW_PRESETS.keys())

    @staticmethod
    def get_preset_info(preset_name: str):
        """Get information about a specific preset"""
        from utils.style.GUI_dimensions import LayoutConstants
        if preset_name in LayoutConstants.WINDOW_PRESETS:
            size = LayoutConstants.WINDOW_PRESETS[preset_name]
            return f"{size['width']}x{size['height']}"
        return "Unknown"
