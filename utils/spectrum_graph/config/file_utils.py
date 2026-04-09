"""UI utility helpers for file dialogs and DataFrame saving."""
import os

import pandas as pd
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QFileDialog, QMessageBox


def get_save_filename(parent, title, default_filename, file_filter, settings_key="last_save_directory"):
    """Get save filename with remembered directory via QSettings.

    Args:
        parent: Parent widget for the dialog.
        title: Dialog window title.
        default_filename: Suggested filename.
        file_filter: File type filter string.
        settings_key: QSettings key used to persist the last directory.

    Returns:
        The chosen filepath, or empty string if cancelled.
    """
    settings = QSettings("SpectrumGraph", "MassSpecViewer")
    last_dir = settings.value(settings_key, "")
    if not last_dir or not os.path.exists(last_dir):
        last_dir = os.path.expanduser("~/Documents")

    full_path = os.path.join(last_dir, default_filename)

    filename, _ = QFileDialog.getSaveFileName(parent, title, full_path, file_filter)

    if filename:
        settings.setValue(settings_key, os.path.dirname(filename))

    return filename


def save_dataframe_to_file(parent, dataframe, filename, description):
    """Save a DataFrame to CSV or Excel with standard error handling.

    Args:
        parent: Parent widget for message boxes.
        dataframe: The pandas DataFrame to save.
        filename: Destination file path.
        description: Human-readable name shown in success/error messages.
    """
    try:
        if filename.endswith('.xlsx'):
            dataframe.to_excel(filename, index=False, engine='openpyxl')
        else:
            dataframe.to_csv(filename, index=False)
        QMessageBox.information(parent, "Success", f"{description} saved successfully to:\n{filename}")
    except Exception as e:
        QMessageBox.critical(parent, "Error", f"Failed to save {description}:\n{str(e)}")
