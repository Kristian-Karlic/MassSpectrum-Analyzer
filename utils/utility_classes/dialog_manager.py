"""Dialog manager for handling non-modal editor dialogs"""

import logging
from PyQt6.QtWidgets import QMessageBox
from utils.tables.tableeditor import TableEditorDialog

logger = logging.getLogger(__name__)


class DataListEditorManager:
    """Manages non-modal editor dialogs for data lists"""

    def __init__(self, parent):
        self.parent = parent
        self._active_dialogs = {}

    def open_editor(self, data_type: str, current_data, file_path: str, title: str):
        """
        Open or focus existing editor dialog

        Args:
            data_type: Type of data being edited (e.g., 'modifications', 'diagnostic_ions')
            current_data: Current data to edit
            file_path: Path to save the data
            title: Dialog title
        """
        # Check if dialog is already open
        if data_type in self._active_dialogs and self._active_dialogs[data_type] is not None:
            # Bring existing dialog to front
            existing_dialog = self._active_dialogs[data_type]
            existing_dialog.raise_()
            existing_dialog.activateWindow()
            logger.debug(f"Focused existing {title} editor dialog")
            return

        # Create NON-MODAL editor dialog
        editor = TableEditorDialog(data_type, current_data, file_path, self.parent)

        # Store reference to prevent multiple dialogs
        self._active_dialogs[data_type] = editor

        # Connect signals for live updates
        def on_data_updated():
            """Handle live data updates from the editor"""
            try:
                updated_data = editor.get_data()
                self._apply_data_update(data_type, updated_data, is_live=True)
                logger.debug(f"Live updated {data_type} with {len(updated_data)} entries")
            except Exception as e:
                logger.exception(f"Failed to apply live update for {data_type}")

        def on_dialog_finished():
            """Handle dialog close/finish"""
            try:
                updated_data = editor.get_data()
                self._apply_data_update(data_type, updated_data, is_live=False)
                self.parent.show_toast_message(f"{title} updated successfully!")
                logger.debug(f"Final update for {data_type} with {len(updated_data)} entries")
            except Exception as e:
                logger.exception(f"Failed to apply final update for {data_type}")
            finally:
                self._active_dialogs[data_type] = None

        def on_dialog_closed():
            """Handle dialog being closed (X button)"""
            self._active_dialogs[data_type] = None

        # Connect the signals for live updates (if available)
        if hasattr(editor, 'data_changed'):
            editor.data_changed.connect(on_data_updated)

        # Connect finish/close signals
        editor.finished.connect(on_dialog_finished)
        editor.rejected.connect(on_dialog_closed)

        # Show as NON-MODAL dialog
        editor.show()

        logger.debug(f"Opened non-modal {title} editor dialog")

    def _apply_data_update(self, data_type: str, updated_data, is_live: bool = False):
        """
        Apply updated data to the parent application

        Args:
            data_type: Type of data being updated
            updated_data: The updated data
            is_live: Whether this is a live update or final update
        """
        log_prefix = "Live" if is_live else "Final"

        if data_type == "modifications":
            self.parent.available_mods = updated_data
            self.parent.annotation_tab_manager.set_available_modifications(updated_data)
            logger.debug(f"{log_prefix} updated interactive peptide widget with {len(updated_data)} modifications")

        elif data_type == "diagnostic_ions":
            self.parent.diagnostic_ions = updated_data
            self.parent._refresh_diagnostic_dropdown_items()
            # Reconcile already-selected diagnostic ions with updated properties
            self._reconcile_selected_ions(
                self.parent.selected_diagnostic_ions_data,
                updated_data, key_column="Name"
            )
            self.parent._update_selected_diagnostic_ions_table()
            logger.debug(f"{log_prefix} refreshed diagnostic ions dropdown with {len(updated_data)} items")

        elif data_type == "custom_ion_series":
            self.parent.custom_ion_series = updated_data
            self.parent._refresh_custom_dropdown_items()
            # Reconcile already-selected custom ions with updated properties
            self._reconcile_selected_ions(
                self.parent.selected_custom_ions_data,
                updated_data, key_column="Series Name"
            )
            self.parent._update_selected_custom_ions_table()
            logger.debug(f"{log_prefix} refreshed custom ion series dropdown with {len(updated_data)} items")

    @staticmethod
    def _reconcile_selected_ions(selected_list: list, master_data, key_column: str):
        """Update already-selected ions in-place to match current master data.

        Matches each selected ion dict against the master DataFrame by key_column,
        refreshing all other properties. Ions no longer in master data are kept as-is.
        """
        if master_data is None or master_data.empty:
            return
        # Build a lookup from the master DataFrame keyed by the key column
        lookup = {}
        for _, row in master_data.iterrows():
            key = row.get(key_column)
            if key is not None:
                lookup[key] = row.to_dict()

        for ion_dict in selected_list:
            key = ion_dict.get(key_column)
            if key in lookup:
                for prop, value in lookup[key].items():
                    ion_dict[prop] = value
