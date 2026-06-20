import logging
from utils.style.style import EditorConstants, StyleSheet
from utils.gui_tabs._fragmentation_ui_mixin import _FragmentationUIMixin
from utils.gui_tabs._fragmentation_groups_mixin import _FragmentationGroupsMixin
from utils.gui_tabs._fragmentation_analysis_mixin import _FragmentationAnalysisMixin
from utils.gui_tabs._fragmentation_export_mixin import _FragmentationExportMixin

logger = logging.getLogger(__name__)


class FragmentationTabManager(
    _FragmentationUIMixin,
    _FragmentationGroupsMixin,
    _FragmentationAnalysisMixin,
    _FragmentationExportMixin,
):
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
            "#34495E",  # Dark Blue-Gray
        ]

    def update_theme(self, theme_name):
        """Update fragmentation tab for theme changes"""
        logger.debug(f"Updating fragmentation tab theme to {theme_name}")

        # Update matplotlib figure background
        if hasattr(self, "comparison_figure"):
            self.comparison_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            self.comparison_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())

            # Update all axes in the figure
            for ax in self.comparison_figure.get_axes():
                self._apply_theme_to_axes(ax)

                # Update tick label colors
                for label in ax.get_xticklabels() + ax.get_yticklabels():
                    label.set_color(EditorConstants.TEXT_COLOR())

            # Redraw canvas
            if hasattr(self, "comparison_canvas"):
                self.comparison_canvas.draw()

        # Update all comparison group widgets with new theme colors
        if hasattr(self, "comparison_groups"):
            logger.debug(f"Updating {len(self.comparison_groups)} comparison groups")
            for group_id, group_info in self.comparison_groups.items():
                color = group_info.get("color", "#0066cc")

                # Update group name input styling
                if "name_input" in group_info:
                    name_input = group_info["name_input"]
                    name_input.setStyleSheet(self._get_group_name_style(color))
                    logger.debug(f"Updated name input for {group_id}")

                # Update drop zone widget styling using its update_theme method
                if "widget" in group_info:
                    group_widget = group_info["widget"]
                    # Call the widget's own update_theme method if it exists
                    if hasattr(group_widget, "update_theme"):
                        group_widget.update_theme()
                    else:
                        # Fallback to manual styling
                        group_widget.setStyleSheet(self._get_drop_zone_style())
                    logger.debug(f"Updated drop zone for {group_id}")

                # Update container widget background
                if "container" in group_info:
                    container = group_info["container"]
                    container.setStyleSheet(
                        f"QWidget {{"
                        f"    background-color: {EditorConstants.BACKGROUND_COLOR()};"
                        f"    border-radius: 8px;"
                        f"}}"
                    )
                    logger.debug(f"Updated container for {group_id}")

        # Update draggable PSM summary widget filter sections
        if hasattr(self.main_app, "frag_psm_summary_widget"):
            psm_widget = self.main_app.frag_psm_summary_widget

            # Update filter widget styling
            filter_widget_style = (
                f"QWidget {{"
                f"    background-color: {EditorConstants.GRAY_50()};"
                f"    {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_LARGE())}"
                f"}}"
                f"QLabel {{"
                f"    color: {EditorConstants.HEADER_TEXT_COLOR()};"
                f"    {EditorConstants.get_font_string('bold')}"
                f"    border: none;"
                f"    background: transparent;"
                f"}}"
                f"{EditorConstants.get_scrollbar_style()}"
            )

            if hasattr(psm_widget, "summary_filter_widget"):
                psm_widget.summary_filter_widget.setStyleSheet(filter_widget_style)
            if hasattr(psm_widget, "details_filter_widget"):
                psm_widget.details_filter_widget.setStyleSheet(filter_widget_style)

            # Update filter input fields
            if hasattr(psm_widget, "summary_filter_input"):
                psm_widget.summary_filter_input.setStyleSheet(
                    EditorConstants.get_lineedit_style()
                )
            if hasattr(psm_widget, "details_filter_input"):
                psm_widget.details_filter_input.setStyleSheet(
                    EditorConstants.get_lineedit_style()
                )

            # Update tables
            if hasattr(psm_widget, "summary_table"):
                StyleSheet.apply_table_styling(psm_widget.summary_table)
            if hasattr(psm_widget, "details_table"):
                StyleSheet.apply_table_styling(psm_widget.details_table)

        # Update right groups widget background
        if hasattr(self, "right_groups_widget"):
            self.right_groups_widget.setStyleSheet(
                f"QWidget {{"
                f"    background-color: {EditorConstants.BACKGROUND_COLOR()};"
                f"}}"
            )

        # Update groups scroll area
        if hasattr(self, "groups_scroll_area"):
            self.groups_scroll_area.setStyleSheet(self._get_scroll_area_style())

        # Update groups container background
        if hasattr(self, "groups_container"):
            self.groups_container.setStyleSheet(
                f"QWidget {{"
                f"    background-color: {EditorConstants.BACKGROUND_COLOR()};"
                f"}}"
            )

        logger.debug("Fragmentation tab theme updated")
