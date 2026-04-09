import re
import os
import logging
import numpy as np
import traceback
from datetime import datetime
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, 
    QScrollArea, QLineEdit, QMessageBox, QMenu,QStackedWidget,QDialog,
    QFileDialog,QProgressDialog, QCheckBox
)
from utils.utility_classes.htmlformating import HTMLFormatter
import pandas as pd
from PyQt6.QtCore import Qt,QSettings
from PyQt6.QtGui import QAction
from utils.style.style import EditorConstants, StyleSheet
from utils.utility_classes.drag_and_drop_box import DropZoneWidget
from utils.tables.psm_summary_widget import DraggablePSMSummaryWidget
from utils.peak_matching.peptide_fragmentation import calculate_fragment_ions, match_fragment_ions
import matplotlib.colors as mcolors
from utils.utilities import DataGatherer

logger = logging.getLogger(__name__)

class FragmentationTabManager:
    def __init__(self, main_app):
        self.main_app = main_app
        
        # Initialize fragmentation-specific attributes
        self.comparison_groups = {}
        self.max_groups = 6
        self.last_comparison_data = None
        self.last_selected_ions = None
        
        # Available colors for groups
        self.available_colors = [
            EditorConstants.PRIMARY_BLUE(),
            "#E74C3C",  # Red
            "#F39C12",  # Orange
            "#27AE60",  # Green
            "#9B59B6",  # Purple
            "#34495E"   # Dark Blue-Gray
        ]

    @staticmethod
    def _apply_theme_to_axes(ax):
        """Apply theme-aware styling to a matplotlib axes object."""
        ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
        ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which='both')
        for spine in ax.spines.values():
            spine.set_color(EditorConstants.TEXT_COLOR())
        ax.xaxis.label.set_color(EditorConstants.TEXT_COLOR())
        ax.yaxis.label.set_color(EditorConstants.TEXT_COLOR())
        ax.title.set_color(EditorConstants.TEXT_COLOR())

    @staticmethod
    def _get_group_name_style(color):
        """Return stylesheet for a group name QLineEdit."""
        return f"""
            QLineEdit {{
                {EditorConstants.get_font_string("bold")}
                font-size: 11px;
                color: {color};
                background-color: transparent;
                border: 1px solid {color};
                border-radius: 3px;
                padding: 2px 4px;
            }}
            QLineEdit:focus {{
                border: 2px solid {color};
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
        """

    @staticmethod
    def _get_drop_zone_style():
        """Return stylesheet for a group drop zone QListWidget."""
        return f"""
            QListWidget {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border: 2px dashed {EditorConstants.GRAY_300()};
                border-radius: 8px;
                padding: 5px;
                selection-background-color: transparent;
            }}
            QListWidget::item {{
                background-color: {EditorConstants.GRAY_50()};
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 4px;
                padding: 4px;
                margin: 2px;
            }}
            QListWidget::item:hover {{
                background-color: {EditorConstants.GRAY_100()};
                border-color: {EditorConstants.GRAY_300()};
            }}
        """

    @staticmethod
    def _get_scroll_area_style():
        """Return stylesheet for the groups scroll area."""
        return f"""
            QScrollArea {{
                border: 1px solid {EditorConstants.GRAY_200()};
                border-radius: 4px;
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            {EditorConstants.get_scrollbar_style()}
        """
    
    def setup_fragmentation_analysis_tab(self):
        """Setup the fragmentation analysis tab with dynamic group management"""
        frag_tab = QWidget()
        frag_layout = QVBoxLayout(frag_tab)
        frag_layout.setContentsMargins(0, 0, 0, 0)
        frag_layout.setSpacing(0)
        
        ################################################################
        # TOP SECTION - Plot and Comparison Groups
        ################################################################
        
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        
        # Create center widget (plot area)
        center_widget = self._create_center_plot_widget()
        
        # Create right widget (comparison groups)
        right_widget = self._create_right_groups_widget()
        
        # Add to top section layout
        top_layout.addWidget(center_widget, 1)
        top_layout.addWidget(right_widget, 0)
        
        ################################################################
        # BOTTOM SECTION - Draggable PSM Summary Widget (HEIGHT LIMITED)
        ################################################################
        
        self.main_app.frag_psm_summary_widget = DraggablePSMSummaryWidget()
        self.main_app.frag_psm_summary_widget.setMinimumHeight(50)
        
        # Add sections to fragmentation analysis tab with stretch factors
        frag_layout.addWidget(top_section, 3)  # Give more space to the plots
        frag_layout.addWidget(self.main_app.frag_psm_summary_widget, 1)  # Limit table space
        
        # Add tab to main tab widget
        self.main_app.main_tab_widget.addTab(frag_tab, "Fragmentation Analysis")
        
        # Start with Group A
        self.add_comparison_group()
        
        logger.debug("Fragmentation analysis tab setup completed")
        
        return frag_tab
        
    def _create_center_plot_widget(self):
        """Create the center plot area widget - SIMPLIFIED with buttons moved to right panel"""
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(5, 5, 5, 5)
        center_layout.setSpacing(5)
        
        self.plot_stack = QStackedWidget()
        
        # Index 0: Matplotlib plots (bar charts, isotope ratios)
        matplotlib_widget = QWidget()
        matplotlib_layout = QVBoxLayout(matplotlib_widget)
        matplotlib_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create figure with theme-aware colors
        self.comparison_figure = Figure(
            figsize=(10, 6),
            facecolor=EditorConstants.PLOT_BACKGROUND(),
            edgecolor=EditorConstants.PLOT_FOREGROUND()
        )
        self.comparison_canvas = FigureCanvas(self.comparison_figure)
        matplotlib_layout.addWidget(self.comparison_canvas)
        
        self.plot_stack.addWidget(matplotlib_widget)
        
        # Start with matplotlib view
        self.plot_stack.setCurrentIndex(0)
        center_layout.addWidget(self.plot_stack)

        return center_widget
    
    def on_plot_type_changed(self, plot_type_text):
        """Handle plot type dropdown change"""
        logger.debug(f"Plot type changed to: {plot_type_text}")
        
        is_isotope_plot = plot_type_text == "Isotope Ratio Plot"
        
        # Show/hide isotope ratio specific controls
        if hasattr(self, 'charge_widget'):
            self.charge_widget.setVisible(is_isotope_plot)
        if hasattr(self, 'isotope_options_widget'):
            self.isotope_options_widget.setVisible(is_isotope_plot)
        
        # Clear existing plots
        if hasattr(self, 'comparison_figure'):
            self.comparison_figure.clear()
            self.comparison_canvas.draw()
        
        # Always use matplotlib view (only view now)
        if hasattr(self, 'plot_stack'):
            self.plot_stack.setCurrentIndex(0)
            if is_isotope_plot:
                self.main_app.show_toast_message("Isotope Ratio Plot: Select isotopes, charge state and click Compare")
            else:
                self.main_app.show_toast_message("Ion Count Bar Chart: Click Compare to generate chart")
        
    def _create_right_groups_widget(self):
        """Create the right widget for dynamic comparison groups - WITH CONTROL BUTTONS"""
        right_widget = QWidget()
        right_widget.setMaximumWidth(350)
        right_widget.setMinimumWidth(350)
        right_main_layout = QVBoxLayout(right_widget)
        right_main_layout.setContentsMargins(5, 5, 5, 5)
        right_main_layout.setSpacing(5)
        
        # Store reference for theme updates
        self.right_groups_widget = right_widget
        
        # MOVED: Control buttons section at the top
        control_section = self._create_control_buttons_section()
        right_main_layout.addWidget(control_section)
        
        # Add separator
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {EditorConstants.GRAY_300()};")
        right_main_layout.addWidget(separator)
        
        # Group management buttons
        group_buttons_layout = QHBoxLayout()
        
        self.add_group_button = QPushButton("Add Group")
        self.add_group_button.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        self.add_group_button.clicked.connect(self.add_comparison_group)
        group_buttons_layout.addWidget(self.add_group_button)
        
        self.remove_group_button = QPushButton("Remove Group")
        self.remove_group_button.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        self.remove_group_button.clicked.connect(self.remove_comparison_group)
        self.remove_group_button.setEnabled(False)  # Disabled when only 1 group
        group_buttons_layout.addWidget(self.remove_group_button)
        
        group_buttons_layout.addStretch()
        right_main_layout.addLayout(group_buttons_layout)
        
        # SCROLLABLE AREA for groups
        groups_scroll_area = QScrollArea()
        groups_scroll_area.setWidgetResizable(True)
        groups_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        groups_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        groups_scroll_area.setMinimumHeight(200)
        groups_scroll_area.setStyleSheet(self._get_scroll_area_style())
        
        # Store reference for theme updates
        self.groups_scroll_area = groups_scroll_area
        
        # Widget to contain all the groups (this goes inside the scroll area)
        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(5, 5, 5, 5)
        self.groups_layout.setSpacing(8)
        
        # Add stretch to push groups to top of scroll area
        self.groups_layout.addStretch()
        
        # Set the groups container as the scroll area widget
        groups_scroll_area.setWidget(self.groups_container)
        
        # Add scroll area to the right main layout
        right_main_layout.addWidget(groups_scroll_area)
        
        return right_widget
    
    
    def _create_control_buttons_section(self):
        """Create the control buttons section for the right panel"""
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 0, 0, 5)
        control_layout.setSpacing(8)
        
        # Plot Type Selection
        plot_type_layout = QHBoxLayout()
        plot_type_label = QLabel("Plot Type:")
        plot_type_label.setStyleSheet(f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()};")
        plot_type_layout.addWidget(plot_type_label)
        
        self.plot_type_combo = QComboBox()
        self.plot_type_combo.addItems([
            "Ion Count Bar Chart",
            "Isotope Ratio Plot"
        ])
        self.plot_type_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.plot_type_combo.setToolTip("Select the type of plot to generate")
        self.plot_type_combo.currentTextChanged.connect(self.on_plot_type_changed)
        plot_type_layout.addWidget(self.plot_type_combo)
        
        control_layout.addLayout(plot_type_layout)
        
        # Charge Selection (only shown for Isotope Ratio Plot)
        charge_layout = QHBoxLayout()
        charge_label = QLabel("Charge State:")
        charge_label.setStyleSheet(f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()};")
        charge_layout.addWidget(charge_label)
        
        self.charge_combo = QComboBox()
        self.charge_combo.addItems(["All", "1", "2", "3", "4", "5"])
        self.charge_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.charge_combo.setToolTip("Select charge state to filter isotope ratio analysis")
        charge_layout.addWidget(self.charge_combo)
        
        self.charge_widget = QWidget()
        self.charge_widget.setLayout(charge_layout)
        self.charge_widget.setVisible(False)  # Hidden by default
        
        control_layout.addWidget(self.charge_widget)
        
        # Isotope Selection Options (only shown for Isotope Ratio Plot)
        isotope_options_layout = QVBoxLayout()
        isotope_options_layout.setSpacing(4)
        
        # Isotope numerator/denominator selection row
        isotope_select_layout = QHBoxLayout()
        isotope_select_layout.setSpacing(4)
        
        # Numerator isotope
        numerator_label = QLabel("Ratio:")
        numerator_label.setStyleSheet(f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()}; font-size: 10px;")
        isotope_select_layout.addWidget(numerator_label)
        
        self.isotope_numerator_combo = QComboBox()
        self.isotope_numerator_combo.addItems(["-1", "0", "1", "2", "3", "4"])
        self.isotope_numerator_combo.setCurrentText("1")  # Default numerator is isotope 1
        self.isotope_numerator_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.isotope_numerator_combo.setToolTip("Select isotope for numerator")
        self.isotope_numerator_combo.setMaximumWidth(50)
        isotope_select_layout.addWidget(self.isotope_numerator_combo)
        
        slash_label = QLabel("/")
        slash_label.setStyleSheet(f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()}; font-size: 12px;")
        isotope_select_layout.addWidget(slash_label)
        
        # Denominator isotope
        self.isotope_denominator_combo = QComboBox()
        self.isotope_denominator_combo.addItems(["-1", "0", "1", "2", "3", "4"])
        self.isotope_denominator_combo.setCurrentText("0")  # Default denominator is isotope 0
        self.isotope_denominator_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.isotope_denominator_combo.setToolTip("Select isotope for denominator")
        self.isotope_denominator_combo.setMaximumWidth(50)
        isotope_select_layout.addWidget(self.isotope_denominator_combo)
        
        isotope_select_layout.addStretch()
        isotope_options_layout.addLayout(isotope_select_layout)
        
        # Zero denominator handling checkbox (complete hydrogen transfer)
        self.zero_denom_checkbox = QCheckBox("Show complete transfer (ratio=5)")
        self.zero_denom_checkbox.setStyleSheet(f"color: {EditorConstants.TEXT_COLOR()}; font-size: 10px;")
        self.zero_denom_checkbox.setToolTip("When denominator intensity is 0 (e.g., no -1 isotope), display as complete hydrogen transfer at ratio = 5")
        self.zero_denom_checkbox.setChecked(False)
        isotope_options_layout.addWidget(self.zero_denom_checkbox)
        
        self.isotope_options_widget = QWidget()
        self.isotope_options_widget.setLayout(isotope_options_layout)
        self.isotope_options_widget.setVisible(False)  # Hidden by default
        
        control_layout.addWidget(self.isotope_options_widget)
        
        # Action buttons - arranged in a grid for better space usage
        buttons_grid = QVBoxLayout()
        buttons_grid.setSpacing(5)
        
        # Row 1: Export and Compare buttons
        row1_layout = QHBoxLayout()
        
        export_frag_button = QPushButton("Export Analysis")
        export_frag_button.setStyleSheet(EditorConstants.get_pushbutton_style("info"))
        export_frag_button.setToolTip("Export detailed fragmentation analysis for all peptides")
        export_frag_button.clicked.connect(self.export_fragmentation_analysis)
        row1_layout.addWidget(export_frag_button)
        
        compare_button = QPushButton("Compare")
        compare_button.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        compare_button.clicked.connect(self.update_comparison_plot)
        row1_layout.addWidget(compare_button)
        
        buttons_grid.addLayout(row1_layout)
        
        # Row 2: Clear and Save buttons
        row2_layout = QHBoxLayout()
        
        clear_button = QPushButton("Clear Groups")
        clear_button.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        clear_button.clicked.connect(self.clear_comparison_groups)
        row2_layout.addWidget(clear_button)
        
        save_button = QPushButton("Save Plot/Data")
        save_button.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        save_button.clicked.connect(self.show_save_options)
        row2_layout.addWidget(save_button)
        
        buttons_grid.addLayout(row2_layout)
        
        control_layout.addLayout(buttons_grid)
        
        return control_widget
    
    def add_comparison_group(self):
        """Add a new comparison group"""
        if len(self.comparison_groups) >= self.max_groups:
            QMessageBox.information(
                self.main_app, 
                "Maximum Groups Reached", 
                f"Maximum of {self.max_groups} groups allowed."
            )
            return
        
        # Generate group identifier - find next available letter
        group_letters = ['A', 'B', 'C', 'D', 'E', 'F']
        used_letters = {info['group_letter'] for info in self.comparison_groups.values()}
        available_letter = None
        for letter in group_letters:
            if letter not in used_letters:
                available_letter = letter
                break
        if available_letter is None:
            return  # shouldn't happen if max_groups check passed

        group_id = f"Group_{available_letter}"
        default_name = f"Group {available_letter}"
        letter_index = group_letters.index(available_letter)
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
        group_name_input.textChanged.connect(lambda text, gid=group_id: self._update_group_name(gid, text))
        
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
            'widget': group_widget,
            'color': color,
            'name_input': group_name_input,
            'name_widget': group_name_widget,
            'current_name': default_name,
            'original_key': group_id,
            'group_letter': available_letter
        }
        
        # Update button states
        self._update_group_button_states()

        self.main_app.show_toast_message(f"Added {default_name}")

    def remove_comparison_group(self):
        """Remove the last comparison group"""
        if len(self.comparison_groups) <= 1:
            QMessageBox.information(
                self.main_app, 
                "Cannot Remove", 
                "At least one group must remain."
            )
            return
        
        # Find the group with the highest counter number (most recently added)
        group_to_remove = None
        highest_counter = -1
        
        for group_id, group_info in self.comparison_groups.items():
            # Extract counter from group letter
            letter = group_info['group_letter']
            counter = ord(letter) - ord('A')
            if counter > highest_counter:
                highest_counter = counter
                group_to_remove = group_id
        
        if group_to_remove:
            group_info = self.comparison_groups[group_to_remove]
            group_name = group_info['current_name']
            
            # Confirm removal if group has peptides
            if group_info['widget'].count() > 0:
                reply = QMessageBox.question(
                    self.main_app,
                    "Remove Group",
                    f"'{group_name}' contains {group_info['widget'].count()} peptide(s). "
                    f"Are you sure you want to remove it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # Remove widgets from layout
            self.groups_layout.removeWidget(group_info['name_widget'])
            self.groups_layout.removeWidget(group_info['widget'])
            
            # Delete widgets
            group_info['name_widget'].deleteLater()
            group_info['widget'].deleteLater()
            
            # Remove from groups dictionary
            del self.comparison_groups[group_to_remove]

            # Update button states
            self._update_group_button_states()
            
            self.main_app.show_toast_message(f"Removed {group_name}")
            logger.debug(f"Removed {group_to_remove}. Total groups: {len(self.comparison_groups)}")
    
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
        
        total_peptides = sum(group_info['widget'].count() for group_info in self.comparison_groups.values())
        
        if total_peptides == 0:
            self.main_app.show_toast_message("No peptides to clear")
            return
        
        # Confirm clearing
        reply = QMessageBox.question(
            self.main_app,
            "Clear All Groups",
            f"This will remove all {total_peptides} peptides from all groups. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Clear all groups
        for group_info in self.comparison_groups.values():
            group_info['widget'].clear()
        
        # Clear the comparison plot
        if hasattr(self, 'comparison_figure'):
            self.comparison_figure.clear()
            self.comparison_canvas.draw()
        
        self.main_app.show_toast_message(f"Cleared {total_peptides} peptides from all groups")
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
            self.show_comparison_message("Please select at least one ion type in the left panel to analyze")
            return
        
        # Check how many groups have data
        groups_with_data = []
        for group_id, group_info in self.comparison_groups.items():
            peptide_count = group_info['widget'].count()
            logger.debug(f"Group {group_id} has {peptide_count} peptides")
            if peptide_count > 0:
                groups_with_data.append(group_id)
        
        logger.debug(f"Groups with data: {groups_with_data}")
        
        if len(groups_with_data) < 1:
            self.show_comparison_message("Please add peptides to at least one group for analysis")
            return
        
        # Use matplotlib view
        self.plot_stack.setCurrentIndex(0)
        
        if current_plot_type == "Isotope Ratio Plot":
            logger.debug(f"Creating isotope ratio plot")
            self.create_isotope_ratio_plot(selected_ions)
        else:  # Ion Count Bar Chart
            logger.debug(f"Creating bar chart plot for {len(groups_with_data)} group(s)")
            self.update_bar_chart_plot(selected_ions)
    
    def get_selected_ion_types_for_comparison(self):
        """Get selected ion types for comparison - FIXED to properly access main app"""
        selected_ions = []
        
        # Get reference to main app
        main_app = self.main_app
        
        logger.debug(f"Getting selected ion types from main app: {type(main_app)}")
        
        # Normal ion types
        if hasattr(main_app, 'normal_ion_checkboxes'):
            for ion_type, checkbox in main_app.normal_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append(ion_type)
                    logger.debug(f"Added normal ion: {ion_type}")
        else:
            logger.debug(f"No normal_ion_checkboxes found on main app")

        # Neutral loss ion types
        if hasattr(main_app, 'neutral_ion_checkboxes'):
            for ion_type, checkbox in main_app.neutral_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append(ion_type)
                    logger.debug(f"Added neutral loss ion: {ion_type}")
        else:
            logger.debug(f"No neutral_ion_checkboxes found on main app")

        # Internal ion types
        if hasattr(main_app, 'internal_ion_checkboxes'):
            for ion_type, checkbox in main_app.internal_ion_checkboxes.items():
                if checkbox.isChecked():
                    selected_ions.append('int-' + ion_type)
                    logger.debug(f"Added internal ion: int-{ion_type}")
        else:
            logger.debug(f"No internal_ion_checkboxes found on main app")
        
        # Custom ion series
        if hasattr(main_app, 'selected_custom_ions_data'):
            for custom_ion in main_app.selected_custom_ions_data:
                series_name = custom_ion.get('Series Name', '')
                if series_name:
                    selected_ions.append(series_name)
                    logger.debug(f"Added custom ion: {series_name}")
        else:
            logger.debug(f"No selected_custom_ions_data found on main app")
        
        logger.debug(f"Total selected ions for comparison: {selected_ions}")
        return selected_ions


    def get_peptides_from_group(self, group_widget):
        """Extract peptide data from a group widget - ENHANCED to ensure consistent data format"""
        peptides = []
        for i in range(group_widget.count()):
            item = group_widget.item(i)
            if hasattr(item, 'peptide_data') and item.peptide_data:
                # Ensure the peptide data has the required fields for fragmentation
                peptide_data = item.peptide_data.copy()
                
                # Map field names to ensure consistency with fragmentation system
                if 'Peptide' in peptide_data and 'peptide' not in peptide_data:
                    peptide_data['peptide'] = peptide_data['Peptide']
                
                if 'Charge' in peptide_data and 'charge' not in peptide_data:
                    peptide_data['charge'] = peptide_data['Charge']
                
                if 'Parsed Modifications' in peptide_data and 'parsed_modifications' not in peptide_data:
                    peptide_data['parsed_modifications'] = peptide_data['Parsed Modifications']
                
                # Ensure we have row_data for spectral data retrieval
                if 'row_data' not in peptide_data:
                    # Create row_data from available fields
                    peptide_data['row_data'] = {
                        'spectrum_file_path': peptide_data.get('spectrum_file_path', ''),
                        'index': peptide_data.get('index', ''),
                        'Peptide': peptide_data.get('Peptide', ''),
                        'Charge': peptide_data.get('Charge', ''),
                        'Spectrum file': peptide_data.get('Spectrum file', '')
                    }
                
                peptides.append(peptide_data)
                logger.debug(f"Retrieved peptide data: {peptide_data.get('Peptide', 'Unknown')}")
            else:
                logger.warning(f"No peptide_data found for item at index {i}")
        
        logger.debug(f"Extracted {len(peptides)} peptides from group")
        return peptides
    
    def show_save_options(self):
        """Show save options dialog for comparison data"""
        if not hasattr(self, 'comparison_figure') or not self.comparison_figure.get_axes():
            QMessageBox.warning(self.main_app, "No Graph", "No comparison graph to save. Please create a comparison first.")
            return
        
        # Create a simple dialog with save options
        dialog = QDialog(self.main_app)
        dialog.setWindowTitle("Save Comparison")
        dialog.resize(300, 200)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title_label = QLabel("Choose what to save:")
        title_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {EditorConstants.TEXT_COLOR()};")
        layout.addWidget(title_label)
        
        # Define save options with their export types
        save_options = [
            ("Save Graph as SVG", "primary", "svg"),
            ("Save Graph as PNG", "primary", "png"),
            ("Save Raw Data", "secondary", "xlsx"),
            ("Save Graph + Raw Data", "success", "combined")
        ]
        
        # Create buttons dynamically
        for text, style, export_type in save_options:
            btn = QPushButton(text)
            btn.setStyleSheet(EditorConstants.get_pushbutton_style(style))
            btn.clicked.connect(lambda checked, et=export_type: (self.export_comparison_data(et), dialog.accept()))
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
            self.comparison_groups[group_id]['current_name'] = new_name if new_name.strip() else self.comparison_groups[group_id]['original_key']
            
            # Update the drop zone's display if needed (for internal tracking)
            group_widget = self.comparison_groups[group_id]['widget']
            if hasattr(group_widget, 'group_name'):
                group_widget.group_name = self.comparison_groups[group_id]['current_name']
    
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
        remove_action.triggered.connect(lambda: self._remove_peptide_from_group(group_widget, item_index))
        menu.addAction(remove_action)
        
        # Show the menu
        menu.exec(group_widget.mapToGlobal(position))
    
    def _remove_peptide_from_group(self, group_widget, item_index):
        """Remove a specific peptide from a group"""
        if 0 <= item_index < group_widget.count():
            item = group_widget.takeItem(item_index)
            if item:
                logger.debug(f"Removed peptide from group")
                # Update placeholder if group is now empty
                if group_widget.count() == 0:
                    group_widget.update_placeholder()

    def create_multi_group_bar_chart_with_custom_names(self, all_group_counts, selected_ions, group_colors, custom_names):
        """Create a multi-group bar chart with custom group names - ENHANCED for single group support"""

        
        logger.debug(f"Creating bar chart for {len(custom_names)} group(s): {custom_names}")
        
        # Validate that we have data
        if not all_group_counts or not custom_names or not group_colors:
            self.show_comparison_message("No groups with data found for analysis")
            return
        
        # Ensure all arrays have the same length
        n_groups = len(custom_names)
        if len(all_group_counts) != n_groups or len(group_colors) != n_groups:
            logger.error(f"Mismatch in group data lengths: counts={len(all_group_counts)}, names={len(custom_names)}, colors={len(group_colors)}")
            self.show_comparison_message("Error: Inconsistent group data")
            return
        
        self.comparison_figure.clear()
        
        # Filter out ion types with zero counts in all groups
        active_ions = []
        for ion_type in selected_ions:
            has_data = False
            for group_counts in all_group_counts.values():
                if group_counts.get(ion_type) and np.mean(group_counts[ion_type]) > 0:
                    has_data = True
                    break
            if has_data:
                active_ions.append(ion_type)
        
        if not active_ions:
            self.show_comparison_message("No ion counts found for selected ion types")
            return
        
        ax = self.comparison_figure.add_subplot(111)

        # Apply theme-aware styling to axes
        self._apply_theme_to_axes(ax)
        
        # Use the actual groups that have data
        original_keys = list(all_group_counts.keys())
        n_ions = len(active_ions)
        
        logger.debug(f"Plotting {n_groups} group(s) with {n_ions} ion types")
        logger.debug(f"Groups: {original_keys}")
        logger.debug(f"Custom names: {custom_names}")
        
        # Calculate means for each group and ion type
        data_matrix = np.zeros((n_groups, n_ions))
        error_matrix = np.zeros((n_groups, n_ions))
        
        for i, original_key in enumerate(original_keys):
            if original_key not in all_group_counts:
                logger.error(f"Missing group data for {original_key}")
                continue
                
            for j, ion_type in enumerate(active_ions):
                values = all_group_counts[original_key].get(ion_type, [])
                if values:
                    data_matrix[i, j] = np.mean(values)
                    error_matrix[i, j] = np.std(values) / np.sqrt(len(values)) if len(values) > 1 else 0
        
        # Create grouped bar chart - ADAPTED for single or multiple groups
        x = np.arange(n_ions)  # Ion type positions
        
        if n_groups == 1:
            # Single group - wider bars, centered
            width = 0.6
            bars = ax.bar(x, data_matrix[0], width, 
                        label=custom_names[0], color=group_colors[0], alpha=0.8,
                        yerr=error_matrix[0], capsize=3)
            
            # Add value labels on bars
            for j, (bar, value) in enumerate(zip(bars, data_matrix[0])):
                if value > 0:
                    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + error_matrix[0, j] + 0.1,
                        f'{value:.1f}', ha='center', va='bottom', fontsize=10, fontweight='bold')
        else:
            # Multiple groups - grouped bars
            width = 0.8 / n_groups  # Width of bars
            
            # Plot bars for each group
            for i in range(n_groups):
                if i >= len(custom_names) or i >= len(group_colors):
                    logger.error(f"Index {i} out of range for names or colors")
                    continue
                    
                custom_name = custom_names[i]
                color = group_colors[i]
                
                offset = (i - n_groups/2 + 0.5) * width
                bars = ax.bar(x + offset, data_matrix[i], width, 
                            label=custom_name, color=color, alpha=0.8,
                            yerr=error_matrix[i], capsize=3)
                
                # Add value labels on bars
                for j, (bar, value) in enumerate(zip(bars, data_matrix[i])):
                    if value > 0:
                        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + error_matrix[i, j] + 0.1,
                            f'{value:.1f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        # Customize plot based on number of groups
        ax.set_xlabel('Ion Type', fontsize=12, fontweight='bold')
        ax.set_ylabel('Ion Count', fontsize=12, fontweight='bold')
        
        if n_groups == 1:
            ax.set_title(f'Fragmentation Pattern Analysis - {custom_names[0]}\n({n_ions} ion types with matches)', 
                        fontsize=14, fontweight='bold')
        else:
            ax.set_title(f'Ion Count Comparison Across {n_groups} Groups\n({n_ions} ion types with matches)', 
                        fontsize=14, fontweight='bold')
        
        ax.set_xticks(x)
        ax.set_xticklabels(active_ions, rotation=45 if n_ions > 6 else 0)
        
        # Only show legend if more than one group
        if n_groups > 1:
            ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        ax.grid(True, alpha=0.3, axis='y')
        
        # Adjust layout to prevent legend cutoff
        self.comparison_figure.tight_layout()
        self.comparison_canvas.draw()

    def show_comparison_message(self, message):
        """Show a message in the comparison plot area"""
        if hasattr(self, 'comparison_figure'):
            self.comparison_figure.clear()
            ax = self.comparison_figure.add_subplot(111)
            ax.text(0.5, 0.5, message, 
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=14, 
                bbox=dict(boxstyle="round,pad=0.5", facecolor=EditorConstants.GRAY_200(), alpha=0.8))
            ax.set_xticks([])
            ax.set_yticks([])
            self.comparison_canvas.draw()
                
            
    def export_comparison_data(self, export_type="svg"):
        """Enhanced export method for integration"""
        
        current_index = self.plot_stack.currentIndex()
        current_plot_type = self.plot_type_combo.currentText()
        
        # Validation for graph export
        if export_type in ["svg", "png"]:
            if not hasattr(self, 'comparison_figure') or not self.comparison_figure.get_axes():
                QMessageBox.warning(self.main_app, "No Graph", "No comparison graph to export. Please create a comparison first.")
                return
        
        # Get filename
        if export_type == "svg":
            default_filename = self._get_comparison_default_filename("svg")
            file_filter = "SVG files (*.svg);;All files (*.*)"
            title = "Export Comparison Graph as SVG"
        elif export_type == "png":
            default_filename = self._get_comparison_default_filename("png") 
            file_filter = "PNG files (*.png);;All files (*.*)"
            title = "Export Comparison Graph as PNG"
        else:
            # Data export
            if not hasattr(self, 'last_comparison_data') or self.last_comparison_data is None:
                QMessageBox.warning(self.main_app, "No Data", "No comparison data to export. Please create a comparison first.")
                return
            default_filename = self._get_comparison_default_filename("xlsx")
            file_filter = "Excel files (*.xlsx);;CSV files (*.csv);;All files (*.*)"
            title = "Export Comparison Raw Data"
        
        filename = self._get_export_filename(title, default_filename, file_filter)
        
        if not filename:
            return

        try:
            if export_type in ["svg", "png"]:
                # Graph export - only matplotlib
                self.comparison_figure.savefig(filename, format=export_type, bbox_inches='tight', dpi=300)
                QMessageBox.information(self.main_app, "Success", f"Graph exported successfully to:\n{filename}")
            elif export_type == "xlsx":
                # Data export
                self._export_comparison_data_to_file(filename)
                QMessageBox.information(self.main_app, "Success", f"Raw data exported successfully to:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self.main_app, "Error", f"Failed to export {export_type.upper()}:\n{str(e)}")
                

    def _get_export_filename(self, title, default_filename, file_filter):
        """Get export filename with remembered directory"""
        # Use QSettings to remember last directory
        settings = QSettings("YourCompany", "MassSpecAnalyzer")
        last_dir = settings.value("last_export_directory", "")
        
        if last_dir and os.path.exists(last_dir):
            full_path = os.path.join(last_dir, default_filename)
        else:
            full_path = os.path.join(os.path.expanduser("~/Documents"), default_filename)
        
        filename, _ = QFileDialog.getSaveFileName(
            self.main_app,
            title,
            full_path,
            file_filter
        )
        
        if filename:
            # Save directory for next time
            directory = os.path.dirname(filename)
            settings.setValue("last_export_directory", directory)
        
        return filename

    def _get_comparison_default_filename(self, extension):
        """Generate default filename using group data - UPDATED for new plot types"""
        # Count active groups and use their custom names
        active_groups = []
        for original_key, group_info in self.comparison_groups.items():
            if group_info['widget'].count() > 0:
                custom_name = group_info['current_name'].replace(" ", "_")
                active_groups.append(custom_name)
        
        # Determine plot type based on current dropdown selection
        if hasattr(self, 'plot_type_combo'):
            current_plot = self.plot_type_combo.currentText()
            if current_plot == "Isotope Ratio Plot":
                plot_type = "isotope_ratio"
            else: 
                plot_type = "ion_count"
        else:
            plot_type = "ion_count"
        
        if active_groups:
            groups_str = "_vs_".join(active_groups)
            base_name = f"fragmentation_{plot_type}_{groups_str}"
        else:
            base_name = f"fragmentation_{plot_type}"
        
        if extension:
            return f"{base_name}.{extension}"
        else:
            return base_name

    def _export_comparison_data_to_file(self, filename):
        """Export comparison data to Excel or CSV file"""
        
        if filename.endswith('.xlsx'):
            # Use the method that includes source rows
            self._export_comparison_data_to_file_with_source_rows(filename)
        else:
            # Export main data as CSV
            summary_data = self._create_comparison_summary_data()
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_csv(filename, index=False)

    def _export_comparison_data_to_file_with_source_rows(self, filename):
        """Export comparison data to Excel file including source PSM rows"""
        
        if filename.endswith('.xlsx'):
            # Export to Excel with multiple sheets INCLUDING source rows
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                
                # Export main data in long format
                summary_data = self._create_comparison_summary_data()
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Fragmentation_Data', index=False)
                
                # Export source PSM rows with group information
                source_rows_df = self._create_source_rows_data()
                if not source_rows_df.empty:
                    source_rows_df.to_excel(writer, sheet_name='Source_PSM_Rows', index=False)
                
                # Export peptide information for each group
                for original_key, group_data in self.last_comparison_data.items():
                    if group_data['peptides']:  # Only export if group has data
                        custom_name = self.comparison_groups[original_key]['current_name']
                        peptide_df = self._create_peptide_info_data(custom_name, group_data)
                        # Sanitize sheet name (Excel requirements)
                        sheet_name = f"{custom_name.replace(' ', '_')}_Peptides"[:31]
                        peptide_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        
                # Export metadata sheet
                metadata_df = self._create_comparison_metadata()
                metadata_df.to_excel(writer, sheet_name='Metadata', index=False)

    def _create_source_rows_data(self):
        """Create a dataframe with all source PSM rows used in the comparison"""

        source_rows = []
        
        if not hasattr(self, 'last_comparison_data') or not self.last_comparison_data:
            return pd.DataFrame()
        
        # Get the active PSM summary widget
        current_tab = self.main_app.main_tab_widget.currentIndex()
        if current_tab == 0:  # Annotation tab
            psm_widget = self.main_app.psm_summary_widget
        else:  # Fragmentation analysis tab
            psm_widget = self.main_app.frag_psm_summary_widget
        
        # Check if we have access to the details dataframe
        if not hasattr(psm_widget, 'current_details_df') or psm_widget.current_details_df.empty:
            logger.warning("No current_details_df available for source row export")
            return pd.DataFrame()
        
        details_df = psm_widget.current_details_df
        
        # Process each group to find matching rows
        for original_key, group_data in self.last_comparison_data.items():
            custom_name = self.comparison_groups[original_key]['current_name']
            
            if 'peptides' not in group_data or not group_data['peptides']:
                continue
            
            # For each peptide in this group, find the matching row in details_df
            for peptide_info in group_data['peptides']:
                try:
                    # Extract peptide information
                    if isinstance(peptide_info, dict):
                        peptide_seq = peptide_info.get('Peptide', '')
                        charge = peptide_info.get('Charge', '')
                        scan_number = str(peptide_info.get('index', ''))
                        spectrum_file = peptide_info.get('Spectrum file', '')
                        
                        # If we have valid data, try to find the matching row
                        if peptide_seq and peptide_seq != 'Unknown' and charge and charge != 'Unknown':
                            # Create a mask to find matching rows
                            mask = (
                                (details_df['Peptide'] == peptide_seq) &
                                (details_df['Charge'] == charge)
                            )
                            
                            # Add scan number if available
                            if scan_number and scan_number != 'Unknown':
                                mask = mask & (details_df['index'].astype(str) == scan_number)
                            
                            # Add spectrum file if available
                            if spectrum_file and spectrum_file != 'Unknown' and 'Spectrum file' in details_df.columns:
                                mask = mask & (details_df['Spectrum file'] == spectrum_file)
                            
                            # Find matching rows
                            matching_rows = details_df[mask]
                            
                            if len(matching_rows) > 0:
                                # Take the first matching row
                                row_data = matching_rows.iloc[0].to_dict()
                                
                                # Add group information
                                row_data['Comparison_Group'] = custom_name
                                row_data['Group_Original_Key'] = original_key
                                row_data['Export_Timestamp'] = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                source_rows.append(row_data)
                                
                except Exception as e:
                    logger.error(f"Error processing peptide info for source rows: {e}")
                    continue
        
        if source_rows:
            source_df = pd.DataFrame(source_rows)
            
            # Reorder columns to put group information first
            group_cols = ['Comparison_Group', 'Group_Original_Key', 'Export_Timestamp']
            other_cols = [col for col in source_df.columns if col not in group_cols]
            source_df = source_df[group_cols + other_cols]
            
            return source_df
        else:
            return pd.DataFrame()

    def _create_comparison_summary_data(self):
        """Create summary data for export in long format - ENHANCED to handle charge grouping and isotope ratios"""
        summary_data = []
        
        if not self.last_comparison_data:
            return summary_data
    
        # Export regular data (existing logic)
        for original_key, group_data in self.last_comparison_data.items():
            custom_name = self.comparison_groups[original_key]['current_name']
            
            if 'ion_counts' in group_data:
                for ion_type, counts in group_data['ion_counts'].items():
                    # Add each individual replicate as a separate row
                    for count_value in counts:
                        summary_data.append({
                            'Ion_Type': ion_type,
                            'Ion_Count': count_value,
                            'Group': custom_name
                        })
            
            # Handle isotope ratio data
            if 'isotope_ratios' in group_data:
                for ion_type, position_data in group_data['isotope_ratios'].items():
                    # position_data is a dict: {position: [ratio1, ratio2, ...]}
                    for position, ratios in position_data.items():
                        # Handle position as tuple (position, charge) or scalar
                        if isinstance(position, tuple) and len(position) == 2:
                            pos, charge = position
                        else:
                            pos = position
                            charge = None
                        
                        for ratio_value in ratios:
                            row_data = {
                                'Ion_Type': ion_type,
                                'Ion_Position': pos,
                                'Isotope_Ratio': ratio_value,
                                'Group': custom_name
                            }
                            if charge is not None:
                                row_data['Charge'] = charge
                            summary_data.append(row_data)
            
            # Handle zero denominator positions (complete hydrogen transfer) if present
            if 'zero_denom_positions' in group_data:
                for ion_type, zero_denom_list in group_data['zero_denom_positions'].items():
                    for zd in zero_denom_list:
                        summary_data.append({
                            'Ion_Type': ion_type,
                            'Ion_Position': zd['position'],
                            'Charge': zd['charge'],
                            'Isotope_Ratio': 5.0,  # Complete transfer ratio
                            'Complete_Transfer': True,
                            'Numerator_Intensity': zd['numerator_intensity'],
                            'Group': custom_name
                        })
        
        return summary_data

    def _create_peptide_info_data(self, group_name, group_data):
        """Create peptide information data for a specific group"""
        
        peptide_data = []
        
        if 'peptides' in group_data:
            for i, peptide_info in enumerate(group_data['peptides']):
                if isinstance(peptide_info, dict):
                    # Extract the actual values
                    peptide_seq = peptide_info.get('Peptide', 'Unknown')
                    charge = peptide_info.get('Charge', 'Unknown')
                    spectrum_file = peptide_info.get('Spectrum file', 'Unknown')
                    scan = peptide_info.get('index', 'Unknown')
                    modifications = peptide_info.get('Parsed Modifications', [])
                    
                    # Convert modifications to readable string
                    if isinstance(modifications, list) and modifications:
                        mod_str = str(modifications)
                    else:
                        mod_str = "None"
                    
                    peptide_data.append({
                        'Group': group_name,
                        'Replicate_Index': i + 1,
                        'Peptide': peptide_seq,
                        'Modifications': mod_str,
                        'Charge': charge,
                        'File': spectrum_file,
                        'Scan': scan
                    })
                else:
                    # Fallback for non-dictionary items
                    peptide_data.append({
                        'Group': group_name,
                        'Replicate_Index': i + 1,
                        'Peptide': str(peptide_info) if peptide_info else 'Unknown',
                        'Modifications': 'Unknown',
                        'Charge': 'Unknown',
                        'File': 'Unknown',
                        'Scan': 'Unknown'
                    })
        
        return pd.DataFrame(peptide_data)

    def _create_comparison_metadata(self):
        """Create metadata for the comparison export"""
        
        # Get current plot type from combo box
        current_plot_type = self.plot_type_combo.currentText() if hasattr(self, 'plot_type_combo') else 'Unknown'

        metadata = [
            {'Parameter': 'Export_Date', 'Value': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
            {'Parameter': 'Plot_Type', 'Value': current_plot_type},
            {'Parameter': 'Selected_Ion_Types', 'Value': ', '.join(self.last_selected_ions) if self.last_selected_ions else 'None'},
            {'Parameter': 'Number_of_Groups', 'Value': len([g for g in self.comparison_groups.values() if g['widget'].count() > 0])},
            {'Parameter': 'PPM_Tolerance', 'Value': self.main_app.ppm_tolerance_input.value()},
            {'Parameter': 'Max_Neutral_Losses', 'Value': self.main_app.max_neutral_losses_input.value()},
            {'Parameter': 'Active_Tab', 'Value': 'Annotation' if self.main_app.main_tab_widget.currentIndex() == 0 else 'Fragmentation_Analysis'},
        ]
        
        # Add isotope ratio settings if applicable
        if current_plot_type == 'Isotope Ratio Plot':
            if hasattr(self, 'isotope_numerator_combo'):
                metadata.append({'Parameter': 'Isotope_Numerator', 'Value': self.isotope_numerator_combo.currentText()})
            if hasattr(self, 'isotope_denominator_combo'):
                metadata.append({'Parameter': 'Isotope_Denominator', 'Value': self.isotope_denominator_combo.currentText()})
            if hasattr(self, 'zero_denom_checkbox'):
                metadata.append({'Parameter': 'Handle_Zero_Denominator', 'Value': self.zero_denom_checkbox.isChecked()})
            if hasattr(self, 'charge_combo'):
                metadata.append({'Parameter': 'Charge_Filter', 'Value': self.charge_combo.currentText()})
        
        # Add group information with custom names
        total_peptides = 0
        for original_key, group_info in self.comparison_groups.items():
            if group_info['widget'].count() > 0:
                custom_name = group_info['current_name']
                peptide_count = group_info['widget'].count()
                total_peptides += peptide_count
                metadata.append({
                    'Parameter': f'{custom_name}_Replicate_Count',
                    'Value': peptide_count
                })
        
        metadata.append({
            'Parameter': 'Total_Peptides_Used',
            'Value': total_peptides
        })
        
        return pd.DataFrame(metadata)
    
    
    def update_bar_chart_plot(self, selected_ions):
        """Update bar chart plot"""
        # Collect data from ALL groups that have peptides (including single group)
        group_data = {}
        group_colors = []
        custom_names = []
        groups_with_data = []

        # Identify groups with data
        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info['widget'])
            if peptides:  # Only include groups with peptides
                group_data[group_id] = peptides
                groups_with_data.append(group_id)
                group_colors.append(group_info['color'])
                custom_names.append(group_info['current_name'])

        # CHANGED: Allow single group analysis
        if len(group_data) < 1:
            self.show_comparison_message("Please add peptides to at least one group for analysis")
            return

        # Use existing logic for regular bar chart
        all_group_counts = {}
        comparison_data = {}

        # Collect all discovered Ion Type keys across all groups
        all_discovered_ions = set()

        for group_id, peptides in group_data.items():
            ion_counts, _, coverage = self.calculate_group_analysis(peptides, selected_ions, "ion_count")
            all_group_counts[group_id] = ion_counts
            all_discovered_ions.update(ion_counts.keys())

            # Store data for export
            comparison_data[group_id] = {
                'peptides': peptides,
                'ion_counts': ion_counts,
                'coverage': coverage
            }

        # Store for export
        self.last_comparison_data = comparison_data
        # Use discovered Ion Types as the axis labels instead of selected base types
        discovered_ions_list = sorted(all_discovered_ions)
        self.last_selected_ions = discovered_ions_list

        # Create regular bar chart with actual Ion Type labels
        self.create_multi_group_bar_chart_with_custom_names(
            all_group_counts, discovered_ions_list, group_colors, custom_names
        )

    def calculate_group_analysis(self, peptides, selected_ions, analysis_type="ion_count",
                                  numerator_isotope=1, denominator_isotope=0, handle_zero_denom=False):
        """Unified method for group analysis calculations - ENHANCED to handle matched DataFrames"""
        if analysis_type == "ion_count":
            # Results keyed by actual Ion Type values discovered across all peptides
            results = {}
            coverage_results = {}  # base_type -> list of coverage counts per peptide
            peptide_idx = 0
            for peptide_data in peptides:
                matched_df = self.run_fragmentation_analysis(peptide_data, selected_ions)
                peptide_results, base_type_coverage = self.count_ions_by_type(matched_df, selected_ions)

                # Register any newly discovered Ion Types with zero back-fill
                for ion_type in peptide_results:
                    if ion_type not in results:
                        results[ion_type] = [0] * peptide_idx

                # Append this peptide's count for every known Ion Type
                for ion_type in results:
                    results[ion_type].append(peptide_results.get(ion_type, 0))

                peptide_idx += 1

                for base_type, cov_count in base_type_coverage.items():
                    if base_type not in coverage_results:
                        coverage_results[base_type] = []
                    coverage_results[base_type].append(cov_count)

            return results, {}, coverage_results  # Return empty zero_denom for consistency
        
        else:  # isotope_ratio
            results = {ion_type: {} for ion_type in selected_ions}
            all_zero_denom = {ion_type: [] for ion_type in selected_ions}
            
            for peptide_data in peptides:
                # Get matched DataFrame from fragmentation analysis
                matched_df = self.run_fragmentation_analysis(peptide_data, selected_ions)
                
                # Process the matched DataFrame for isotope ratios
                peptide_results, zero_denom = self.calculate_isotope_ratios_by_position(
                    matched_df, selected_ions, numerator_isotope, denominator_isotope, handle_zero_denom
                )
                
                for ion_type in selected_ions:
                    if ion_type in peptide_results:
                        for position, ratio in peptide_results[ion_type].items():
                            if position not in results[ion_type]:
                                results[ion_type][position] = []
                            results[ion_type][position].append(ratio)
                    
                    # Accumulate zero denominator positions
                    if ion_type in zero_denom:
                        all_zero_denom[ion_type].extend(zero_denom[ion_type])
            
            return results, all_zero_denom, {}
        
    def run_fragmentation_analysis(self, peptide_data, selected_ions):
        """Run fragmentation analysis and return matched DataFrame"""
        
        # Extract common data
        peptide = peptide_data.get('peptide', '')
        modifications = peptide_data.get('parsed_modifications', [])
        charge = peptide_data.get('charge', 1)
        
        logger.debug(f"Running fragmentation analysis for peptide: {peptide}, charge: {charge}")
        
        # Get spectral data
        mz_data, intensity_data = self.get_raw_spectral_data(peptide_data)
        if not mz_data:
            logger.debug(f"No spectral data found for peptide")
            return pd.DataFrame()  # Return empty DataFrame
        
        try:
            # grab ions selected
            ion_types = self.main_app.generate_dynamic_ion_types() if self.main_app else self.generate_comprehensive_ion_types()

            # Get custom ion series
            custom_ion_series_list = []
            if self.main_app and hasattr(self.main_app, 'selected_custom_ions_data'):
                from utils.utilities import DataGatherer
                custom_ion_series_list = DataGatherer.gather_custom_ion_series(
                    self.main_app.selected_custom_ions_data
                )

            # Build modification-specific neutral losses from central DB
            mod_neutral_losses = None
            central_mod_db = getattr(self.main_app, 'central_mod_db', None)
            if central_mod_db and modifications:
                from utils.utilities import DataGatherer
                enable_labile = getattr(self.main_app, 'enable_labile_losses_cb', None)
                enable_labile = enable_labile.isChecked() if enable_labile else False
                enable_remainder = getattr(self.main_app, 'enable_remainder_ions_cb', None)
                enable_remainder = enable_remainder.isChecked() if enable_remainder else False
                enable_mod_nl = getattr(self.main_app, 'enable_mod_nl_cb', None)
                enable_mod_nl = enable_mod_nl.isChecked() if enable_mod_nl else False
                mod_neutral_losses = DataGatherer.build_mod_neutral_losses(
                    modifications, central_mod_db, enable_labile=enable_labile,
                    enable_remainder=enable_remainder, enable_mod_nl=enable_mod_nl
                )

            # Calculate theoretical fragments
            calculated_ions = calculate_fragment_ions(
                peptide_sequence=peptide,
                modifications=modifications,
                max_charge=charge,
                ion_types=ion_types,
                Internal=['b', 'a'] if self.main_app and any(cb.isChecked() for cb in self.main_app.internal_ion_checkboxes.values()) else [],
                custom_ion_series=custom_ion_series_list,
                max_neutral_losses=self.main_app.max_neutral_losses_input.value() if self.main_app else 1,
                mod_neutral_losses=mod_neutral_losses
            )
            
            if calculated_ions.empty:
                logger.debug(f"No theoretical fragments calculated")
                return pd.DataFrame()  # Return empty DataFrame
            
            # Match fragments with experimental data
            user_mz_values = list(zip(mz_data, intensity_data))
            ppm_tolerance = self.main_app.ppm_tolerance_input.value() if self.main_app else 10
            matched_data = match_fragment_ions(
                calculated_ions.to_dict('records'),
                user_mz_values,
                ppm_tolerance=ppm_tolerance
            )
            
            matched_df = pd.DataFrame(matched_data)
            return matched_df
                
        except Exception as e:
            logger.debug(f"Error in fragmentation analysis: {e}")
            traceback.print_exc()
            return pd.DataFrame()  # Return empty DataFrame

    def count_ions_by_type(self, matched_data, selected_ions):
        """Count matched ions by their actual Ion Type column value.

        Each selected ion (a base-type key like 'y' or 'b') is expanded
        into all distinct Ion Type values that share that Base Type in the
        data (e.g. 'y', 'y*', 'y-H2O').

        Returns:
            ion_counts:        dict {ion_type_str: count}
            base_type_coverage: dict {base_type_str: unique_positions}
        """
        if matched_data.empty:
            return {ion_type: 0 for ion_type in selected_ions}, {}

        logger.debug(f"Enhanced counting from {len(matched_data)} matched peaks")

        # Filter for matched, monoisotopic peaks
        matched_peaks = matched_data[
            (matched_data['Matched'].notna()) &
            (matched_data['Matched'] != 'No Match')
        ].copy()

        if 'Isotope' in matched_peaks.columns:
            matched_peaks = matched_peaks[
                pd.to_numeric(matched_peaks['Isotope'], errors='coerce') == 0
            ]

        logger.debug(f"After filtering: {len(matched_peaks)} peaks")

        # Build a set of selected base-type keys for fast lookup.
        # Handle special selected_ions like 'int-b', custom series, etc.
        selected_set = set(selected_ions)

        ion_counts = {}

        for _, row in matched_peaks.iterrows():
            ion_type_full = str(row.get('Ion Type', '')).strip()
            base_type = str(row.get('Base Type', '')).strip()

            if not ion_type_full or not base_type:
                continue

            # Determine if this row belongs to any selected ion category.
            # Internal ions: selected as 'int-b', ion type starts with 'int-'
            is_selected = False
            if ion_type_full.startswith('int-'):
                # Internal ion — check if 'int-<base>' is in selected set
                int_key = f"int-{base_type}"
                if int_key in selected_set:
                    is_selected = True
            elif ion_type_full.startswith('custom_'):
                # Custom ion series
                for sel in selected_set:
                    if sel in ion_type_full:
                        is_selected = True
                        break
            else:
                # Standard ions: check if base_type is in selected set
                if base_type in selected_set:
                    is_selected = True
                # Also check for special selected keys like z+1, c-1
                elif 'z+1' in selected_set and 'z+1' in ion_type_full:
                    is_selected = True
                elif 'c-1' in selected_set and 'c-1' in ion_type_full:
                    is_selected = True
                # Neutral loss selected directly (e.g. 'y-H2O' in selected)
                elif ion_type_full in selected_set:
                    is_selected = True

            if is_selected:
                ion_counts[ion_type_full] = ion_counts.get(ion_type_full, 0) + 1

        # Sequence coverage by base type (unchanged)
        base_type_positions = {}
        for _, row in matched_peaks.iterrows():
            base_type = str(row.get('Base Type', '')).strip()
            if not base_type or base_type in ('None', 'nan', ''):
                continue
            try:
                ion_number = int(row.get('Ion Number', 0))
                if base_type not in base_type_positions:
                    base_type_positions[base_type] = set()
                base_type_positions[base_type].add(ion_number)
            except (ValueError, TypeError):
                pass
        base_type_coverage = {bt: len(positions) for bt, positions in base_type_positions.items()}

        logger.debug(f"Ion counts: {ion_counts}")
        logger.debug(f"Sequence coverage by base type: {base_type_coverage}")
        return ion_counts, base_type_coverage


    def _ion_type_matches_selected(self, ion_type_full, selected_ion_type):
            """Unified ion type matching method"""
            # Handle z+1 as special case first
            if selected_ion_type == 'z+1':
                return 'z+1' in ion_type_full.lower() or (
                    ion_type_full.startswith('z') and '+1' in ion_type_full
                )
            
            # Handle c-1 as special case
            if selected_ion_type == 'c-1':
                return 'c-1' in ion_type_full.lower() or (
                    ion_type_full.startswith('c') and '-1' in ion_type_full
                )
            
            # Handle regular z ions (should NOT match z+1)
            if selected_ion_type == 'z':
                if 'z+1' in ion_type_full.lower():
                    return False
                base_match = re.match(r'^z\d*', ion_type_full)
                return base_match is not None
            
            # Handle regular c ions (should NOT match c-1)
            if selected_ion_type == 'c':
                if 'c-1' in ion_type_full.lower():
                    return False
                base_match = re.match(r'^c\d*', ion_type_full)
                return base_match is not None

            # Handle d (include da, db variants)
            if selected_ion_type == 'd':
                return re.match(r'^d[ab]?\d*', ion_type_full) is not None

            # Handle w (include wa, wb variants)
            if selected_ion_type == 'w':
                return re.match(r'^w[ab]?\d*', ion_type_full) is not None

            # Handle satellite neutral losses: d-H2O matches da-H2O, db-H2O etc.
            if selected_ion_type.startswith(('d-', 'w-')):
                base_letter = selected_ion_type[0]  # 'd' or 'w'
                loss_part = selected_ion_type[1:]    # '-H2O', '-NH3'
                return re.match(rf'^{base_letter}[ab]?{re.escape(loss_part)}$', ion_type_full) is not None
            if selected_ion_type.startswith('v-'):
                return ion_type_full == selected_ion_type

            # Extract base type from the full ion type string
            base_type = ion_type_full.split('-')[0].split('+')[0]
            
            # Handle different ion type categories
            if selected_ion_type.startswith('int-'):
                if base_type.startswith('int-') and base_type[4:] == selected_ion_type[4:]:
                    return True
            elif '-' in selected_ion_type and selected_ion_type not in ['z+1', 'c-1']:
                if selected_ion_type in ion_type_full or base_type == selected_ion_type.split('-')[0]:
                    return True
            elif selected_ion_type in ['b', 'y', 'a', 'x', 'MH', 'd', 'v', 'w']:
                if base_type == selected_ion_type:
                    return True
            else:
                # Custom ion series
                if selected_ion_type in ion_type_full:
                    return True
            
            return False


    def create_isotope_ratio_plot(self, selected_ions):
        """Create isotope ratio plot with user-selected isotopes"""
        logger.debug(f"Creating isotope ratio plot for selected ions: {selected_ions}")
        
        # Get selected charge state
        selected_charge = None
        if hasattr(self, 'charge_combo'):
            charge_text = self.charge_combo.currentText()
            if charge_text != "All":
                selected_charge = int(charge_text)
                logger.debug(f"Filtering for charge state: {selected_charge}")
        
        # Get selected isotope numerator and denominator
        numerator_isotope = 1  # Default
        denominator_isotope = 0  # Default
        handle_zero_denom = False  # Default
        
        if hasattr(self, 'isotope_numerator_combo'):
            numerator_isotope = int(self.isotope_numerator_combo.currentText())
        if hasattr(self, 'isotope_denominator_combo'):
            denominator_isotope = int(self.isotope_denominator_combo.currentText())
        if hasattr(self, 'zero_denom_checkbox'):
            handle_zero_denom = self.zero_denom_checkbox.isChecked()
        
        logger.debug(f"Isotope ratio: isotope {numerator_isotope} / isotope {denominator_isotope}")
        logger.debug(f"Handle zero denominator: {handle_zero_denom}")
        
        # Collect data ONLY from groups that have peptides
        group_data = {}
        group_colors = []
        custom_names = []
        
        # Identify groups with data
        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info['widget'])
            if peptides:  # Only include groups with peptides
                group_data[group_id] = peptides
                group_colors.append(group_info['color'])
                custom_names.append(group_info['current_name'])
        
        if len(group_data) < 1:
            self.show_comparison_message("Please add peptides to at least one group for isotope ratio analysis")
            return
        
        # Calculate isotope ratios for each group
        all_group_ratios = {}
        all_group_zero_denom = {}
        comparison_data = {}
        
        for group_id, peptides in group_data.items():
            isotope_ratios, zero_denom, _ = self.calculate_group_analysis(
                peptides, selected_ions, "isotope_ratio", 
                numerator_isotope, denominator_isotope, handle_zero_denom
            )
            all_group_ratios[group_id] = isotope_ratios
            all_group_zero_denom[group_id] = zero_denom
            
            # Store data for export
            comparison_data[group_id] = {
                'peptides': peptides,
                'isotope_ratios': isotope_ratios,
                'zero_denom_positions': zero_denom
            }
        
        # Store for export
        self.last_comparison_data = comparison_data
        self.last_selected_ions = selected_ions
        
        # Create the isotope ratio plot with charge filter
        self.create_isotope_ratio_scatter_plot(
            all_group_ratios, selected_ions, group_colors, custom_names, selected_charge,
            numerator_isotope, denominator_isotope, handle_zero_denom, all_group_zero_denom
        )

    def get_raw_spectral_data(self, peptide_data):
        """Get raw spectral data (m/z and intensity) from cache - returns tuple (mz_values, intensity_values)"""
        try:
            # Get the row data which should contain the proper file path info
            row_data = peptide_data.get('row_data', {})
            
            if not row_data:
                logger.debug(f"No row data found in peptide_data")
                return [], []
            
            # Use the same approach as PSM summary widget
            raw_path_str = row_data.get("spectrum_file_path", "")
            index_str = str(row_data.get("index", ""))
            
            logger.debug(f"Raw path: {raw_path_str}")
            logger.debug(f"Index: {index_str}")
            
            if not raw_path_str or not index_str:
                logger.debug(f"Missing spectrum_file_path or index in row_data")
                logger.debug(f"Available row_data keys: {list(row_data.keys())}")
                return [], []

            # Clean scan number using the same method as PSM summary
            scan_str = DataGatherer._clean_scan_number(index_str)
            
            # Create cache key exactly like PSM summary does
            cache_key = f"{raw_path_str}_{scan_str}"
            
            logger.debug(f"Looking for cache key: {cache_key}")
            
            # Access main app's extracted spectral data directly
            if not hasattr(self.main_app, 'extracted_spectral_data'):
                logger.debug(f"No extracted_spectral_data found on main app")
                return [], []
                
            extracted_data = self.main_app.extracted_spectral_data
            
            if cache_key not in extracted_data:
                logger.debug(f"Cache key not found in extracted_spectral_data")
                
                # Debug: Show what keys are actually available
                available_keys = list(extracted_data.keys())
                logger.debug(f"Available cache keys ({len(available_keys)}): {available_keys[:5]}...")
                
                # Try to find similar keys
                similar_keys = [key for key in available_keys if scan_str in key]
                if similar_keys:
                    logger.debug(f"Keys containing scan '{scan_str}': {similar_keys[:3]}")
                
                return [], []
            
            # Get spectral data
            spectral_data = extracted_data[cache_key]
            mz_data = spectral_data.get('mz_values', [])
            intensity_data = spectral_data.get('intensity_values', [])
            
            logger.debug(f"Found cached spectral data: {len(mz_data)} peaks")
            
            return mz_data, intensity_data
                    
        except Exception as e:
            logger.debug(f"Error getting raw spectral data: {e}")
            traceback.print_exc()
            return [], []
    

    def generate_comprehensive_ion_types(self):
        """Generate comprehensive ion types as fallback when main app is not available"""
        return [
            'b', 'y', 'a', 'c', 'z', 'x', 'MH',
            'y-H2O', 'b-H2O', 'a-H2O', 'y-NH3', 'b-NH3', 'a-NH3',
            'y-H3PO4', 'b-H3PO4', 'a-H3PO4', 'y-SOCH4', 'b-SOCH4',
            'MH-H2O', 'MH-NH3'
        ]


    def calculate_isotope_ratios_by_position(self, matched_df, selected_ions, numerator_isotope=1, denominator_isotope=0, handle_zero_denom=False):
        """Calculate isotope ratios by ion position with configurable isotopes"""
        isotope_ratios = {ion_type: {} for ion_type in selected_ions}
        zero_denom_positions = {ion_type: [] for ion_type in selected_ions}  # Track positions with zero denominator
        
        if matched_df.empty:
            return isotope_ratios, zero_denom_positions
        
        # Filter for matched peaks only
        matched_peaks = matched_df[
            (matched_df['Matched'].notna()) & 
            (matched_df['Matched'] != 'No Match')
        ].copy()
        
        if matched_peaks.empty:
            return isotope_ratios, zero_denom_positions
        
        logger.debug(f"Processing {len(matched_peaks)} matched peaks for isotope ratios (isotope {numerator_isotope} / isotope {denominator_isotope})")
        
        # Group by ion type, charge, and position
        for ion_type in selected_ions:
            # Filter for this ion type
            type_filtered_peaks = []
            
            for _, row in matched_peaks.iterrows():
                ion_type_full = str(row['Ion Type'])
                
                if self._ion_type_matches_selected(ion_type_full, ion_type):
                    type_filtered_peaks.append(row)
            
            if not type_filtered_peaks:
                continue
            
            # Group by charge and position to find isotope pairs
            charge_position_groups = {}
            
            for peak_row in type_filtered_peaks:
                # Extract charge - INLINED
                if 'Charge' in peak_row and pd.notna(peak_row['Charge']):
                    try:
                        charge = int(peak_row['Charge'])
                    except (ValueError, TypeError):
                        charge = 1
                else:
                    # Inline charge extraction
                    ion_type_str = peak_row['Ion Type']
                    charge_match = re.search(r'\+(\d+)', ion_type_str)
                    if charge_match:
                        charge = int(charge_match.group(1))
                    else:
                        charge_match = re.search(r'\^(\d+)', ion_type_str)
                        charge = int(charge_match.group(1)) if charge_match else 1
                
                # Extract position - INLINED
                if 'Ion Number' in peak_row and pd.notna(peak_row['Ion Number']):
                    try:
                        position = int(peak_row['Ion Number'])
                    except (ValueError, TypeError):
                        ion_type_str = peak_row['Ion Type']
                        position_match = re.search(r'^[a-zA-Z]+(\d+)', ion_type_str)
                        if position_match:
                            position = int(position_match.group(1))
                        elif ion_type_str.startswith('int-'):
                            internal_match = re.search(r'int-[a-zA-Z]*(\d+)', ion_type_str)
                            position = int(internal_match.group(1)) if internal_match else 0
                        else:
                            position = 0
                else:
                    # Same inline logic as above
                    ion_type_str = peak_row['Ion Type']
                    position_match = re.search(r'^[a-zA-Z]+(\d+)', ion_type_str)
                    if position_match:
                        position = int(position_match.group(1))
                    elif ion_type_str.startswith('int-'):
                        internal_match = re.search(r'int-[a-zA-Z]*(\d+)', ion_type_str)
                        position = int(internal_match.group(1)) if internal_match else 0
                    else:
                        position = 0
                
                # Extract isotope number
                if 'Isotope' in peak_row and pd.notna(peak_row['Isotope']):
                    try:
                        isotope = int(peak_row['Isotope'])
                    except (ValueError, TypeError):
                        isotope = 0
                else:
                    isotope = 0
                
                # Group by charge and position
                key = (charge, position)
                if key not in charge_position_groups:
                    charge_position_groups[key] = {}
                
                if isotope not in charge_position_groups[key]:
                    charge_position_groups[key][isotope] = []
                
                # Store intensity
                intensity = peak_row.get('intensity', 0)
                charge_position_groups[key][isotope].append(intensity)
            
            # Calculate ratios for each charge/position group
            for (charge, position), isotope_data in charge_position_groups.items():
                position_charge_key = (position, charge)
                
                if numerator_isotope in isotope_data and denominator_isotope in isotope_data:
                    # Both isotopes exist - calculate ratio normally
                    intensity_num = sum(isotope_data[numerator_isotope]) / len(isotope_data[numerator_isotope])
                    intensity_denom = sum(isotope_data[denominator_isotope]) / len(isotope_data[denominator_isotope])
                    
                    if intensity_denom > 0:
                        ratio = intensity_num / intensity_denom
                        
                        # Store ratio with (position, charge) tuple as key
                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []
                        
                        isotope_ratios[ion_type][position_charge_key].append(ratio)
                        
                        logger.debug(f"{ion_type} position {position} charge {charge}: ratio = {ratio:.3f} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}={intensity_denom:.0f})")
                    elif handle_zero_denom and intensity_num > 0:
                        # Denominator exists but intensity is 0 - complete transfer, add as ratio=5
                        complete_transfer_ratio = 5.0
                        
                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []
                        
                        isotope_ratios[ion_type][position_charge_key].append(complete_transfer_ratio)
                        zero_denom_positions[ion_type].append({
                            'position': position,
                            'charge': charge,
                            'numerator_intensity': intensity_num,
                            'position_charge_key': position_charge_key
                        })
                        logger.debug(f"{ion_type} position {position} charge {charge}: zero denominator intensity - using ratio={complete_transfer_ratio} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}=0)")
                
                elif handle_zero_denom and numerator_isotope in isotope_data and denominator_isotope not in isotope_data:
                    # Numerator exists but denominator was never matched/detected - complete hydrogen transfer
                    intensity_num = sum(isotope_data[numerator_isotope]) / len(isotope_data[numerator_isotope])
                    complete_transfer_ratio = 5.0
                    
                    if intensity_num > 0:
                        # Add to regular ratios so it's plotted with the same group
                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []
                        
                        isotope_ratios[ion_type][position_charge_key].append(complete_transfer_ratio)
                        zero_denom_positions[ion_type].append({
                            'position': position,
                            'charge': charge,
                            'numerator_intensity': intensity_num,
                            'position_charge_key': position_charge_key
                        })
                        logger.debug(f"{ion_type} position {position} charge {charge}: COMPLETE TRANSFER - using ratio={complete_transfer_ratio} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}=not found)")
        
        return isotope_ratios, zero_denom_positions
        
    def create_isotope_ratio_scatter_plot(self, all_group_ratios, selected_ions, group_colors, custom_names, selected_charge=None,
                                          numerator_isotope=1, denominator_isotope=0, handle_zero_denom=False, all_group_zero_denom=None):
        """Create scatter plot of isotope ratios vs ion position with charge filtering and averaging"""

        logger.debug(f"Creating isotope ratio scatter plot for groups: {custom_names}")
        if selected_charge:
            logger.debug(f"Filtering for charge state: {selected_charge}")
        
        if not all_group_ratios or not custom_names:
            self.show_comparison_message("No groups with isotope ratio data found")
            return
        
        self.comparison_figure.clear()
        ax = self.comparison_figure.add_subplot(111)

        # Apply theme-aware styling to axes
        self._apply_theme_to_axes(ax)
        
        # Filter data by charge state if specified
        filtered_ratios = {}
        for group_id, group_ratios in all_group_ratios.items():
            filtered_ratios[group_id] = {}
            for ion_type in selected_ions:
                if ion_type not in group_ratios:
                    continue
                filtered_ratios[group_id][ion_type] = {}
                
                for position_charge_key, ratio_values in group_ratios[ion_type].items():
                    # position_charge_key is tuple (position, charge)
                    if isinstance(position_charge_key, tuple) and len(position_charge_key) == 2:
                        position, charge = position_charge_key
                        # Filter by charge if specified
                        if selected_charge is None or charge == selected_charge:
                            # Group by position only (combine all charges or filtered charge)
                            if position not in filtered_ratios[group_id][ion_type]:
                                filtered_ratios[group_id][ion_type][position] = []
                            
                            # Add ratio values - flatten any nested lists
                            if isinstance(ratio_values, list):
                                # Flatten the list
                                for val in ratio_values:
                                    if isinstance(val, (int, float)):
                                        filtered_ratios[group_id][ion_type][position].append(float(val))
                                    elif isinstance(val, list):
                                        # Nested list - flatten it
                                        filtered_ratios[group_id][ion_type][position].extend([float(v) for v in val])
                            elif isinstance(ratio_values, (int, float)):
                                filtered_ratios[group_id][ion_type][position].append(float(ratio_values))
        
        # Find all positions and active ions
        all_positions = set()
        active_ions = []
        
        # Check regular ratio data
        for group_id, group_ratios in filtered_ratios.items():
            for ion_type in selected_ions:
                if ion_type in group_ratios and group_ratios[ion_type]:
                    if ion_type not in active_ions:
                        active_ions.append(ion_type)
                    for position in group_ratios[ion_type].keys():
                        all_positions.add(position)
        
        # Also check zero denominator (complete transfer) data for active ions
        if handle_zero_denom and all_group_zero_denom:
            for group_id, zero_denom_data in all_group_zero_denom.items():
                for ion_type in selected_ions:
                    if ion_type in zero_denom_data and zero_denom_data[ion_type]:
                        # Check if any match the charge filter
                        has_matching_charge = False
                        for zd in zero_denom_data[ion_type]:
                            if selected_charge is None or zd['charge'] == selected_charge:
                                has_matching_charge = True
                                break
                        if has_matching_charge and ion_type not in active_ions:
                            active_ions.append(ion_type)
        
        if not active_ions:
            charge_msg = f" for charge {selected_charge}" if selected_charge else ""
            self.show_comparison_message(f"No isotope ratio data found{charge_msg}")
            return
        
        sorted_positions = sorted(all_positions)
        logger.debug(f"Found positions: {sorted_positions}")
        logger.debug(f"Active ions: {active_ions}")
        
        # Determine if we have single or multiple peptides per group
        peptides_per_group = {}
        for group_id in filtered_ratios.keys():
            group_info = self.comparison_groups[group_id]
            peptides_per_group[group_id] = group_info['widget'].count()
        
        # Plot data for each group and ion type
        for group_idx, (group_id, group_ratios) in enumerate(filtered_ratios.items()):
            custom_name = custom_names[group_idx]
            group_color = group_colors[group_idx]
            num_peptides = peptides_per_group[group_id]
            
            for ion_idx, ion_type in enumerate(active_ions):
                if ion_type not in group_ratios or not group_ratios[ion_type]:
                    continue
                
                positions = []
                mean_ratios = []
                std_ratios = []
                
                for position in sorted(group_ratios[ion_type].keys()):
                    ratio_values = group_ratios[ion_type][position]
                    
                    if not ratio_values:
                        continue
                    
                    # Ensure all values are scalars
                    clean_values = []
                    for val in ratio_values:
                        if isinstance(val, (int, float)):
                            clean_values.append(float(val))
                        elif isinstance(val, (list, tuple)) and len(val) > 0:
                            # Flatten nested structures
                            clean_values.extend([float(v) for v in val if isinstance(v, (int, float))])
                    
                    if not clean_values:
                        continue
                    
                    positions.append(position)
                    
                    if len(clean_values) == 1 and num_peptides == 1:
                        # Single peptide, single point - no error bar
                        mean_ratios.append(float(clean_values[0]))
                        std_ratios.append(0.0)
                    else:
                        # Multiple values - show mean with error bar
                        mean_ratios.append(float(np.mean(clean_values)))
                        std_ratios.append(float(np.std(clean_values, ddof=1) if len(clean_values) > 1 else 0.0))
                
                if positions and mean_ratios:
                    # Ensure all arrays are numpy arrays of floats
                    positions = np.array(positions, dtype=float)
                    mean_ratios = np.array(mean_ratios, dtype=float)
                    std_ratios = np.array(std_ratios, dtype=float)
                    
                    # Create marker style for this ion type
                    markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'h']
                    marker = markers[ion_idx % len(markers)]
                    
                    # Adjust color for different ion types
                    base_color = mcolors.to_rgba(group_color)
                    alpha = 0.8 - (ion_idx * 0.1)
                    alpha = max(alpha, 0.3)
                    
                    # Plot with error bars
                    ax.errorbar(positions, mean_ratios, yerr=std_ratios,
                              fmt=marker, color=base_color, alpha=alpha,
                              markersize=8, capsize=4, capthick=1.5,
                              ecolor=base_color, elinewidth=1.5,
                              label=f'{custom_name} - {ion_type}',
                              markeredgecolor='black', markeredgewidth=0.5)
                    
                    logger.debug(f"Plotted {len(positions)} points for {custom_name} - {ion_type}")
        
        # Customize plot
        ax.set_xlabel('Ion Position', fontsize=12, fontweight='bold')
        ax.set_ylabel(f'Isotope Ratio (Isotope {numerator_isotope} / Isotope {denominator_isotope})', fontsize=12, fontweight='bold')
        
        # Update title based on charge filter
        charge_text = f" (Charge {selected_charge})" if selected_charge else ""
        ax.set_title(f'Isotope Ratio Analysis{charge_text}\n({len(custom_names)} groups, {len(active_ions)} ion types)', 
                    fontsize=14, fontweight='bold')
        
        # Use linear scale with breaks of 1, not log scale
        all_ratios = []
        for group_ratios in filtered_ratios.values():
            for ion_ratios in group_ratios.values():
                for ratio_values in ion_ratios.values():
                    if isinstance(ratio_values, list):
                        all_ratios.extend(ratio_values)
                    else:
                        all_ratios.append(ratio_values)
        
        # Handle zero denominator points (complete hydrogen transfer) if enabled
        zero_denom_count = 0
        complete_transfer_ratio = 5.0  # Fixed ratio for complete hydrogen transfer
        has_complete_transfer_points = False
        
        if handle_zero_denom and all_group_zero_denom:
            # Count complete transfer points (they're already plotted with regular data)
            for group_id, zero_denom_data in all_group_zero_denom.items():
                if not zero_denom_data:
                    continue
                    
                for ion_type in active_ions:
                    if ion_type not in zero_denom_data:
                        continue
                    
                    zero_denom_list = zero_denom_data[ion_type]
                    if not zero_denom_list:
                        continue
                    
                    # Filter by charge if specified
                    for zd in zero_denom_list:
                        if selected_charge is None or zd['charge'] == selected_charge:
                            zero_denom_count += 1
                            has_complete_transfer_points = True
        
        # Set x-axis limits AFTER all points (including complete transfer) are added to all_positions
        if all_positions:
            x_min, x_max = min(all_positions), max(all_positions)
            ax.set_xlim(x_min - 0.5, x_max + 0.5)
        
        if all_ratios:
            y_min = max(0, min(all_ratios) - 1)
            y_max = max(all_ratios) + 1
            
            # Extend y_max if we have complete transfer points
            if has_complete_transfer_points:
                y_max = max(y_max, complete_transfer_ratio + 1)
            
            ax.set_ylim(y_min, y_max)
            
            # Set y-axis major ticks at intervals of 1
            from matplotlib.ticker import MultipleLocator
            ax.yaxis.set_major_locator(MultipleLocator(1.0))
        
        # Add horizontal line at ratio = 1 for reference
        ax.axhline(y=1.0, color=EditorConstants.GRID_COLOR(), linestyle='--', alpha=0.5, label='Ratio = 1.0 (reference)')
        
        # Add complete transfer reference line at ratio = 5 if we have such points
        if has_complete_transfer_points:
            ax.axhline(y=complete_transfer_ratio, color='#E74C3C', linestyle=':', linewidth=2, alpha=0.7, label='Complete transfer (ratio = 5)')
        
        # Create legend
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9)
        ax.grid(True, alpha=0.3, axis='both')
        
        # Add statistics text
        total_points = sum(len(ratios) for group_ratios in filtered_ratios.values() 
                          for ion_ratios in group_ratios.values() 
                          for ratios in ion_ratios.values())
        
        stats_text = f'Total data points: {total_points}\n'
        if zero_denom_count > 0:
            stats_text += f'Complete transfer points: {zero_denom_count}\n'
        stats_text += f'Position range: {min(all_positions) if all_positions else 0}-{max(all_positions) if all_positions else 0}\n'
        if all_ratios:
            stats_text += f'Ratio range: {min(all_ratios):.3f}-{max(all_ratios):.3f}'
        
        ax.text(0.02, 0.98, stats_text, 
                transform=ax.transAxes, fontsize=9, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor=EditorConstants.ANNOTATION_BG(), alpha=0.8))
        
        # Adjust layout to prevent legend cutoff
        self.comparison_figure.tight_layout()
        self.comparison_canvas.draw()
        
        logger.debug(f"Isotope ratio scatter plot completed successfully")
        
        
            
    def export_fragmentation_analysis(self):
        """Export detailed fragmentation analysis for all peptides in all groups"""

        # Get selected ion types
        selected_ions = self.get_selected_ion_types_for_comparison()
        
        if not selected_ions:
            QMessageBox.warning(
                self.main_app, 
                "No Ion Types Selected", 
                "Please select at least one ion type in the left panel before exporting fragmentation analysis."
            )
            return
        
        # Collect all peptides from all groups
        all_peptides = []
        peptide_group_mapping = []
        
        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info['widget'])
            group_name = group_info['current_name']
            
            for peptide_data in peptides:
                all_peptides.append(peptide_data)
                peptide_group_mapping.append({
                    'group_id': group_id,
                    'group_name': group_name,
                    'peptide': peptide_data.get('peptide', 'Unknown'),
                    'charge': peptide_data.get('charge', 'Unknown')
                })
        
        if not all_peptides:
            QMessageBox.warning(
                self.main_app, 
                "No Peptides Found", 
                "No peptides found in any comparison groups. Please add peptides to analyze."
            )
            return
        
        # Get export filename
        default_filename = self._get_fragmentation_export_default_filename()
        filename = self._get_export_filename(
            "Export Fragmentation Analysis",
            default_filename,
            "Excel files (*.xlsx);;CSV files (*.csv);;All files (*.*)"
        )
        
        if not filename:
            return
        
        # Create progress dialog
        progress = QProgressDialog(
            "Analyzing fragmentation patterns...", 
            "Cancel", 
            0, 
            len(all_peptides), 
            self.main_app
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        try:
            # Process all peptides and collect matched data
            all_matched_data = []
            
            for i, (peptide_data, group_info) in enumerate(zip(all_peptides, peptide_group_mapping)):
                
                # Update progress
                progress.setValue(i)
                progress.setLabelText(f"Analyzing peptide {i+1}/{len(all_peptides)}: {group_info['peptide']}")
                
                if progress.wasCanceled():
                    return
                
                # Run fragmentation analysis
                matched_df = self.run_fragmentation_analysis(peptide_data, selected_ions)
                
                if not matched_df.empty:
                    # Add group and peptide information to each row
                    matched_df = matched_df.copy()
                    matched_df['Group_ID'] = group_info['group_id']
                    matched_df['Group_Name'] = group_info['group_name']
                    matched_df['Peptide_Sequence'] = group_info['peptide']
                    matched_df['Peptide_Charge'] = group_info['charge']
                    matched_df['Peptide_Index'] = i + 1
                    
                    # Add additional peptide metadata if available
                    matched_df['Spectrum_File'] = peptide_data.get('Spectrum file', 'Unknown')
                    matched_df['Scan_Number'] = peptide_data.get('index', 'Unknown')
                    matched_df['Modifications'] = str(peptide_data.get('parsed_modifications', []))
                    
                    all_matched_data.append(matched_df)
                else:
                    logger.warning(f"No matched data for peptide {group_info['peptide']} in group {group_info['group_name']}")
            
            progress.close()
            
            if not all_matched_data:
                QMessageBox.warning(
                    self.main_app, 
                    "No Fragmentation Data", 
                    "No fragmentation matches found for any peptides. Check your ion selections and peptide data."
                )
                return
            
            # Combine all matched data
            combined_df = pd.concat(all_matched_data, ignore_index=True)
            
            # Reorder columns to put metadata first
            metadata_cols = [
                'Group_ID', 'Group_Name', 'Peptide_Index', 'Peptide_Sequence', 
                'Peptide_Charge', 'Modifications', 'Spectrum_File', 'Scan_Number'
            ]
            other_cols = [col for col in combined_df.columns if col not in metadata_cols]
            final_df = combined_df[metadata_cols + other_cols]
            
            # Export data
            if filename.endswith('.xlsx'):
                self._export_fragmentation_to_excel(final_df, filename, selected_ions, peptide_group_mapping)
            else:
                # CSV export
                final_df.to_csv(filename, index=False)
            
            # Show success message
            QMessageBox.information(
                self.main_app, 
                "Export Complete", 
                f"Fragmentation analysis exported successfully!\n\n"
                f"File: {filename}\n"
                f"Peptides analyzed: {len(all_peptides)}\n"
                f"Total matches: {len(final_df)}\n"
                f"Ion types: {', '.join(selected_ions)}"
            )
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self.main_app, 
                "Export Error", 
                f"Failed to export fragmentation analysis:\n{str(e)}"
            )
            logger.error(f"Fragmentation export error: {e}")

            traceback.print_exc()

    def _export_fragmentation_to_excel(self, combined_df, filename, selected_ions, peptide_group_mapping):
        """Export fragmentation data to Excel with multiple sheets"""

        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            
            # Main fragmentation data sheet
            combined_df.to_excel(writer, sheet_name='Fragmentation_Analysis', index=False)
            
            # Summary sheet - ion counts per peptide
            summary_data = []
            for i, group_info in enumerate(peptide_group_mapping):
                peptide_df = combined_df[combined_df['Peptide_Index'] == i + 1]
                
                # Count matched ions (excluding "No Match")
                matched_df = peptide_df[
                    (peptide_df['Matched'].notna()) & 
                    (peptide_df['Matched'] != 'No Match')
                ]
                
                # Count by ion type
                ion_counts = {}
                for ion_type in selected_ions:
                    count = 0
                    for _, row in matched_df.iterrows():
                        ion_type_full = str(row.get('Ion Type', ''))
                        if self._ion_type_matches_selected(ion_type_full, ion_type):
                            count += 1
                    ion_counts[ion_type] = count

                # Collect sequence coverage by base type (monoisotopic only)
                mono_df = matched_df
                if 'Isotope' in mono_df.columns:
                    mono_df = mono_df[pd.to_numeric(mono_df['Isotope'], errors='coerce') == 0]
                base_type_positions = {}
                for _, row in mono_df.iterrows():
                    base_type = str(row.get('Base Type', '')).strip()
                    if not base_type or base_type in ('None', 'nan', ''):
                        continue
                    try:
                        ion_number = int(row.get('Ion Number', 0))
                        if base_type not in base_type_positions:
                            base_type_positions[base_type] = set()
                        base_type_positions[base_type].add(ion_number)
                    except (ValueError, TypeError):
                        pass
                base_type_coverage = {bt: len(pos) for bt, pos in base_type_positions.items()}

                # Create summary row
                summary_row = {
                    'Group_Name': group_info['group_name'],
                    'Peptide_Sequence': group_info['peptide'],
                    'Peptide_Charge': group_info['charge'],
                    'Total_Theoretical': len(peptide_df),
                    'Total_Matched': len(matched_df),
                    'Match_Rate_%': (len(matched_df) / len(peptide_df) * 100) if len(peptide_df) > 0 else 0
                }

                # Add ion type counts
                for ion_type in selected_ions:
                    summary_row[f'{ion_type}_Count'] = ion_counts.get(ion_type, 0)

                # Add sequence coverage counts
                for base_type, cov_count in sorted(base_type_coverage.items()):
                    summary_row[f'sequence_coverage_count_{base_type}'] = cov_count
                
                summary_data.append(summary_row)
            
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

    def _get_fragmentation_export_default_filename(self):
        """Generate default filename for fragmentation export"""
  
        
        # Count active groups
        active_groups = []
        for group_info in self.comparison_groups.values():
            if group_info['widget'].count() > 0:
                active_groups.append(group_info['current_name'].replace(" ", "_"))
        
        if active_groups:
            groups_str = "_".join(active_groups[:3])  # Limit to first 3 groups for filename
            if len(active_groups) > 3:
                groups_str += f"_plus{len(active_groups)-3}more"
        else:
            groups_str = "no_groups"
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"fragmentation_analysis_{groups_str}_{timestamp}.xlsx"
    
    def update_theme(self, theme_name):
        """Update fragmentation tab for theme changes"""
        logger.debug(f"Updating fragmentation tab theme to {theme_name}")
        
        # Update matplotlib figure background
        if hasattr(self, 'comparison_figure'):
            self.comparison_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            self.comparison_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())
            
            # Update all axes in the figure
            for ax in self.comparison_figure.get_axes():
                self._apply_theme_to_axes(ax)
                
                # Update tick label colors
                for label in ax.get_xticklabels() + ax.get_yticklabels():
                    label.set_color(EditorConstants.TEXT_COLOR())
            
            # Redraw canvas
            if hasattr(self, 'comparison_canvas'):
                self.comparison_canvas.draw()
        
        # Update all comparison group widgets with new theme colors
        if hasattr(self, 'comparison_groups'):
            logger.debug(f"Updating {len(self.comparison_groups)} comparison groups")
            for group_id, group_info in self.comparison_groups.items():
                color = group_info.get('color', '#0066cc')
                
                # Update group name input styling
                if 'name_input' in group_info:
                    name_input = group_info['name_input']
                    name_input.setStyleSheet(self._get_group_name_style(color))
                    logger.debug(f"Updated name input for {group_id}")
                
                # Update drop zone widget styling using its update_theme method
                if 'widget' in group_info:
                    group_widget = group_info['widget']
                    # Call the widget's own update_theme method if it exists
                    if hasattr(group_widget, 'update_theme'):
                        group_widget.update_theme()
                    else:
                        # Fallback to manual styling
                        group_widget.setStyleSheet(self._get_drop_zone_style())
                    logger.debug(f"Updated drop zone for {group_id}")
                
                # Update container widget background
                if 'container' in group_info:
                    container = group_info['container']
                    container.setStyleSheet(f"""
                        QWidget {{
                            background-color: {EditorConstants.BACKGROUND_COLOR()};
                            border-radius: 8px;
                        }}
                    """)
                    logger.debug(f"Updated container for {group_id}")
        
        # Update draggable PSM summary widget filter sections
        if hasattr(self.main_app, 'frag_psm_summary_widget'):
            psm_widget = self.main_app.frag_psm_summary_widget
            
            # Update filter widget styling
            filter_widget_style = f"""
                QWidget {{
                    background-color: {EditorConstants.GRAY_50()};
                    {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_LARGE())}
                }}
                QLabel {{
                    color: {EditorConstants.HEADER_TEXT_COLOR()};
                    {EditorConstants.get_font_string("bold")}
                    border: none;
                    background: transparent;
                }}
                {EditorConstants.get_scrollbar_style()}
            """
            
            if hasattr(psm_widget, 'summary_filter_widget'):
                psm_widget.summary_filter_widget.setStyleSheet(filter_widget_style)
            if hasattr(psm_widget, 'details_filter_widget'):
                psm_widget.details_filter_widget.setStyleSheet(filter_widget_style)
            
            # Update filter input fields
            if hasattr(psm_widget, 'summary_filter_input'):
                psm_widget.summary_filter_input.setStyleSheet(EditorConstants.get_lineedit_style())
            if hasattr(psm_widget, 'details_filter_input'):
                psm_widget.details_filter_input.setStyleSheet(EditorConstants.get_lineedit_style())
            
            # Update tables
            if hasattr(psm_widget, 'summary_table'):
                StyleSheet.apply_table_styling(psm_widget.summary_table)
            if hasattr(psm_widget, 'details_table'):
                StyleSheet.apply_table_styling(psm_widget.details_table)
        
        # Update right groups widget background
        if hasattr(self, 'right_groups_widget'):
            self.right_groups_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
        
        # Update groups scroll area
        if hasattr(self, 'groups_scroll_area'):
            self.groups_scroll_area.setStyleSheet(self._get_scroll_area_style())
        
        # Update groups container background
        if hasattr(self, 'groups_container'):
            self.groups_container.setStyleSheet(f"""
                QWidget {{
                    background-color: {EditorConstants.BACKGROUND_COLOR()};
                }}
            """)
        
        logger.debug(f"Fragmentation tab theme updated")
 
