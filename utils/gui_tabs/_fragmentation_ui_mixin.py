"""
_FragmentationUIMixin
---------------------
Static style helpers and UI layout-building methods for the fragmentation tab.
Covers: _apply_theme_to_axes, _get_group_name_style, _get_drop_zone_style,
_get_scroll_area_style, setup_fragmentation_analysis_tab,
_create_center_plot_widget, on_plot_type_changed,
_create_right_groups_widget, _create_control_buttons_section.
"""

import logging
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QScrollArea,
    QStackedWidget,
    QCheckBox,
)
from PyQt6.QtCore import Qt
from utils.style.style import EditorConstants
from utils.tables.psm_summary_widget import DraggablePSMSummaryWidget

logger = logging.getLogger(__name__)


class _FragmentationUIMixin:

    @staticmethod
    def _apply_theme_to_axes(ax):
        """Apply theme-aware styling to a matplotlib axes object."""
        ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
        ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which="both")
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
        frag_layout.addWidget(
            self.main_app.frag_psm_summary_widget, 1
        )  # Limit table space

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
            edgecolor=EditorConstants.PLOT_FOREGROUND(),
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
        if hasattr(self, "charge_widget"):
            self.charge_widget.setVisible(is_isotope_plot)
        if hasattr(self, "isotope_options_widget"):
            self.isotope_options_widget.setVisible(is_isotope_plot)

        # Clear existing plots
        if hasattr(self, "comparison_figure"):
            self.comparison_figure.clear()
            self.comparison_canvas.draw()

        # Always use matplotlib view (only view now)
        if hasattr(self, "plot_stack"):
            self.plot_stack.setCurrentIndex(0)
            if is_isotope_plot:
                self.main_app.show_toast_message(
                    "Isotope Ratio Plot: Select isotopes, charge state and click Compare"
                )
            else:
                self.main_app.show_toast_message(
                    "Ion Count Bar Chart: Click Compare to generate chart"
                )

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
        self.add_group_button.setStyleSheet(
            EditorConstants.get_pushbutton_style("success")
        )
        self.add_group_button.clicked.connect(self.add_comparison_group)
        group_buttons_layout.addWidget(self.add_group_button)

        self.remove_group_button = QPushButton("Remove Group")
        self.remove_group_button.setStyleSheet(
            EditorConstants.get_pushbutton_style("danger")
        )
        self.remove_group_button.clicked.connect(self.remove_comparison_group)
        self.remove_group_button.setEnabled(False)  # Disabled when only 1 group
        group_buttons_layout.addWidget(self.remove_group_button)

        group_buttons_layout.addStretch()
        right_main_layout.addLayout(group_buttons_layout)

        # SCROLLABLE AREA for groups
        groups_scroll_area = QScrollArea()
        groups_scroll_area.setWidgetResizable(True)
        groups_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        groups_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
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
        plot_type_label.setStyleSheet(
            f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()};"
        )
        plot_type_layout.addWidget(plot_type_label)

        self.plot_type_combo = QComboBox()
        self.plot_type_combo.addItems(["Ion Count Bar Chart", "Isotope Ratio Plot"])
        self.plot_type_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.plot_type_combo.setToolTip("Select the type of plot to generate")
        self.plot_type_combo.currentTextChanged.connect(self.on_plot_type_changed)
        plot_type_layout.addWidget(self.plot_type_combo)

        control_layout.addLayout(plot_type_layout)

        # Charge Selection (only shown for Isotope Ratio Plot)
        charge_layout = QHBoxLayout()
        charge_label = QLabel("Charge State:")
        charge_label.setStyleSheet(
            f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()};"
        )
        charge_layout.addWidget(charge_label)

        self.charge_combo = QComboBox()
        self.charge_combo.addItems(["All", "1", "2", "3", "4", "5"])
        self.charge_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.charge_combo.setToolTip(
            "Select charge state to filter isotope ratio analysis"
        )
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
        numerator_label.setStyleSheet(
            f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()}; font-size: 10px;"
        )
        isotope_select_layout.addWidget(numerator_label)

        self.isotope_numerator_combo = QComboBox()
        self.isotope_numerator_combo.addItems(["-1", "0", "1", "2", "3", "4"])
        self.isotope_numerator_combo.setCurrentText(
            "1"
        )  # Default numerator is isotope 1
        self.isotope_numerator_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.isotope_numerator_combo.setToolTip("Select isotope for numerator")
        self.isotope_numerator_combo.setMaximumWidth(50)
        isotope_select_layout.addWidget(self.isotope_numerator_combo)

        slash_label = QLabel("/")
        slash_label.setStyleSheet(
            f"font-weight: bold; color: {EditorConstants.TEXT_COLOR()}; font-size: 12px;"
        )
        isotope_select_layout.addWidget(slash_label)

        # Denominator isotope
        self.isotope_denominator_combo = QComboBox()
        self.isotope_denominator_combo.addItems(["-1", "0", "1", "2", "3", "4"])
        self.isotope_denominator_combo.setCurrentText(
            "0"
        )  # Default denominator is isotope 0
        self.isotope_denominator_combo.setStyleSheet(
            EditorConstants.get_combobox_style()
        )
        self.isotope_denominator_combo.setToolTip("Select isotope for denominator")
        self.isotope_denominator_combo.setMaximumWidth(50)
        isotope_select_layout.addWidget(self.isotope_denominator_combo)

        isotope_select_layout.addStretch()
        isotope_options_layout.addLayout(isotope_select_layout)

        # Zero denominator handling checkbox (complete hydrogen transfer)
        self.zero_denom_checkbox = QCheckBox("Show complete transfer (ratio=5)")
        self.zero_denom_checkbox.setStyleSheet(
            f"color: {EditorConstants.TEXT_COLOR()}; font-size: 10px;"
        )
        self.zero_denom_checkbox.setToolTip(
            "When denominator intensity is 0 (e.g., no -1 isotope), display as complete hydrogen transfer at ratio = 5"
        )
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
        export_frag_button.setToolTip(
            "Export detailed fragmentation analysis for all peptides"
        )
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
