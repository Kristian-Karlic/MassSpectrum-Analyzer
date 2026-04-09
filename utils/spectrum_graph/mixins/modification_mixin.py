import logging
from typing import Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCursor, QAction
from PyQt6.QtWidgets import QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QCompleter

from ..classes.modification_item import ModificationItem
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class ModificationMixin:
    """Modification management for MassSpecViewer."""

    def set_available_modifications(self, modifications):
        """Set available modifications for the peptide widget"""

        # Convert DataFrame or other formats to a consistent list of dicts
        if hasattr(modifications, 'iterrows'):
            # It's a DataFrame
            self.available_modifications = []
            for _, row in modifications.iterrows():
                self.available_modifications.append({
                    'Name': row.get('Name', ''),
                    'Mass': row.get('Mass', 0)
                })
        elif isinstance(modifications, list):
            # It's already a list
            self.available_modifications = modifications
        else:
            self.available_modifications = []

        logger.debug(f"Processed {len(self.available_modifications)} available modifications")

    def set_modifications(self, modifications: list):
        """Set current modifications and emit signal - FIXED to handle restoration vs new changes"""

        # Don't emit signal during data updates to prevent recursion
        if getattr(self, '_updating_data', False):
            self.current_interactive_mods = modifications
            # Still need to update the internal data structure during data updates
            if modifications:
                self._update_modifications_data(modifications)
            else:
                self.modifications = {}
            return

        if (hasattr(self, 'current_interactive_mods') and
            self.current_interactive_mods == modifications and
            modifications):  # Don't skip for empty modifications
            logger.debug(f"Modifications unchanged - updating display only")
            # Clear existing modifications
            self.modifications = {}
            # Process the modifications list
            self._update_modifications_data(modifications)
            # Update visual display
            self.update_modification_display()
            return

        # Clear existing modifications
        self.modifications = {}

        # Ensure modifications is a list (handle None case)
        if modifications is None:
            modifications = []

        if modifications:
            # Process the modifications list
            self._update_modifications_data(modifications)

        # Update visual display
        self.update_modification_display()

        # Store for signal emission
        self.current_interactive_mods = modifications

        # Emit the signal for GUI to catch (now guaranteed to be a list)
        self.modificationsChanged.emit(modifications)

        logger.debug(f"Set {len(self.modifications)} modification positions")

    def _update_modifications_data(self, modifications: list):
        """Helper method to update modifications data structure"""
        for mass, position in modifications:
            if position not in self.modifications:
                self.modifications[position] = []

            # Try to find name for this mass
            name = self.get_modification_name(mass)
            self.modifications[position].append((mass, name))

    def get_modification_name(self, mass: float) -> str:
        """Get modification name from mass"""
        if not self.available_modifications:
            return f"+{mass:.0f}"

        for mod in self.available_modifications:
            try:
                mod_mass = float(mod.get('Mass', 0))
                if abs(mod_mass - mass) < 0.01:
                    return mod.get('Name', f"+{mass:.0f}")
            except (ValueError, TypeError, AttributeError):
                continue

        return f"+{mass:.0f}"

    def get_modifications(self) -> list:
        """Get current modifications"""
        return getattr(self, 'current_interactive_mods', [])

    def show_amino_acid_context_menu(self, position: int, event):
        """Show context menu for amino acid position - FIXED to match original"""

        # Find the associated text item and apply temporary emphasis
        text_item = None
        for item_data in self.amino_acid_items:
            if item_data.get('position') == position:
                text_item = item_data.get('item')
                break

        if text_item:
            try:
                text_item.apply_temporary_emphasis(scale=1.35)
            except Exception as e:
                logger.debug(f"Error applying temporary emphasis: {e}")

        menu = QMenu()

        # Check if this position has modifications
        has_modifications = position in self.modifications and self.modifications[position]
        mod_count = len(self.modifications.get(position, []))

        # Add modification action (limit to 2)
        if mod_count < 2:
            add_action = QAction("Add Modification...", menu)
            add_action.triggered.connect(lambda: self.show_modification_selector(position))
            menu.addAction(add_action)
        else:
            # Show warning that max modifications reached
            warning_action = QAction("Maximum 2 modifications per position", menu)
            warning_action.setEnabled(False)
            menu.addAction(warning_action)

        # Delete modifications action (only if there are modifications)
        if has_modifications:
            menu.addSeparator()
            delete_action = QAction("Delete All Modifications", menu)
            delete_action.triggered.connect(lambda: self.delete_all_modifications_at_position(position))
            menu.addAction(delete_action)

            # Individual modification deletion
            for i, (mass, name) in enumerate(self.modifications[position]):
                location_text = "above" if i == 1 else "below"
                delete_single_action = QAction(f"Delete {name} ({location_text})", menu)
                delete_single_action.triggered.connect(
                    lambda checked, m=mass, p=position: self.delete_single_modification(p, m)
                )
                menu.addAction(delete_single_action)

        # Show menu at cursor position
        try:
            menu.exec(QCursor.pos())
        finally:
            # Always remove temporary emphasis after the menu closes
            if text_item:
                try:
                    text_item.remove_temporary_emphasis()
                except Exception as e:
                    logger.debug(f"Error removing temporary emphasis: {e}")

    def delete_single_modification(self, position: int, mass: float):
        """Delete a single modification - ADDED method"""
        if position in self.modifications:
            mods = self.modifications[position]
            for i, (mod_mass, name) in enumerate(mods):
                if abs(mod_mass - mass) < 0.01:
                    mods.pop(i)
                    if not mods:  # If no more mods at this position
                        del self.modifications[position]
                    break
            self.update_modification_display()
            self.emit_modifications_changed()

    def show_modification_selector(self, position: int):
        """Show searchable modification selector dialog - FIXED to match original"""


        logger.debug(f"Showing modification selector for position {position}")

        # Check if we have available modifications
        if (not hasattr(self, 'available_modifications') or
            self.available_modifications is None or
            len(self.available_modifications) == 0):
            print("[DEBUG] No available modifications found")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Add Modification to Position {position}")
        dialog.setFixedSize(400, 300)

        layout = QVBoxLayout(dialog)

        # Search field
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))

        search_field = QLineEdit()
        search_field.setPlaceholderText("Type to search modifications...")
        search_layout.addWidget(search_field)
        layout.addLayout(search_layout)

        # Modification list (combobox with search)
        mod_selector = QComboBox()
        mod_selector.setEditable(True)
        mod_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        # Populate with available modifications
        mod_names = []
        for mod in self.available_modifications:
            name = mod.get('Name', 'Unknown')
            mass = mod.get('Mass', 0)
            display_name = f"{name} (+{mass})"
            mod_selector.addItem(display_name, mod)
            mod_names.append(display_name)

        # Setup completer for search
        completer = QCompleter(mod_names)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        mod_selector.setCompleter(completer)

        # Connect search field to filter combobox
        def filter_modifications(search_text: str):
            """Filter the modification combobox based on search text"""
            mod_selector.clear()

            search_lower = search_text.lower()
            for mod in self.available_modifications:
                name = mod.get('Name', 'Unknown')
                mass = mod.get('Mass', 0)
                display_name = f"{name} (+{mass})"

                if search_lower in name.lower() or search_lower in str(mass):
                    mod_selector.addItem(display_name, mod)

        search_field.textChanged.connect(filter_modifications)

        layout.addWidget(mod_selector)

        # Buttons
        button_layout = QHBoxLayout()

        def add_selected_modification():
            """Add the selected modification from the dialog"""
            current_data = mod_selector.currentData()
            if current_data:
                mass = float(current_data.get('Mass', 0))
                name = current_data.get('Name', f"+{mass}")
                success = self.add_modification(position, mass, name)
                if success:
                    dialog.accept()
                else:
                    logger.warning(f"Failed to add modification {name} at position {position}")
            else:
                print("[WARNING] No modification selected")

        add_button = QPushButton("Add")
        add_button.clicked.connect(add_selected_modification)
        button_layout.addWidget(add_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        # Execute dialog
        dialog.exec()

    # ADD: Missing modification visual methods
    def add_modification_visual(self, position: int, mass: float, name: str, color: QColor, mod_index: int = 0):
        """Add a visual modification item with stacking support (max 2 per position) - FIXED like original"""
        x_pos = self.get_position_x(position)
        if x_pos is None:
            logger.debug(f"Could not find x position for position {position}")
            return

        # Calculate stacking position (FIXED to match original positioning)
        if mod_index == 0:
            # First modification goes below the peptide sequence (like original)
            y_pos = -120  # Below the peptide sequence
        elif mod_index == 1:
            # Second modification goes above the peptide sequence (like original)
            y_pos = 120   # Above the peptide sequence
        else:
            # If somehow more than 2 modifications, stack below with offset (like original)
            y_pos = -120 - ((mod_index - 1) * 15)

        mod_item = ModificationItem(position, mass, name, color, self)
        mod_item.setPos(x_pos, y_pos)

        # Connect signals
        mod_item.modificationMoved.connect(self.handle_modification_moved)
        mod_item.modificationRemoved.connect(self.handle_modification_removed)

        self.peptide_plot.addItem(mod_item)
        self.modification_items.append(mod_item)

    def handle_modification_moved(self, old_pos: int, new_pos: int, mass: float):
        """Handle when a modification is moved to a new position - FIXED like original"""
        # Find the modification in our data structure
        if old_pos in self.modifications:
            mods = self.modifications[old_pos]
            for i, (mod_mass, name) in enumerate(mods):
                if abs(mod_mass - mass) < 0.01:
                    # Remove from old position
                    removed_mod = mods.pop(i)
                    if not mods:  # If no more mods at this position
                        del self.modifications[old_pos]

                    # Add to new position
                    if new_pos not in self.modifications:
                        self.modifications[new_pos] = []
                    self.modifications[new_pos].append(removed_mod)
                    break

        self.update_modification_display()
        self.emit_modifications_changed()

    def handle_modification_removed(self, position: int, mass: float):
        """Handle when a modification is removed - FIXED to properly handle last modification"""
        logger.debug(f"handle_modification_removed called: position={position}, mass={mass}")

        if position in self.modifications:
            mods = self.modifications[position]
            for i, (mod_mass, name) in enumerate(mods):
                if abs(mod_mass - mass) < 0.01:
                    logger.debug(f"Removing modification {name} from position {position}")
                    mods.pop(i)
                    if not mods:  # If no more mods at this position
                        del self.modifications[position]
                        logger.debug(f"Removed empty modification list for position {position}")
                    break

        logger.debug(f"Remaining modifications after removal: {self.modifications}")
        self.update_modification_display()

        self.current_interactive_mods = []
        for pos, mods in self.modifications.items():
            for mass, name in mods:
                self.current_interactive_mods.append((mass, pos))

        logger.debug(f"Updated current_interactive_mods: {self.current_interactive_mods}")

        self.emit_modifications_changed()

        #  Force visual refresh to ensure everything is cleared when empty
        if not self.modifications:
            print("[DEBUG] No modifications remaining - forcing complete visual refresh")
            # Clear all modification items manually
            for mod_item in self.modification_items:
                self.peptide_plot.removeItem(mod_item)
            self.modification_items.clear()

            # Update legend to show "None"
            if hasattr(self, 'legend'):
                self.legend.update_legend({}, [])

    def set_nl_legend_info(self, entries: list):
        """Store NL/labile/remainder symbol legend entries and refresh the legend."""
        self.nl_legend_entries = entries or []
        self.update_modification_display()

    def update_modification_display(self):
        """Update the display of modifications with color coding and stacking - FIXED for last modification removal"""
        logger.debug(f"Updating modification display with {len(self.modifications)} positions")

        # Clear existing modification items FIRST
        for mod_item in self.modification_items:
            self.peptide_plot.removeItem(mod_item)
        self.modification_items.clear()

        # ALWAYS update legend first, even if modifications is empty
        if hasattr(self, 'legend'):
            self.legend.update_legend(self.modifications, getattr(self, 'nl_legend_entries', []))
            logger.debug(f"Legend updated with {len(self.modifications)} modification positions")

        # Only add visual items if we have modifications
        if self.modifications:
            # Add new modification items with assigned colors from legend
            for position, mods in self.modifications.items():
                logger.debug(f"Adding modifications at position {position}: {mods}")

                # Limit to maximum 2 modifications per position for clean display
                visible_mods = mods[:2]  # Only show first 2 modifications

                for i, (mass, name) in enumerate(visible_mods):
                    # Get color from legend
                    if hasattr(self, 'legend'):
                        color = self.legend.get_color_for_mass(mass)
                    else:
                        color = QColor(255, 100, 100)  # Fallback

                    self.add_modification_visual(position, mass, name, color, mod_index=i)

                # If there are more than 2 modifications, show a warning
                if len(mods) > 2:
                    logger.warning(f"Position {position} has {len(mods)} modifications. Only showing first 2.")
        else:
            print("[DEBUG] No modifications to display - visual elements cleared")

        logger.debug(f"Added {len(self.modification_items)} modification visual items")

    def add_modification(self, position: int, mass: float, name: str):
        """Add a modification at the specified position"""
        if position not in self.modifications:
            self.modifications[position] = []

        if len(self.modifications[position]) >= 2:
            logger.warning(f"Cannot add modification to position {position}. Maximum 2 modifications per position.")
            return False

        self.modifications[position].append((mass, name))
        logger.debug(f"Added modification {name} (+{mass}) at position {position}")

        # Update display and emit signal
        self.update_modification_display()
        self.emit_modifications_changed()
        return True

    def emit_modifications_changed(self):
        """Emit the modifications changed signal - ENHANCED to handle empty modifications"""
        mod_list = []
        for position, mods in self.modifications.items():
            for mass, name in mods:
                mod_list.append((mass, position))

        logger.debug(f"Emitting modifications changed: {mod_list}")

        self.modificationsChanged.emit(mod_list)

        #  Ensure parent GUI updates when modifications become empty
        if not mod_list and hasattr(self.parent(), 'handle_modifications_changed'):
            print("[DEBUG] Forcing parent GUI update for empty modifications")
            self.parent().handle_modifications_changed([])

    def delete_all_modifications_at_position(self, position: int):
        """Delete all modifications at a specific position"""
        if position in self.modifications:
            del self.modifications[position]
            self.emit_modifications_changed()
            logger.debug(f"Deleted all modifications at position {position}")

    def _restore_modifications_display(self):
        """Force restore modifications display after data plotting - FIXED to prevent double execution"""
        if (hasattr(self, 'current_interactive_mods') and
            self.current_interactive_mods and
            self.modifications):
            # Clear and rebuild
            self.modifications = {}
            self._update_modifications_data(self.current_interactive_mods)
            self.update_modification_display()

        else:
            # Ensure everything is properly cleared
            self.modifications = {}
            self.current_interactive_mods = []
            self.update_modification_display()
