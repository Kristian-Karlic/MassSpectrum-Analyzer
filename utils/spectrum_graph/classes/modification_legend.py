# modification_legend.py
from typing import List, Tuple, Dict

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from utils.style.style import EditorConstants


class ModificationLegend(QWidget):
    """Legend widget to show modification colors and names with stacking info"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.modification_colors = {}  # mass -> (color, name, count)
        self.setup_ui()

    def setup_ui(self):
        """Setup the legend UI with theme-aware colors"""
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 2, 5, 2)
        self.layout.setSpacing(10)

        # Title
        title_label = QLabel("Modifications:")
        title_label.setStyleSheet(f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()}; background-color: transparent;")
        self.layout.addWidget(title_label)

        # Add info label about stacking
        info_label = QLabel("(Max 2 per position)")
        info_label.setStyleSheet(f"font-size: 10px; color: {EditorConstants.TEXT_COLOR()}; background-color: transparent; font-style: italic;")
        self.layout.addWidget(info_label)

        # PLACEHOLDER for when no modifications - ALWAYS VISIBLE
        self.no_mods_label = QLabel("None")
        self.no_mods_label.setStyleSheet(f"font-size: 10px; color: {EditorConstants.TEXT_COLOR()}; background-color: transparent; font-style: italic;")
        self.layout.addWidget(self.no_mods_label)

        # Add stretch to push everything to the left
        self.layout.addStretch()

        # ALWAYS VISIBLE - start with "None" showing
        self.setVisible(True)
        self.no_mods_label.setVisible(True)

    def clear_legend(self):
        """Clear all legend items but keep the widget visible"""
        # Remove all items except title, info label, no_mods_label and stretch
        while self.layout.count() > 4:  # Keep title, info label, no_mods_label and stretch
            item = self.layout.takeAt(3)  # Remove fourth item (first legend item after no_mods_label)
            if item.widget():
                item.widget().deleteLater()

        self.modification_colors.clear()

        # ALWAYS VISIBLE: Show "None" instead of hiding
        self.no_mods_label.setVisible(True)
        self.setVisible(True)

    def update_legend(self, modifications: Dict[int, List[Tuple[float, str]]], nl_symbol_entries: list = None):
        """Update the legend based on current modifications with stacking info - FIXED for empty modifications"""

        # Clear existing legend items
        while self.layout.count() > 4:  # Keep title, info label, no_mods_label and stretch
            item = self.layout.takeAt(3)
            if item.widget():
                item.widget().deleteLater()

        self.modification_colors.clear()

        if not modifications:
            # No modifications - show "None" and ensure it's visible
            self.no_mods_label.setVisible(True)
            self.setVisible(True)
            return

        # Hide "None" label when we have modifications
        self.no_mods_label.setVisible(False)

        # Count modifications by mass and track stacking info
        mass_counts = {}
        mass_names = {}
        stacked_positions = []

        for position, mods in modifications.items():
            if len(mods) > 1:
                stacked_positions.append(position)

            for mass, name in mods:
                mass_key = round(mass, 3)  # Round to avoid floating point issues
                if mass_key not in mass_counts:
                    mass_counts[mass_key] = 0
                    mass_names[mass_key] = name
                mass_counts[mass_key] += 1

        if not mass_counts:
            # Fallback to showing "None" if somehow we got here with empty mass_counts
            self.no_mods_label.setVisible(True)
            self.setVisible(True)
            return

        # Generate colors for each unique mass
        colors = self.generate_colors(len(mass_counts))

        # Create legend items
        for i, (mass, count) in enumerate(sorted(mass_counts.items())):
            color = colors[i]
            name = mass_names[mass]

            # Store color mapping
            self.modification_colors[mass] = (color, name, count)

            # Create legend item
            legend_item = self.create_legend_item(color, name, mass, count)

            # Insert before the stretch (which is always last)
            self.layout.insertWidget(self.layout.count() - 1, legend_item)

        # Add stacking info if there are stacked positions
        if stacked_positions:
            stacking_info = QLabel(f"Stacked at: {', '.join(map(str, stacked_positions))}")
            stacking_info.setStyleSheet("font-size: 10px; color: #888; background-color: transparent;")
            self.layout.insertWidget(self.layout.count() - 1, stacking_info)

        # NL / labile / remainder symbol legend entries
        if nl_symbol_entries:
            sep = QLabel("|")
            sep.setStyleSheet(f"color: {EditorConstants.DISABLED_COLOR()}; background-color: transparent;")
            self.layout.insertWidget(self.layout.count() - 1, sep)
            for symbol, label, mass_da, mod_name in nl_symbol_entries:
                sign = "+" if mass_da >= 0 else ""
                text = f"{symbol} = {sign}{mass_da:.3f} Da  ({mod_name}, {label})"
                sym_label = QLabel(text)
                sym_label.setStyleSheet(
                    f"color: {EditorConstants.TEXT_COLOR()}; font-size: 11px; "
                    f"font-family: monospace; background-color: transparent;"
                )
                self.layout.insertWidget(self.layout.count() - 1, sym_label)

        # Always visible
        self.setVisible(True)

    def generate_colors(self, count: int) -> List[QColor]:
        """Generate distinct colors for modifications"""
        if count == 0:
            return []
        # Predefined distinct colors
        base_colors = [
            QColor(255, 100, 100),  # Red
            QColor(100, 150, 255),  # Blue
            QColor(100, 200, 100),  # Green
            QColor(255, 150, 100),  # Orange
            QColor(200, 100, 255),  # Purple
            QColor(255, 200, 100),  # Yellow
            QColor(100, 255, 200),  # Cyan
            QColor(255, 100, 200),  # Pink
            QColor(150, 255, 100),  # Lime
            QColor(100, 200, 255),  # Sky Blue
        ]
        colors = []
        for i in range(count):
            if i < len(base_colors):
                colors.append(base_colors[i])
            else:
                hue = (i * 137) % 360  # Use golden angle for good distribution
                color = QColor()
                color.setHsv(hue, 200, 200)
                colors.append(color)

        return colors

    def create_legend_item(self, color: QColor, name: str, mass: float, count: int) -> QWidget:
        """Create a single legend item"""
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(5)

        # Color box
        color_label = QLabel()
        color_label.setFixedSize(12, 12)
        color_label.setStyleSheet(f"""
            background-color: rgb({color.red()}, {color.green()}, {color.blue()});
            border: 1px solid {EditorConstants.TEXT_COLOR()};
        """)
        item_layout.addWidget(color_label)

        # Text label
        if count > 1:
            text = f"{name} (×{count})"
        else:
            text = name

        text_label = QLabel(text)
        text_label.setStyleSheet(f"color: {EditorConstants.TEXT_COLOR()}; font-size: 11px;")
        item_layout.addWidget(text_label)

        return item_widget

    def get_color_for_mass(self, mass: float) -> QColor:
        """Get the assigned color for a specific mass"""
        mass_key = round(mass, 3)
        if mass_key in self.modification_colors:
            return self.modification_colors[mass_key][0]
        # Fallback color
        return QColor(128, 128, 128)
