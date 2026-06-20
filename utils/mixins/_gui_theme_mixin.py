import logging
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QFrame,
    QSizePolicy,
)
from PyQt6.QtCore import Qt

from utils.style.style import StyleSheet, EditorConstants
from utils import TableUtils
from utils.style.GUI_dimensions import LayoutConstants

logger = logging.getLogger(__name__)


class _GUIThemeMixin:

    def switch_theme(self, theme_name: str) -> None:
        """Switch between light and dark themes - UPDATED"""
        logger.debug(f"Switching to {theme_name} theme")

        # Update theme in theme manager
        from utils.style.style import ThemeManager

        ThemeManager.set_theme(theme_name)

        # Update theme selection in menu
        if theme_name == "light":
            self.light_theme_action.setChecked(True)
            self.dark_theme_action.setChecked(False)
        else:
            self.light_theme_action.setChecked(False)
            self.dark_theme_action.setChecked(True)

        # Apply new stylesheet to main application
        self.setStyleSheet(StyleSheet.build_gui_style())

        # Update all major widget styles
        self._update_all_widget_styles()
        self.annotation_tab_manager.update_theme(theme_name)
        self.fragmentation_tab_manager.update_theme(theme_name)
        self.rescoring_tab_manager.update_theme(theme_name)
        self.protein_coverage_tab_manager.update_theme(theme_name)
        self.manage_files_tab_manager.update_theme(theme_name)
        self.results_tab_manager.update_theme(theme_name)

        logger.debug(f"Theme switched to {theme_name}")

    def _update_all_widget_styles(self) -> None:
        """Update styles for all widgets that need explicit theme updates"""
        self._update_section_headers()
        self._update_panel_headers()
        self._update_tables()
        self._update_form_widgets()
        self._update_special_widgets()

        logger.debug(
            "Updated all widget styles including section headers and checkboxes"
        )

    def _update_section_headers(self) -> None:
        """Update section header styles for theme changes"""
        section_headers = self.findChildren(QLabel, "section_header")
        for header in section_headers:
            # Apply new stylesheet
            header.setStyleSheet(StyleSheet.get_section_header_style())

            # Also update font directly to ensure immediate change
            font = header.font()
            font.setFamily(EditorConstants.FONT_FAMILY())
            font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
            font.setBold(True)
            header.setFont(font)

            # Force geometry update
            header.updateGeometry()
            header.update()

    def _update_panel_headers(self) -> None:
        """Update panel header styles for theme changes"""
        panel_headers = self.findChildren(QFrame)
        for frame in panel_headers:
            if (
                hasattr(frame, "layout")
                and frame.layout()
                and frame.layout().count() > 0
            ):
                # Check if this is a panel header
                for i in range(frame.layout().count()):
                    item = frame.layout().itemAt(i)
                    if item and isinstance(item.widget(), QLabel):
                        frame.setStyleSheet(StyleSheet.get_panel_header_style())

                        # Update the label font inside the panel header
                        label = item.widget()
                        font = label.font()
                        font.setFamily(EditorConstants.FONT_FAMILY())
                        font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
                        font.setBold(True)
                        label.setFont(font)
                        label.updateGeometry()
                        label.update()
                        break

    def _update_tables(self) -> None:
        """Update table styles for theme changes"""
        all_tables = self.findChildren(QTableWidget)
        for table in all_tables:
            # Apply new table styling
            StyleSheet.apply_table_styling(table)

            # Force header updates
            h_header = table.horizontalHeader()
            if h_header:
                h_header.setFixedHeight(EditorConstants.HEADER_MIN_HEIGHT())
                # Update header font
                font = h_header.font()
                font.setFamily(EditorConstants.FONT_FAMILY())
                font.setPointSize(EditorConstants.HEADER_FONT_SIZE())
                font.setBold(True)
                h_header.setFont(font)

    def _update_form_widgets(self) -> None:
        """Update form widget styles (spinboxes, checkboxes, labels)"""
        # Update spinboxes explicitly
        for spinbox in self.findChildren(QSpinBox):
            spinbox.setStyleSheet(EditorConstants.get_spinbox_style())

        # Update checkboxes
        for checkbox in self.findChildren(QCheckBox):
            checkbox.setStyleSheet(EditorConstants.get_checkbox_style())

        # Update all QLabel widgets (for spinbox labels, etc.)
        for label in self.findChildren(QLabel):
            # Skip section headers and other specially styled labels
            if (
                label.objectName() != "section_header"
                and "section_header" not in label.styleSheet()
            ):
                # Check if label has custom styling or is a standard label
                current_style = label.styleSheet()
                if "color:" in current_style or not current_style:
                    # Update color for labels with explicit color or no styling
                    label.setStyleSheet(f"""
                        QLabel {{
                            color: {EditorConstants.TEXT_COLOR()};
                        }}
                    """)

        # Update tab widget styling
        for tab_widget in self.findChildren(QTabWidget):
            tab_widget.setStyleSheet(EditorConstants.get_tab_style())

    def _update_special_widgets(self) -> None:
        """Update special widget styles (ion tiles, PSM summary, spectrum tracker)"""
        # Update ion tiles for theme changes
        from utils.utility_classes.widgets import IonTile

        for tile in self.findChildren(IonTile):
            tile._update_style()

        # Update the PSM summary widget styling
        if hasattr(self, "psm_summary_widget"):
            self.annotation_tab_manager._update_psm_summary_theme()

        # Update spectrum tracker styling
        if hasattr(self, "spectrum_tracker"):
            self.annotation_tab_manager._update_spectrum_tracker_theme()

    def _create_section_header(self, title: str) -> QLabel:
        """Create a standardized section header with proper object name"""
        header = QLabel(title)
        header.setObjectName("section_header")  # Set object name for CSS targeting
        header.setStyleSheet(StyleSheet.get_section_header_style())
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return header

    def _create_widget_container(
        self,
        layout: QHBoxLayout,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
    ) -> QWidget:
        """Create a standardized widget container"""
        widget = QWidget()
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if max_width is not None:
            widget.setMaximumWidth(max_width)

        if min_height:
            widget.setMinimumHeight(min_height)

        return widget

    def _create_selection_table(
        self, headers: List[str], context_menu_handler, data_list_name: str
    ) -> QTableWidget:
        """Create a standardized selection table with common properties"""
        table = TableUtils.create_basic_table(
            row_count=3,
            col_count=len(headers),
            headers=headers,
            min_width=LayoutConstants.MIN_TABLE_WIDTH,
            parent=self,
        )

        table.setMinimumHeight(80)
        table.setMaximumHeight(150)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(context_menu_handler)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.itemChanged.connect(self.on_settings_changed)
        table.horizontalHeader().setFixedHeight(30)  # <-- add here

        return table

    # backwards compatibility - getter/setter property pairs
    @property
    def _skip_adaptive_update(self):
        """Get skip adaptive update flag from event handlers"""
        return self.event_handlers.get_skip_adaptive_update()

    @_skip_adaptive_update.setter
    def _skip_adaptive_update(self, value):
        """Set skip adaptive update flag in event handlers"""
        self.event_handlers.set_skip_adaptive_update(value)

    @property
    def _has_manual_changes(self):
        """Get manual changes flag from event handlers"""
        return self.event_handlers.get_has_manual_changes()

    @_has_manual_changes.setter
    def _has_manual_changes(self, value):
        """Set manual changes flag in event handlers"""
        self.event_handlers.set_has_manual_changes(value)
