"""
_FragmentationGroupsMixin
-------------------------
Comparison group management for the fragmentation tab.
Covers: add_comparison_group, remove_comparison_group,
_update_group_button_states, clear_comparison_groups,
update_comparison_plot, get_selected_ion_types_for_comparison,
get_peptides_from_group, show_save_options, _update_group_name,
_show_group_context_menu, _remove_peptide_from_group.
"""

import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from utils.style.style import EditorConstants
from utils.utility_classes.drag_and_drop_box import DropZoneWidget

logger = logging.getLogger(__name__)


class _FragmentationGroupsMixin:

    def add_comparison_group(self):
        """Add a new comparison group"""
        if len(self.comparison_groups) >= self.max_groups:
            QMessageBox.information(
                self.main_app,
                "Maximum Groups Reached",
                f"Maximum of {self.max_groups} groups allowed.",
            )
            return

        # Generate group identifier - find next available letter
        group_letters = ["A", "B", "C", "D", "E", "F"]
        used_letters = {
            info["group_letter"] for info in self.comparison_groups.values()
        }
        available_letter = None
        for letter in group_letters:
            if letter not in used_letters:
                available_letter = letter
                break
        if available_letter is None:
            return  # shouldn't happen if max_groups check passed

        group_id = f"Group_{available_letter}"
        default_name = f"Group {available_letter}"
        letter_index = ord(available_letter) - ord("A")
        color = self.available_colors[letter_index % len(self.available_colors)]

        # Create editable group name with label
        group_name_layout = QHBoxLayout()
        group_name_layout.setContentsMargins(0, 2, 0, 2)

        # Editable group name input
        group_name_input = QLineEdit(default_name)
        group_name_input.setMaximumWidth(100)
        group_name_input.setMinimumHeight(22)
        group_name_input.setStyleSheet(self._get_group_name_style(color))

        # Connect name change to update function
        group_name_input.textChanged.connect(
            lambda text, gid=group_id: self._update_group_name(gid, text)
        )

        group_name_layout.addWidget(group_name_input)
        group_name_layout.addStretch()

        # Create container for the name input
        group_name_widget = QWidget()
        group_name_widget.setLayout(group_name_layout)

        # Group drop zone
        group_widget = DropZoneWidget(default_name)
        group_widget.setMinimumHeight(80)
        group_widget.setMaximumHeight(120)

        # Style the drop zone
        group_widget.setStyleSheet(self._get_drop_zone_style())

        # Disable selection mode to prevent highlighting
        group_widget.setSelectionMode(group_widget.SelectionMode.NoSelection)

        # Set up context menu for the group widget
        group_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        group_widget.customContextMenuRequested.connect(
            lambda pos, widget=group_widget: self._show_group_context_menu(pos, widget)
        )

        # Add to layout (before the stretch)
        insert_position = self.groups_layout.count() - 1  # Before the stretch
        self.groups_layout.insertWidget(insert_position, group_name_widget)
        self.groups_layout.insertWidget(insert_position + 1, group_widget)

        # Store reference
        self.comparison_groups[group_id] = {
            "widget": group_widget,
            "color": color,
            "name_input": group_name_input,
            "name_widget": group_name_widget,
            "current_name": default_name,
            "original_key": group_id,
            "group_letter": available_letter,
        }

        # Update button states
        self._update_group_button_states()

        self.main_app.show_toast_message(f"Added {default_name}")

    def remove_comparison_group(self):
        """Remove the last comparison group"""
        if len(self.comparison_groups) <= 1:
            QMessageBox.information(
                self.main_app, "Cannot Remove", "At least one group must remain."
            )
            return

        # Find the group with the highest counter number (most recently added)
        group_to_remove = None
        highest_counter = -1

        for group_id, group_info in self.comparison_groups.items():
            # Extract counter from group letter
            letter = group_info["group_letter"]
            counter = ord(letter) - ord("A")
            if counter > highest_counter:
                highest_counter = counter
                group_to_remove = group_id

        if group_to_remove:
            group_info = self.comparison_groups[group_to_remove]
            group_name = group_info["current_name"]

            # Confirm removal if group has peptides
            if group_info["widget"].count() > 0:
                reply = QMessageBox.question(
                    self.main_app,
                    "Remove Group",
                    f"'{group_name}' contains {group_info['widget'].count()} peptide(s). "
                    f"Are you sure you want to remove it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )

                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Remove widgets from layout
            self.groups_layout.removeWidget(group_info["name_widget"])
            self.groups_layout.removeWidget(group_info["widget"])

            # Delete widgets
            group_info["name_widget"].deleteLater()
            group_info["widget"].deleteLater()

            # Remove from groups dictionary
            del self.comparison_groups[group_to_remove]

            # Update button states
            self._update_group_button_states()

            self.main_app.show_toast_message(f"Removed {group_name}")
            logger.debug(
                f"Removed {group_to_remove}. Total groups: {len(self.comparison_groups)}"
            )

    def _update_group_button_states(self):
        """Update the state of add/remove group buttons"""
        group_count = len(self.comparison_groups)

        # Update add button
        self.add_group_button.setEnabled(group_count < self.max_groups)
        if group_count >= self.max_groups:
            self.add_group_button.setText(f"Max Groups ({self.max_groups})")
        else:
            self.add_group_button.setText("Add Group")

        # Update remove button
        self.remove_group_button.setEnabled(group_count > 1)

    def clear_comparison_groups(self):
        """Clear all peptides from all comparison groups"""
        logger.debug("Clearing all comparison groups...")

        total_peptides = sum(
            group_info["widget"].count()
            for group_info in self.comparison_groups.values()
        )

        if total_peptides == 0:
            self.main_app.show_toast_message("No peptides to clear")
            return

        # Confirm clearing
        reply = QMessageBox.question(
            self.main_app,
            "Clear All Groups",
            f"This will remove all {total_peptides} peptides from all groups. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Clear all groups
        for group_info in self.comparison_groups.values():
            group_info["widget"].clear()

        # Clear the comparison plot
        if hasattr(self, "comparison_figure"):
            self.comparison_figure.clear()
            self.comparison_canvas.draw()

        self.main_app.show_toast_message(
            f"Cleared {total_peptides} peptides from all groups"
        )
        logger.debug("All comparison groups cleared successfully")

    def update_comparison_plot(self):
        """Update the comparison plot"""
        # Get current plot type from dropdown
        current_plot_type = self.plot_type_combo.currentText()
        logger.debug(f"Current plot type: {current_plot_type}")

        # Get selected ion types for other plot types
        selected_ions = self.get_selected_ion_types_for_comparison()

        # All other plot types require ion selection
        logger.debug(f"Selected ions for comparison: {selected_ions}")

        if not selected_ions:
            self.show_comparison_message(
                "Please select at least one ion type in the left panel to analyze"
            )
            return

        # Check how many groups have data
        groups_with_data = []
        for group_id, group_info in self.comparison_groups.items():
            peptide_count = group_info["widget"].count()
            logger.debug(f"Group {group_id} has {peptide_count} peptides")
            if peptide_count > 0:
                groups_with_data.append(group_id)

        logger.debug(f"Groups with data: {groups_with_data}")

        if len(groups_with_data) < 1:
            self.show_comparison_message(
                "Please add peptides to at least one group for analysis"
            )
            return

        # Use matplotlib view
        self.plot_stack.setCurrentIndex(0)

        if current_plot_type == "Isotope Ratio Plot":
            logger.debug("Creating isotope ratio plot")
            self.create_isotope_ratio_plot(selected_ions)
        else:  # Ion Count Bar Chart
            logger.debug(
                f"Creating bar chart plot for {len(groups_with_data)} group(s)"
            )
            self.update_bar_chart_plot(selected_ions)

    def get_selected_ion_types_for_comparison(self):
        """Get selected ion types for comparison - FIXED to properly access main app"""
        selected_ions = []

        # Get reference to main app
        main_app = self.main_app

        logger.debug(f"Getting selected ion types from main app: {type(main_app)}")

        # Normal ion types
        if hasattr(main_app, "normal_ion_checkboxes"):
            for ion_type, checkbox in main_app.normal_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append(ion_type)
                    logger.debug(f"Added normal ion: {ion_type}")
        else:
            logger.debug("No normal_ion_checkboxes found on main app")

        # Neutral loss ion types
        if hasattr(main_app, "neutral_ion_checkboxes"):
            for ion_type, checkbox in main_app.neutral_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append(ion_type)
                    logger.debug(f"Added neutral loss ion: {ion_type}")
        else:
            logger.debug("No neutral_ion_checkboxes found on main app")

        # Internal ion types
        if hasattr(main_app, "internal_ion_checkboxes"):
            for ion_type, checkbox in main_app.internal_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append("int-" + ion_type)
                    logger.debug(f"Added internal ion: int-{ion_type}")
        else:
            logger.debug("No internal_ion_checkboxes found on main app")

        # Custom ion series
        if hasattr(main_app, "selected_custom_ions_data"):
            for custom_ion in main_app.selected_custom_ions_data:
                series_name = custom_ion.get("Series Name", "")
                if series_name:
                    selected_ions.append(series_name)
                    logger.debug(f"Added custom ion: {series_name}")
        else:
            logger.debug("No selected_custom_ions_data found on main app")

        logger.debug(f"Total selected ions for comparison: {selected_ions}")
        return selected_ions

    def get_peptides_from_group(self, group_widget):
        """Extract peptide data from a group widget - ENHANCED to ensure consistent data format"""
        peptides = []
        for i in range(group_widget.count()):
            item = group_widget.item(i)
            if hasattr(item, "peptide_data") and item.peptide_data:
                # Ensure the peptide data has the required fields for fragmentation
                peptide_data = item.peptide_data.copy()

                # Map field names to ensure consistency with fragmentation system
                if "Peptide" in peptide_data and "peptide" not in peptide_data:
                    peptide_data["peptide"] = peptide_data["Peptide"]

                if "Charge" in peptide_data and "charge" not in peptide_data:
                    peptide_data["charge"] = peptide_data["Charge"]

                if (
                    "Parsed Modifications" in peptide_data
                    and "parsed_modifications" not in peptide_data
                ):
                    peptide_data["parsed_modifications"] = peptide_data[
                        "Parsed Modifications"
                    ]

                # Ensure we have row_data for spectral data retrieval
                if "row_data" not in peptide_data:
                    # Create row_data from available fields
                    peptide_data["row_data"] = {
                        "spectrum_file_path": peptide_data.get(
                            "spectrum_file_path", ""
                        ),
                        "index": peptide_data.get("index", ""),
                        "Peptide": peptide_data.get("Peptide", ""),
                        "Charge": peptide_data.get("Charge", ""),
                        "Spectrum file": peptide_data.get("Spectrum file", ""),
                    }

                peptides.append(peptide_data)
                logger.debug(
                    f"Retrieved peptide data: {peptide_data.get('Peptide', 'Unknown')}"
                )
            else:
                logger.warning(f"No peptide_data found for item at index {i}")

        logger.debug(f"Extracted {len(peptides)} peptides from group")
        return peptides

    def show_save_options(self):
        """Show save options dialog for comparison data"""
        if (
            not hasattr(self, "comparison_figure")
            or not self.comparison_figure.get_axes()
        ):
            QMessageBox.warning(
                self.main_app,
                "No Graph",
                "No comparison graph to save. Please create a comparison first.",
            )
            return

        # Create a simple dialog with save options
        dialog = QDialog(self.main_app)
        dialog.setWindowTitle("Save Comparison")
        dialog.resize(300, 200)

        layout = QVBoxLayout(dialog)

        # Title
        title_label = QLabel("Choose what to save:")
        title_label.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {EditorConstants.TEXT_COLOR()};"
        )
        layout.addWidget(title_label)

        # Define save options with their export types
        save_options = [
            ("Save Graph as SVG", "primary", "svg"),
            ("Save Graph as PNG", "primary", "png"),
            ("Save Raw Data", "secondary", "xlsx"),
            ("Save Graph + Raw Data", "success", "combined"),
        ]

        # Create buttons dynamically
        for text, style, export_type in save_options:
            btn = QPushButton(text)
            btn.setStyleSheet(EditorConstants.get_pushbutton_style(style))
            btn.clicked.connect(
                lambda checked, et=export_type: (
                    self.export_comparison_data(et),
                    dialog.accept(),
                )
            )
            layout.addWidget(btn)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn)

        dialog.exec()

    def _update_group_name(self, group_id, new_name):
        """Update the display name for a group"""
        if group_id in self.comparison_groups:
            # Update the current display name
            self.comparison_groups[group_id]["current_name"] = (
                new_name
                if new_name.strip()
                else self.comparison_groups[group_id]["original_key"]
            )

            # Update the drop zone's display if needed (for internal tracking)
            group_widget = self.comparison_groups[group_id]["widget"]
            if hasattr(group_widget, "group_name"):
                group_widget.group_name = self.comparison_groups[group_id][
                    "current_name"
                ]

    def _show_group_context_menu(self, position, group_widget):
        """Show context menu for group widgets to delete individual peptides"""
        # Get the item at the clicked position
        item = group_widget.itemAt(position)

        if item is None:
            return  # No item at this position

        # Get the item's index
        item_index = group_widget.row(item)

        # Create context menu
        menu = QMenu(self.main_app)

        # Remove action
        remove_action = QAction("Remove", self.main_app)
        remove_action.triggered.connect(
            lambda: self._remove_peptide_from_group(group_widget, item_index)
        )
        menu.addAction(remove_action)

        # Show the menu
        menu.exec(group_widget.mapToGlobal(position))

    def _remove_peptide_from_group(self, group_widget, item_index):
        """Remove a specific peptide from a group"""
        if 0 <= item_index < group_widget.count():
            item = group_widget.takeItem(item_index)
            if item:
                logger.debug("Removed peptide from group")
                # Update placeholder if group is now empty
                if group_widget.count() == 0:
                    group_widget.update_placeholder()
