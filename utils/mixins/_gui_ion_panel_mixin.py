import logging

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QTableWidgetItem,
    QMenu,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor

from config import ION_PRESETS
from utils.style.style import EditorConstants
from utils.utility_classes.widgets import WidgetFactory, NoScrollComboBox, SearchableComboBox
from utils.style.GUI_dimensions import LayoutConstants
from utils.utilities import MockDataGenerator
from utils.tables.Color_selection import ColorDelegate
from utils.fragmentation_presets_dialog import (
    PresetManagerDialog,
    load_custom_presets,
    save_custom_presets,
)

logger = logging.getLogger(__name__)


class _GUIIonPanelMixin:

    def _init_normal_ion_types(self):
        """Create normal ion types section with header that fits container"""
        # Load persisted custom presets
        self._custom_presets = load_custom_presets()

        # Add preset dropdown
        preset_combo = NoScrollComboBox()
        preset_combo.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        preset_combo.setStyleSheet(EditorConstants.get_combobox_style())
        preset_combo.currentTextChanged.connect(self._apply_ion_preset)
        self.left_layout.addWidget(preset_combo)
        self._ion_preset_combo = preset_combo
        self._refresh_preset_combo()

        # "Save as Preset" button row
        save_preset_btn = QPushButton("Save Current as Preset...")
        save_preset_btn.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        save_preset_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        save_preset_btn.setToolTip(
            "Save the current ion selection as a named custom preset"
        )
        save_preset_btn.clicked.connect(self._save_current_as_preset)
        self.left_layout.addWidget(save_preset_btn)

        # Add section header
        normal_ions_header = self._create_section_header("Normal Ion Types")
        self.left_layout.addWidget(normal_ions_header)

        # Create checkbox grid
        normal_ion_types = [
            "b",
            "y",
            "a",
            "x",
            "z",
            "z+1",
            "c",
            "c-1",
            "MH",
            "d",
            "w",
            "v",
        ]
        self.normal_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self,
            self.left_layout,
            normal_ion_types,
            columns=4,
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20,
        )

        # Connect all checkboxes to adaptive update
        for checkbox in self.normal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)

    @staticmethod
    def _format_neutral_loss_label(raw: str) -> str:
        """
        Convert tokens like 'y-H2O' -> 'y–H₂O' using Unicode subscripts
        """
        parts = raw.split("-", 1)
        if len(parts) == 2:
            ion, loss = parts[0], parts[1]
        else:
            ion, loss = raw, ""

        def unicode_subscript(text: str) -> str:
            """Convert numbers to Unicode subscript"""
            subscript_map = {
                "0": "₀",
                "1": "₁",
                "2": "₂",
                "3": "₃",
                "4": "₄",
                "5": "₅",
                "6": "₆",
                "7": "₇",
                "8": "₈",
                "9": "₉",
            }
            result = text
            for digit, sub in subscript_map.items():
                result = result.replace(digit, sub)
            return result

        # Use en dash (–) instead of hyphen (-)
        if loss:
            return f"{ion}–{unicode_subscript(loss)}"
        return ion

    def _init_neutral_loss_ion_types(self):
        """Create neutral loss ion types section with header that fits container"""
        neutral_loss_header = self._create_section_header("Neutral Loss Ion Types")
        self.left_layout.addWidget(neutral_loss_header)

        neutral_loss_ion_types = [
            "y-H2O",
            "a-H2O",
            "b-H2O",
            "y-NH3",
            "b-NH3",
            "a-NH3",
            "b-SOCH4",
            "y-SOCH4",
            "b-H3PO4",
            "y-H3PO4",
            "a-H3PO4",
            "MH-H2O",
            "MH-NH3",
            "d-H2O",
            "d-NH3",
            "w-H2O",
            "w-NH3",
            "v-H2O",
            "v-NH3",
        ]

        self.neutral_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self,
            self.left_layout,
            neutral_loss_ion_types,
            columns=3,
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20,
            label_formatter=self._format_neutral_loss_label,
        )

        for checkbox in self.neutral_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)

    def _apply_ion_preset(self, preset_name: str) -> None:
        """Apply an ion selection preset from the dropdown."""
        if preset_name == "-- Presets --" or preset_name.startswith("Selected:"):
            return

        # Check built-in presets first, then custom
        preset = ION_PRESETS.get(preset_name)
        is_full_preset = False
        if preset is None:
            raw_custom = self._custom_presets.get(preset_name)
            if raw_custom is None:
                return
            # Convert stored lists back to sets for the checkbox loop
            preset = {
                "normal": set(raw_custom.get("normal", [])),
                "neutral": set(raw_custom.get("neutral", [])),
            }
            is_full_preset = True
            custom_ions_data = raw_custom.get("custom_ions", [])
            diagnostic_ions_data = raw_custom.get("diagnostic_ions", [])

        # Block signals to avoid refragmenting for every single checkbox toggle
        for cb in self.normal_ion_checkboxes.values():
            cb.blockSignals(True)
        for cb in self.neutral_ion_checkboxes.values():
            cb.blockSignals(True)
        # Uncheck all, then check the preset's ions
        for ion, cb in self.normal_ion_checkboxes.items():
            cb.setCheckState(
                Qt.CheckState.Checked
                if ion in preset["normal"]
                else Qt.CheckState.Unchecked
            )
        for ion, cb in self.neutral_ion_checkboxes.items():
            cb.setCheckState(
                Qt.CheckState.Checked
                if ion in preset["neutral"]
                else Qt.CheckState.Unchecked
            )
        # Unblock
        for cb in self.normal_ion_checkboxes.values():
            cb.blockSignals(False)
        for cb in self.neutral_ion_checkboxes.values():
            cb.blockSignals(False)

        # Apply custom/diagnostic ions — always reset these tables so stale
        # entries from a previous preset are not carried over when switching
        # to a built-in preset (which defines no custom or diagnostic ions).
        if is_full_preset:
            self.selected_custom_ions_data = list(custom_ions_data)
            self._reconcile_selected_ions_from_master(
                self.selected_custom_ions_data, self.custom_ion_series, "Series Name"
            )
            self.selected_diagnostic_ions_data = list(diagnostic_ions_data)
            self._reconcile_selected_ions_from_master(
                self.selected_diagnostic_ions_data, self.diagnostic_ions, "Name"
            )

            # Restore enable-flag checkboxes (block signals; one update fires below)
            for attr, key in (
                ("enable_mod_nl_cb", "enable_mod_nl"),
                ("enable_labile_losses_cb", "enable_labile_losses"),
                ("enable_remainder_ions_cb", "enable_remainder_ions"),
                ("glycan_enabled_cb", "glycan_y_enabled"),
                ("glycan_snfg_cb", "glycan_snfg_enabled"),
            ):
                cb = getattr(self, attr, None)
                if cb is not None and key in raw_custom:
                    cb.blockSignals(True)
                    cb.setChecked(raw_custom[key])
                    cb.blockSignals(False)

            # Restore glycan max charge
            if "glycan_max_charge" in raw_custom:
                spin = getattr(self, "glycan_max_charge_spin", None)
                if spin is not None:
                    spin.blockSignals(True)
                    spin.setValue(raw_custom["glycan_max_charge"])
                    spin.blockSignals(False)

            # Restore glycan composition text
            if "glycan_composition" in raw_custom:
                combo = getattr(self, "glycan_composition_combo", None)
                if combo is not None:
                    combo.blockSignals(True)
                    combo.setCurrentText(raw_custom["glycan_composition"])
                    combo.blockSignals(False)
        else:
            # Built-in preset: clear any custom/diagnostic ions left from a
            # previously applied full preset, and reset all extra toggles to
            # their default (off) state.
            self.selected_custom_ions_data = []
            self.selected_diagnostic_ions_data = []

            for attr in (
                "enable_mod_nl_cb",
                "enable_labile_losses_cb",
                "enable_remainder_ions_cb",
                "glycan_enabled_cb",
                "glycan_snfg_cb",
            ):
                cb = getattr(self, attr, None)
                if cb is not None:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)

            spin = getattr(self, "glycan_max_charge_spin", None)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(4)
                spin.blockSignals(False)

        self._update_selected_custom_ions_table()
        self._update_selected_diagnostic_ions_table()

        # Sync glycan state to the viewer (signals were blocked above)
        if callable(getattr(self, "_on_glycan_settings_changed", None)):
            self._on_glycan_settings_changed()
        if callable(getattr(self, "_on_glycan_snfg_toggled", None)):
            snfg_checked = getattr(self, "glycan_snfg_cb", None)
            self._on_glycan_snfg_toggled(snfg_checked.isChecked() if snfg_checked else False)

        # Reset dropdown to show the selected preset name
        self._ion_preset_combo.blockSignals(True)
        self._ion_preset_combo.setItemText(0, f"Selected: {preset_name}")
        self._ion_preset_combo.setCurrentIndex(0)
        self._ion_preset_combo.blockSignals(False)
        # Trigger a single update
        self.on_settings_changed()

    def _refresh_preset_combo(self) -> None:
        """Re-populate the preset combo box with built-in and custom presets."""
        combo = self._ion_preset_combo
        # Preserve the current placeholder text (e.g. "Selected: HCD-Glyco")
        current_placeholder = combo.itemText(0) if combo.count() > 0 else "-- Presets --"
        if not current_placeholder.startswith("Selected:"):
            current_placeholder = "-- Presets --"
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(current_placeholder)
        for name in ION_PRESETS:
            combo.addItem(name)
        for name in self._custom_presets:
            combo.addItem(name)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _get_current_preset_state(self) -> dict:
        """Capture the current ion selection state as a preset-compatible dict."""
        normal = [
            ion for ion, cb in self.normal_ion_checkboxes.items() if cb.isChecked()
        ]
        neutral = [
            ion for ion, cb in self.neutral_ion_checkboxes.items() if cb.isChecked()
        ]
        return {
            "normal": normal,
            "neutral": neutral,
            "custom_ions": list(self.selected_custom_ions_data),
            "diagnostic_ions": list(self.selected_diagnostic_ions_data),
            "enable_mod_nl": self.enable_mod_nl_cb.isChecked(),
            "enable_labile_losses": self.enable_labile_losses_cb.isChecked(),
            "enable_remainder_ions": self.enable_remainder_ions_cb.isChecked(),
            "glycan_y_enabled": self.glycan_enabled_cb.isChecked(),
            "glycan_composition": self.glycan_composition_combo.currentText().strip(),
            "glycan_max_charge": self.glycan_max_charge_spin.value(),
            "glycan_snfg_enabled": self.glycan_snfg_cb.isChecked(),
        }

    def _save_current_as_preset(self) -> None:
        """Prompt the user for a name and save the current ion selection as a custom preset."""
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "Save as Custom Preset",
            "Enter a name for this fragmentation method preset:",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Preset name cannot be empty.")
            return
        if name in ION_PRESETS:
            QMessageBox.warning(
                self,
                "Reserved Name",
                f"'{name}' is a built-in preset name and cannot be overwritten.",
            )
            return
        if name in self._custom_presets:
            reply = QMessageBox.question(
                self,
                "Overwrite Preset",
                f"A custom preset named '{name}' already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._custom_presets[name] = self._get_current_preset_state()
        if save_custom_presets(self._custom_presets):
            self._refresh_preset_combo()
            self.show_toast_message(f"Preset '{name}' saved.")
            # Refresh the manager dialog if it's open
            if (
                hasattr(self, "_preset_manager_dialog")
                and self._preset_manager_dialog is not None
            ):
                self._preset_manager_dialog.custom_presets = load_custom_presets()
                self._preset_manager_dialog.refresh()
        else:
            QMessageBox.critical(self, "Error", "Failed to save preset to disk.")

    def _open_preset_manager(self) -> None:
        """Open (or focus) the non-modal Preset Manager dialog."""
        if (
            hasattr(self, "_preset_manager_dialog")
            and self._preset_manager_dialog is not None
        ):
            self._preset_manager_dialog.raise_()
            self._preset_manager_dialog.activateWindow()
            return

        dlg = PresetManagerDialog(ION_PRESETS, parent=self)
        self._preset_manager_dialog = dlg

        def _on_presets_changed():
            self._custom_presets = load_custom_presets()
            self._refresh_preset_combo()

        dlg.presets_changed.connect(_on_presets_changed)
        dlg.finished.connect(lambda: setattr(self, "_preset_manager_dialog", None))
        dlg.show()

    def _init_internal_ion_types(self):
        """Create internal ion types section with header that fits container"""
        # Add section header
        internal_ions_header = self._create_section_header("Internal Ion Types")
        self.left_layout.addWidget(internal_ions_header)

        # Create checkbox grid
        internal_ions = ["b", "a"]
        self.internal_ion_checkboxes = WidgetFactory.create_checkbox_grid(
            self,
            self.left_layout,
            internal_ions,
            columns=4,
            max_width=LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20,
        )

        # Connect all checkboxes to adaptive update
        for checkbox in self.internal_ion_checkboxes.values():
            checkbox.stateChanged.connect(self.on_settings_changed)


    def _init_diagnostic_ions_section(self):
        """Create diagnostic ions selection using SearchableComboBox"""
        self.left_layout.addWidget(self._create_section_header("Diagnostic Ions"))

        self.diagnostic_ion_dropdown = SearchableComboBox(
            "Click or type to search diagnostic ions..."
        )
        self.diagnostic_ion_dropdown.item_selected.connect(
            self._add_diagnostic_ion_from_dropdown
        )
        self.left_layout.addWidget(self.diagnostic_ion_dropdown)

        # selected table
        self.selected_diagnostic_ions_table = self._create_selection_table(
            ["Name", "Mass"],
            self._show_diagnostic_ion_context_menu,
            "selected_diagnostic_ions_data",
        )
        # Apply color delegate to the Color column (index 3)
        self.selected_diagnostic_ions_color_delegate = ColorDelegate()
        self.selected_diagnostic_ions_table.setItemDelegateForColumn(
            3, self.selected_diagnostic_ions_color_delegate
        )
        self.left_layout.addWidget(self.selected_diagnostic_ions_table)

        self.selected_diagnostic_ions_data = []
        self._refresh_diagnostic_dropdown_items()

    def _init_custom_ion_series_section(self):
        """Create custom ion series selection using SearchableComboBox"""
        self.left_layout.addWidget(self._create_section_header("Custom Ion Series"))

        self.custom_ion_dropdown = SearchableComboBox(
            "Click or type to search custom ion series..."
        )
        self.custom_ion_dropdown.item_selected.connect(
            self._add_custom_ion_from_dropdown
        )
        self.left_layout.addWidget(self.custom_ion_dropdown)

        # selected table
        self.selected_custom_ions_table = self._create_selection_table(
            ["Series Name", "Mass Offset", "Restriction"],
            self._show_custom_ion_context_menu,
            "selected_custom_ions_data",
        )
        # Apply color delegate to the Color column (index 3)
        self.selected_custom_ions_color_delegate = ColorDelegate()
        self.selected_custom_ions_table.setItemDelegateForColumn(
            3, self.selected_custom_ions_color_delegate
        )
        self.left_layout.addWidget(self.selected_custom_ions_table)

        # initialize lists
        self.selected_custom_ions_data = []
        self._refresh_custom_dropdown_items()

    def _refresh_ion_dropdown(
        self, dropdown_attr: str, data_source: str, display_format_fn
    ) -> None:
        """
        Generic method to refresh dropdown items from a data source

        Args:
            dropdown_attr: Name of the dropdown attribute (e.g., 'custom_ion_dropdown')
            data_source: Name of the data source attribute (e.g., 'custom_ion_series')
            display_format_fn: Function that takes a row dict and returns (display_text, row_dict)
        """
        items = []
        try:
            dropdown = getattr(self, dropdown_attr)
            dropdown.clear_items()

            data = getattr(self, data_source)

            # If data is DataFrame-like
            if hasattr(data, "itertuples") and hasattr(data, "columns"):
                columns = list(data.columns)
                for row_tuple in data.itertuples(index=False, name=None):
                    row_dict_in = dict(zip(columns, row_tuple))
                    display, row_dict = display_format_fn(row_dict_in)
                    items.append((display, row_dict))
            else:
                # fallback: if it's a list of dicts
                for row in data or []:
                    display, row_dict = display_format_fn(row)
                    items.append((display, row_dict))

            dropdown.set_items(items)

        except Exception:
            logger.exception(f"Failed to refresh {dropdown_attr}")

    def _refresh_custom_dropdown_items(self):
        """Populate custom dropdown from self.custom_ion_series"""

        def format_custom_ion(row):
            restriction = (
                str(row.get("Restriction", ""))
                if row.get("Restriction") is not None
                else ""
            )
            restriction_suffix = f" [{restriction}]" if restriction else ""
            display = f"{row['Series Name']} — {row['Base Ion']} ({row['Mass Offset']:.4f}){restriction_suffix}"
            return display, row

        self._refresh_ion_dropdown(
            "custom_ion_dropdown", "custom_ion_series", format_custom_ion
        )

    def _refresh_diagnostic_dropdown_items(self):
        """Populate diagnostic dropdown from self.diagnostic_ions"""

        def format_diagnostic_ion(row):
            display = f"{row['Name']} ({row['Mass']:.4f})"
            return display, row

        self._refresh_ion_dropdown(
            "diagnostic_ion_dropdown", "diagnostic_ions", format_diagnostic_ion
        )

    def _add_custom_ion_from_dropdown(self, selected_row_dict):
        """Delegate to event handlers"""
        return self.event_handlers.on_custom_ion_selected(selected_row_dict)

    def _add_diagnostic_ion_from_dropdown(self, selected_row_dict):
        """Delegate to event handlers"""
        return self.event_handlers.on_diagnostic_ion_selected(selected_row_dict)

    def load_mock_data(self) -> None:
        """Load mock data using utility"""
        matched_data, mock_row_data = MockDataGenerator.generate_mock_spectrum_data()

        # Use annotation manager to set data
        self.annotation_tab_manager.set_mass_spec_data(
            matched_data=matched_data,
            peptide=self.DEFAULT_MOCK_PEPTIDE,
            mod_positions=[],
            row_data=mock_row_data,
        )

    # -----------------------------------------------------------------
    # Generic Ion Selection Methods
    # -----------------------------------------------------------------
    def _remove_selected_ion(
        self, row_index, data_list_attr, update_method, name_key, ion_type_name
    ):
        """Generic method to remove an ion from a selection list"""
        data_list = getattr(self, data_list_attr)
        if 0 <= row_index < len(data_list):
            removed_ion = data_list.pop(row_index)
            update_method()
            self.on_settings_changed()
            self.show_toast_message(
                f"Removed '{removed_ion[name_key]}' from {ion_type_name}."
            )

    def _show_ion_context_menu(
        self, position, table, data_list_attr, remove_action_text, remove_callback
    ):
        """Generic method to show context menu for ion selection tables"""
        item = table.itemAt(position)

        if item is None:
            return

        row = item.row()
        data_list = getattr(self, data_list_attr)
        if row >= len(data_list):
            return

        menu = QMenu(self)
        remove_action = QAction(remove_action_text, self)
        remove_action.triggered.connect(lambda: remove_callback(row))
        menu.addAction(remove_action)
        menu.exec(table.mapToGlobal(position))

    @staticmethod
    def _reconcile_selected_ions_from_master(
        selected_list: list, master_data, key_column: str
    ):
        """Refresh selected ion dicts in-place from the master DataFrame.

        Matches by key_column and updates all properties to current values.
        Ions no longer in master data are kept with their stored values.
        """
        if master_data is None or master_data.empty:
            return
        lookup = {}
        columns = list(master_data.columns)
        for row_tuple in master_data.itertuples(index=False, name=None):
            row_dict = dict(zip(columns, row_tuple))
            key = row_dict.get(key_column)
            if key is not None:
                lookup[key] = row_dict
        for ion_dict in selected_list:
            key = ion_dict.get(key_column)
            if key in lookup:
                for prop, value in lookup[key].items():
                    ion_dict[prop] = value

    def _update_ion_selection_table(
        self, table, data_list, column_configs, color_column_idx=None
    ):
        """
        Generic method to update ion selection tables

        Args:
            table: The QTableWidget to update
            data_list: List of dictionaries containing ion data
            column_configs: List of tuples (data_key, format_string) for each column
                          format_string can be None (use str()), a format like '.4f', or a callable
            color_column_idx: Index of the color column (if any)
        """
        table.setRowCount(len(data_list))

        for row_idx, ion_data in enumerate(data_list):
            for col_idx, (data_key, format_spec) in enumerate(column_configs):
                value = ion_data.get(data_key, "")

                # Format the value
                if format_spec is None:
                    text = str(value) if value else ""
                elif callable(format_spec):
                    text = format_spec(value)
                elif isinstance(format_spec, str) and "." in format_spec:
                    # It's a numeric format like '.4f'
                    text = f"{value:{format_spec}}"
                else:
                    text = str(value) if value else ""

                item = QTableWidgetItem(text)

                # Handle color column
                if col_idx == color_column_idx and value:
                    item.setBackground(QColor(value))
                    text_color = QColor(
                        EditorConstants.get_contrasting_text_color(value)
                    )
                    item.setForeground(text_color)
                else:
                    item.setForeground(QColor(EditorConstants.TEXT_COLOR()))

                table.setItem(row_idx, col_idx, item)

    def _remove_custom_ion(self, row_index):
        """Remove custom ion from selected list"""
        self._remove_selected_ion(
            row_index,
            "selected_custom_ions_data",
            self._update_selected_custom_ions_table,
            "Series Name",
            "selected custom ions",
        )

    def _update_selected_custom_ions_table(self):
        """Update the selected custom ions table display"""
        column_configs = [
            ("Series Name", None),
            ("Mass Offset", ".4f"),
            ("Restriction", lambda v: str(v) if v else ""),
        ]
        self._update_ion_selection_table(
            self.selected_custom_ions_table,
            self.selected_custom_ions_data,
            column_configs,
            color_column_idx=3,
        )

    def _show_custom_ion_context_menu(self, position):
        """Show context menu for custom ion table"""
        self._show_ion_context_menu(
            position,
            self.selected_custom_ions_table,
            "selected_custom_ions_data",
            "Remove Custom Ion",
            self._remove_custom_ion,
        )

    def _remove_diagnostic_ion(self, row_index):
        """Remove diagnostic ion from selected list"""
        self._remove_selected_ion(
            row_index,
            "selected_diagnostic_ions_data",
            self._update_selected_diagnostic_ions_table,
            "Name",
            "selected diagnostic ions",
        )

    def _update_selected_diagnostic_ions_table(self):
        """Update the selected diagnostic ions table display"""
        column_configs = [
            ("Name", None),
            ("Mass", ".4f")
        ]
        self._update_ion_selection_table(
            self.selected_diagnostic_ions_table,
            self.selected_diagnostic_ions_data,
            column_configs,
            color_column_idx=3,
        )

    def _show_diagnostic_ion_context_menu(self, position):
        """Show context menu for diagnostic ion table"""
        item = self.selected_diagnostic_ions_table.itemAt(position)
        if item is None:
            return

        row = item.row()
        if row >= len(self.selected_diagnostic_ions_data):
            return

        menu = QMenu(self)

        remove_action = QAction("Remove Diagnostic Ion", self)
        remove_action.triggered.connect(lambda: self._remove_diagnostic_ion(row))
        menu.addAction(remove_action)

        remove_all_action = QAction("Remove All Diagnostic Ions", self)
        remove_all_action.triggered.connect(self._remove_all_diagnostic_ions)
        menu.addAction(remove_all_action)

        menu.exec(self.selected_diagnostic_ions_table.mapToGlobal(position))

    def _remove_all_diagnostic_ions(self):
        """Clear all diagnostic ions from the selected list"""
        self.selected_diagnostic_ions_data.clear()
        self._update_selected_diagnostic_ions_table()
