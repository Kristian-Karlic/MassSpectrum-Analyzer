from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import os

# Get the root project directory (where GUI.py is located)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
assets_dir = os.path.join(project_root, "assets")

# Ensure paths use forward slashes and are absolute
red_cross_path = os.path.abspath(os.path.join(assets_dir, "red_cross.png")).replace(
    "\\", "/"
)
up_arrow_path = os.path.abspath(os.path.join(assets_dir, "up_arrow.png")).replace(
    "\\", "/"
)
down_arrow_path = os.path.abspath(os.path.join(assets_dir, "down_arrow.png")).replace(
    "\\", "/"
)


class ThemeManager:
    """Manages light and dark theme constants"""

    # Light theme colors
    LIGHT_THEME = {
        "BACKGROUND_COLOR": "#ffffff",
        "TEXT_COLOR": "#333333",
        "BORDER_COLOR": "#0d6efd",
        "HOVER_COLOR": "#e9ecef",
        "SELECTION_BACKGROUND": "#cfe2ff",
        "SELECTION_TEXT": "#333333",
        "HEADER_TEXT_COLOR": "#495057",
        "DISABLED_COLOR": "#6c757d",
        "SUCCESS_COLOR": "#198754",
        "DANGER_COLOR": "#dc3545",
        "DANGER_HOVER": "#c82333",
        "SUCCESS_HOVER": "#157a3b",
        "LIGHT_BLUE": "#86b7fe",
        "PRESSED_COLOR": "#dee2e6",
        # Graph/Plot specific colors
        "PLOT_BACKGROUND": "#ffffff",
        "PLOT_FOREGROUND": "#000000",
        "GRID_COLOR": "#cccccc",
        "UNMATCHED_PEAK_COLOR": "#808080",
        "ANNOTATION_BG": "#ffffff",
        "LEGEND_BG": "#ffffff",
        "LEGEND_BORDER": "#333333",
        # Gray scale
        "GRAY_50": "#f8f9fa",
        "GRAY_100": "#e9ecef",
        "GRAY_200": "#dee2e6",
        "GRAY_300": "#ced4da",
        "GRAY_400": "#adb5bd",
        "GRAY_500": "#6c757d",
        "GRAY_600": "#495057",
        "GRAY_700": "#343a40",
        "GRAY_800": "#212529",
        "GRAY_900": "#000000",
        # Ion tile colors
        "TILE_SELECTED_BG": "#d4edda",
        "TILE_SELECTED_BORDER": "#28a745",
        "TILE_SELECTED_TEXT": "#155724",
        "TILE_UNSELECTED_BG": "#f8d7da",
        "TILE_UNSELECTED_BORDER": "#dc3545",
        "TILE_UNSELECTED_TEXT": "#721c24",
        "TILE_SELECTED_HOVER": "#c3e6cb",
        "TILE_UNSELECTED_HOVER": "#f1b0b7",
        # Legacy aliases for compatibility
        "WHITE": "#ffffff",
        "BLACK": "#333333",
        "PRIMARY_BLUE": "#0d6efd",
        "SELECTION_BLUE": "#cfe2ff",
    }

    # Dark theme colors
    DARK_THEME = {
        "BACKGROUND_COLOR": "#212529",
        "TEXT_COLOR": "#ffffff",
        "BORDER_COLOR": "#4dabf7",
        "HOVER_COLOR": "#343a40",
        "SELECTION_BACKGROUND": "#495057",
        "SELECTION_TEXT": "#f8f9fa",
        "HEADER_TEXT_COLOR": "#adb5bd",
        "DISABLED_COLOR": "#6c757d",
        "SUCCESS_COLOR": "#20c997",
        "DANGER_COLOR": "#fd7e14",
        "DANGER_HOVER": "#e8590c",
        "SUCCESS_HOVER": "#12b886",
        "LIGHT_BLUE": "#74c0fc",
        "PRESSED_COLOR": "#718096",
        # Graph/Plot specific colors
        "PLOT_BACKGROUND": "#212529",
        "PLOT_FOREGROUND": "#e2e8f0",
        "GRID_COLOR": "#4a5568",
        "UNMATCHED_PEAK_COLOR": "#a0aec0",
        "ANNOTATION_BG": "#2d3748",
        "LEGEND_BG": "#2d3748",
        "LEGEND_BORDER": "#cbd5e0",
        # Gray scale (inverted for dark theme)
        "GRAY_50": "#343a40",
        "GRAY_100": "#495057",
        "GRAY_200": "#6c757d",
        "GRAY_300": "#adb5bd",
        "GRAY_400": "#ced4da",
        "GRAY_500": "#dee2e6",
        "GRAY_600": "#e9ecef",
        "GRAY_700": "#f1f3f4",
        "GRAY_800": "#f8f9fa",
        "GRAY_900": "#ffffff",
        # Ion tile colors
        "TILE_SELECTED_BG": "#1b4332",
        "TILE_SELECTED_BORDER": "#52b788",
        "TILE_SELECTED_TEXT": "#d8f3dc",
        "TILE_UNSELECTED_BG": "#3d1f28",
        "TILE_UNSELECTED_BORDER": "#e07080",
        "TILE_UNSELECTED_TEXT": "#f5c6cb",
        "TILE_SELECTED_HOVER": "#2d6a4f",
        "TILE_UNSELECTED_HOVER": "#5c2636",
        # Legacy aliases for compatibility
        "WHITE": "#1e1e1e",
        "BLACK": "#ffffff",
        "PRIMARY_BLUE": "#4dabf7",
        "SELECTION_BLUE": "#364fc7",
    }

    current_theme = "light"

    @classmethod
    def set_theme(cls, theme_name):
        cls.current_theme = theme_name

    @classmethod
    def get_color(cls, color_name):
        theme = cls.LIGHT_THEME if cls.current_theme == "light" else cls.DARK_THEME
        return theme.get(color_name, "#000000")


class _EditorConstantsMeta(type):
    """Provide dynamic color accessors (e.g., EditorConstants.GRAY_700())."""

    class _ThemeColorAccessor(str):
        def __new__(cls, color_name):
            value = ThemeManager.get_color(color_name)
            obj = str.__new__(cls, value)
            obj._color_name = color_name
            return obj

        def __call__(self):
            return ThemeManager.get_color(self._color_name)

    def __getattr__(cls, name):
        if name in cls._THEME_COLOR_KEYS:
            return cls._ThemeColorAccessor(name)
        raise AttributeError(f"type object '{cls.__name__}' has no attribute '{name}'")


class EditorConstants(metaclass=_EditorConstantsMeta):
    _THEME_COLOR_KEYS = set(ThemeManager.LIGHT_THEME) | set(ThemeManager.DARK_THEME)

    # FONT SETTINGS - NOW DYNAMIC
    @staticmethod
    def FONT_FAMILY():
        return getattr(EditorConstants, "_FONT_FAMILY", "Segoe UI")

    @staticmethod
    def FONT_SIZE():
        return getattr(EditorConstants, "_FONT_SIZE", "10pt")

    @staticmethod
    def BASE_FONT_SIZE():
        return getattr(EditorConstants, "_BASE_FONT_SIZE", 10)

    @staticmethod
    def HEADER_FONT_SIZE():
        return getattr(EditorConstants, "_HEADER_FONT_SIZE", 14)

    @staticmethod
    def TABLE_FONT_SIZE():
        return getattr(EditorConstants, "_TABLE_FONT_SIZE", 12)

    @staticmethod
    def MENU_FONT_SIZE():
        return getattr(EditorConstants, "_MENU_FONT_SIZE", 16)

    @staticmethod
    def CHECKBOX_FONT_SIZE():
        return getattr(EditorConstants, "_CHECKBOX_FONT_SIZE", 14)

    @staticmethod
    def BUTTON_FONT_SIZE():
        return getattr(EditorConstants, "_BUTTON_FONT_SIZE", 10)

    # FONT WEIGHTS - ADDED MISSING
    @staticmethod
    def FONT_WEIGHT_NORMAL():
        return getattr(EditorConstants, "_FONT_WEIGHT_NORMAL", "400")

    @staticmethod
    def FONT_WEIGHT_MEDIUM():
        return getattr(EditorConstants, "_FONT_WEIGHT_MEDIUM", "500")

    @staticmethod
    def FONT_WEIGHT_BOLD():
        return getattr(EditorConstants, "_FONT_WEIGHT_BOLD", "600")

    # SIZING CONSTANTS - NOW DYNAMIC
    @staticmethod
    def BORDER_WIDTH():
        return f"{getattr(EditorConstants, '_BORDER_WIDTH', 1)}px"

    @staticmethod
    def BORDER_WIDTH_FOCUS():
        return f"{getattr(EditorConstants, '_BORDER_WIDTH_FOCUS', 2)}px"

    @staticmethod
    def BORDER_RADIUS_SMALL():
        return getattr(EditorConstants, "_BORDER_RADIUS_SMALL", 2)

    @staticmethod
    def BORDER_RADIUS_MEDIUM():
        return getattr(EditorConstants, "_BORDER_RADIUS_MEDIUM", 4)

    @staticmethod
    def BORDER_RADIUS_LARGE():
        return getattr(EditorConstants, "_BORDER_RADIUS_LARGE", 6)

    # SPACING/PADDING - NOW DYNAMIC
    @staticmethod
    def PADDING_SMALL():
        return getattr(EditorConstants, "_PADDING_SMALL", "4px")

    @staticmethod
    def PADDING_MEDIUM():
        return getattr(EditorConstants, "_PADDING_MEDIUM", "6px")

    @staticmethod
    def PADDING_LARGE():
        return getattr(EditorConstants, "_PADDING_LARGE", "8px")

    @staticmethod
    def PADDING_XL():
        return getattr(EditorConstants, "_PADDING_XL", "12px")

    # BUTTON PADDING - ADDED MISSING
    @staticmethod
    def BUTTON_PADDING():
        return getattr(EditorConstants, "_BUTTON_PADDING", "6px 12px")

    @staticmethod
    def BUTTON_PADDING_SMALL():
        return getattr(EditorConstants, "_BUTTON_PADDING_SMALL", "4px 8px")

    # HEIGHT CONSTANTS - NOW DYNAMIC
    @staticmethod
    def HEADER_HEIGHT():
        return getattr(EditorConstants, "_HEADER_HEIGHT", 30)

    @staticmethod
    def BUTTON_HEIGHT():
        return getattr(EditorConstants, "_BUTTON_HEIGHT", 28)

    @staticmethod
    def EDITOR_MIN_HEIGHT():
        return getattr(EditorConstants, "_EDITOR_MIN_HEIGHT", 28)

    @staticmethod
    def CHECKBOX_HEIGHT():
        return getattr(EditorConstants, "_CHECKBOX_HEIGHT", 20)

    @staticmethod
    def SEARCH_BAR_HEIGHT():
        return getattr(EditorConstants, "_SEARCH_BAR_HEIGHT", 28)

    # ADDED MISSING HEIGHT CONSTANTS
    @staticmethod
    def HEADER_MIN_HEIGHT():
        return getattr(EditorConstants, "_HEADER_MIN_HEIGHT", 30)

    # WIDTH CONSTANTS - NOW DYNAMIC
    @staticmethod
    def SEARCH_BAR_WIDTH():
        return getattr(EditorConstants, "_SEARCH_BAR_WIDTH", 140)

    @staticmethod
    def BUTTON_MIN_WIDTH():
        return getattr(EditorConstants, "_BUTTON_MIN_WIDTH", 80)

    @staticmethod
    def CHECKBOX_SIZE():
        return getattr(EditorConstants, "_CHECKBOX_SIZE", 16)

    # ADDED MISSING WIDTH CONSTANTS
    @staticmethod
    def EDITOR_MIN_WIDTH():
        return getattr(EditorConstants, "_EDITOR_MIN_WIDTH", 80)

    @staticmethod
    def COMBO_MIN_WIDTH():
        return getattr(EditorConstants, "_COMBO_MIN_WIDTH", 120)

    @staticmethod
    def COMBO_DROPDOWN_WIDTH():
        return getattr(EditorConstants, "_COMBO_DROPDOWN_WIDTH", 20)

    # COLUMN WIDTHS - ADDED MISSING
    @staticmethod
    def NAME_COLUMN_WIDTH():
        return getattr(EditorConstants, "_NAME_COLUMN_WIDTH", 150)

    @staticmethod
    def MASS_COLUMN_WIDTH():
        return getattr(EditorConstants, "_MASS_COLUMN_WIDTH", 100)

    @staticmethod
    def HTML_NAME_COLUMN_WIDTH():
        return getattr(EditorConstants, "_HTML_NAME_COLUMN_WIDTH", 150)

    @staticmethod
    def COLOR_COLUMN_WIDTH():
        return getattr(EditorConstants, "_COLOR_COLUMN_WIDTH", 100)

    @staticmethod
    def BASE_ION_COLUMN_WIDTH():
        return getattr(EditorConstants, "_BASE_ION_COLUMN_WIDTH", 100)

    @staticmethod
    def SERIES_NAME_COLUMN_WIDTH():
        return getattr(EditorConstants, "_SERIES_NAME_COLUMN_WIDTH", 150)

    @staticmethod
    def MASS_OFFSET_COLUMN_WIDTH():
        return getattr(EditorConstants, "_MASS_OFFSET_COLUMN_WIDTH", 120)

    # SCROLLBAR PROPERTIES - ADDED MISSING
    @staticmethod
    def SCROLLBAR_WIDTH():
        return getattr(EditorConstants, "_SCROLLBAR_WIDTH", 12)

    @staticmethod
    def SCROLLBAR_HANDLE_MIN():
        return getattr(EditorConstants, "_SCROLLBAR_HANDLE_MIN", 20)

    @staticmethod
    def SCROLLBAR_MARGIN():
        return getattr(EditorConstants, "_SCROLLBAR_MARGIN", 2)

    @staticmethod
    def SCROLLBAR_BORDER_RADIUS():
        return getattr(EditorConstants, "_SCROLLBAR_BORDER_RADIUS", 6)

    # ICON SIZES - ADDED MISSING
    @staticmethod
    def ICON_SMALL():
        return getattr(EditorConstants, "_ICON_SMALL", 10)

    @staticmethod
    def ICON_MEDIUM():
        return getattr(EditorConstants, "_ICON_MEDIUM", 16)

    # LAYOUT SPACING - ADDED MISSING
    @staticmethod
    def CHECKBOX_SPACING():
        return getattr(EditorConstants, "_CHECKBOX_SPACING", 8)

    @staticmethod
    def CHECKBOX_MARGIN():
        return getattr(EditorConstants, "_CHECKBOX_MARGIN", "2px")

    @staticmethod
    def CHECKBOX_PADDING():
        return getattr(EditorConstants, "_CHECKBOX_PADDING", "4px")

    @staticmethod
    def TAB_PADDING():
        return getattr(EditorConstants, "_TAB_PADDING", "8px 16px")

    # SPLITTER - ADDED MISSING
    @staticmethod
    def SPLITTER_HANDLE_WIDTH():
        return getattr(EditorConstants, "_SPLITTER_HANDLE_WIDTH", 3)

    @staticmethod
    def SPLITTER_MARGIN():
        return getattr(EditorConstants, "_SPLITTER_MARGIN", "2px 0px")

    # GRAPH STYLING - NEW
    @staticmethod
    def GRAPH_AXIS_FONT_SIZE():
        return getattr(EditorConstants, "_GRAPH_AXIS_FONT_SIZE", 10)

    @staticmethod
    def GRAPH_LABEL_FONT_SIZE():
        return getattr(EditorConstants, "_GRAPH_LABEL_FONT_SIZE", 11)

    @staticmethod
    def FRAGMENT_LINE_HEIGHT():
        return getattr(EditorConstants, "_FRAGMENT_LINE_HEIGHT", 15)

    @staticmethod
    def FRAGMENT_LINE_OFFSET():
        return getattr(EditorConstants, "_FRAGMENT_LINE_OFFSET", 5)

    # Helper method for contrasting text on colored backgrounds
    @staticmethod
    def get_contrasting_text_color(bg_color_hex: str) -> str:
        """
        Returns appropriate text color (light or dark) for a given background color.
        Args:
            bg_color_hex: Background color in hex format (e.g., '#FF5733')
        Returns:
            Hex color string for text that contrasts well with background
        """
        bg_color = QColor(bg_color_hex)
        # Use theme-aware colors instead of hardcoded black/white
        return (
            EditorConstants.GRAY_900()
            if bg_color.lightness() > 128
            else EditorConstants.GRAY_50()
        )

    @staticmethod
    def MENU_BAR_HEIGHT():
        return getattr(EditorConstants, "_MENU_BAR_HEIGHT", 30)

    @staticmethod
    def PANEL_HEADER_HEIGHT():
        return getattr(EditorConstants, "_PANEL_HEADER_HEIGHT", 30)

    @staticmethod
    def TABLE_ROW_HEIGHT():
        return getattr(EditorConstants, "_TABLE_ROW_HEIGHT", 36)

    @staticmethod
    def TAB_HEIGHT():
        return getattr(EditorConstants, "_TAB_HEIGHT", 30)

    @staticmethod
    def PROGRESS_BAR_HEIGHT():
        return getattr(EditorConstants, "_PROGRESS_BAR_HEIGHT", 20)

    @staticmethod
    def DIALOG_BUTTON_HEIGHT():
        return getattr(EditorConstants, "_DIALOG_BUTTON_HEIGHT", 30)

    #  Missing width constants
    @staticmethod
    def LINEEDIT_MIN_WIDTH():
        return getattr(EditorConstants, "_LINEEDIT_MIN_WIDTH", 80)

    # UTILITY METHODS
    @staticmethod
    def get_font_string(weight="normal"):
        weight_map = {
            "normal": EditorConstants.FONT_WEIGHT_NORMAL(),
            "medium": EditorConstants.FONT_WEIGHT_MEDIUM(),
            "bold": EditorConstants.FONT_WEIGHT_BOLD(),
        }
        return f'font-family: "{EditorConstants.FONT_FAMILY()}", "Arial", sans-serif; font-size: {EditorConstants.FONT_SIZE()}; font-weight: {weight_map.get(weight, EditorConstants.FONT_WEIGHT_NORMAL())};'

    @staticmethod
    def get_border_string(color=None, width=None, radius=None):
        border_color = color or EditorConstants.BORDER_COLOR()
        border_width = width or EditorConstants.BORDER_WIDTH()
        border_str = f"border: {border_width} solid {border_color};"
        if radius is not None:
            border_str += f" border-radius: {radius}px;"
        return border_str

    @staticmethod
    def get_hover_style(bg_color=None, border_color=None):
        """Generate hover style"""
        bg = bg_color or EditorConstants.HOVER_COLOR()
        border = border_color or EditorConstants.LIGHT_BLUE()
        return f"background-color: {bg}; border-color: {border};"

    @staticmethod
    def get_focus_style(border_color=None, border_width=None):
        """Generate focus style"""
        color = border_color or EditorConstants.PRIMARY_BLUE()
        width = border_width or EditorConstants.BORDER_WIDTH_FOCUS()
        return f"border-color: {color}; border-width: {width};"

    @staticmethod
    def get_progress_bar_style():
        """Generate progress bar styling using constants"""
        return f"""
            QProgressBar {{
                background-color: {EditorConstants.GRAY_100()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), EditorConstants.BORDER_WIDTH(), EditorConstants.BORDER_RADIUS_MEDIUM())}
                text-align: center;
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.BASE_FONT_SIZE()}px;
                min-height: {EditorConstants.PROGRESS_BAR_HEIGHT()}px;
                max-height: {EditorConstants.PROGRESS_BAR_HEIGHT()}px;
            }}
            
            QProgressBar::chunk {{
                background-color: {EditorConstants.PRIMARY_BLUE()};
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
                margin: 1px;
            }}
            
            QProgressBar::chunk:indeterminate {{
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {EditorConstants.GRAY_300()},
                    stop: 0.4 {EditorConstants.PRIMARY_BLUE()},
                    stop: 0.6 {EditorConstants.PRIMARY_BLUE()},
                    stop: 1 {EditorConstants.GRAY_300()});
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
            }}
        """

    # ENHANCED STYLE GETTERS FROM OLD CODE
    @staticmethod
    def get_lineedit_style():
        """Generate QLineEdit stylesheet with current constants"""
        return f"""
            QLineEdit {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_300(), EditorConstants.BORDER_WIDTH(), EditorConstants.BORDER_RADIUS_MEDIUM())}
                padding: {EditorConstants.PADDING_MEDIUM()} {EditorConstants.PADDING_XL()};
                {EditorConstants.get_font_string()}
                selection-background-color: {EditorConstants.SELECTION_BACKGROUND()};
                selection-color: {EditorConstants.SELECTION_TEXT()};
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
                min-width: {EditorConstants.EDITOR_MIN_WIDTH()}px;
            }}
            QLineEdit:focus {{
                {EditorConstants.get_focus_style()}
            }}
        """

    @staticmethod
    def get_combobox_style():
        """Generate QComboBox stylesheet with current constants - ENHANCED for better search integration"""
        return f"""
            QComboBox {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_300(), EditorConstants.BORDER_WIDTH(), EditorConstants.BORDER_RADIUS_MEDIUM())}
                padding: {EditorConstants.PADDING_SMALL()} {EditorConstants.PADDING_LARGE()};
                {EditorConstants.get_font_string()}
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
                min-width: {EditorConstants.COMBO_MIN_WIDTH()}px;
            }}
            QComboBox:hover {{
                {EditorConstants.get_hover_style(border_color=EditorConstants.LIGHT_BLUE())}
            }}
            QComboBox:focus {{
                {EditorConstants.get_focus_style()}
            }}
            QComboBox:editable {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {EditorConstants.COMBO_DROPDOWN_WIDTH()}px;
                background-color: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({down_arrow_path});
                width: {EditorConstants.ICON_SMALL()}px;
                height: {EditorConstants.ICON_SMALL()}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                selection-background-color: {EditorConstants.HOVER_COLOR()};
                selection-color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
                outline: none;
                padding: {EditorConstants.PADDING_SMALL()};
            }}
            QComboBox QAbstractItemView::item {{
                padding: {EditorConstants.PADDING_SMALL()} {EditorConstants.PADDING_MEDIUM()};
                border: none;
                min-height: 20px;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {EditorConstants.HOVER_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {EditorConstants.SELECTION_BACKGROUND()};
                color: {EditorConstants.SELECTION_TEXT()};
            }}
            QComboBox QLineEdit {{
                background-color: transparent;
                border: none;
                color: {EditorConstants.TEXT_COLOR()};
                selection-background-color: {EditorConstants.SELECTION_BACKGROUND()};
                selection-color: {EditorConstants.SELECTION_TEXT()};
            }}
        """

    @staticmethod
    def get_pushbutton_style(style="primary"):
        """Generate QPushButton stylesheet - multiple style variants"""
        if style == "primary":
            bg_color = EditorConstants.GRAY_50()
            border_color = EditorConstants.GRAY_200()
            hover_bg = EditorConstants.HOVER_COLOR()
            text_color = EditorConstants.TEXT_COLOR()
            padding = EditorConstants.BUTTON_PADDING()
            font_weight = "medium"
        elif style == "danger":
            bg_color = EditorConstants.DANGER_COLOR()
            border_color = EditorConstants.DANGER_COLOR()
            hover_bg = EditorConstants.DANGER_HOVER()
            text_color = EditorConstants.WHITE()
            padding = EditorConstants.BUTTON_PADDING_SMALL()
            font_weight = "normal"
        elif style == "success":
            bg_color = EditorConstants.SUCCESS_COLOR()
            border_color = EditorConstants.SUCCESS_COLOR()
            hover_bg = EditorConstants.SUCCESS_HOVER()
            text_color = EditorConstants.WHITE()
            padding = EditorConstants.BUTTON_PADDING_SMALL()
            font_weight = "normal"
        else:  # secondary/delegate style
            bg_color = EditorConstants.BACKGROUND_COLOR()
            border_color = EditorConstants.BORDER_COLOR()
            hover_bg = EditorConstants.HOVER_COLOR()
            text_color = EditorConstants.TEXT_COLOR()
            padding = EditorConstants.BUTTON_PADDING_SMALL()
            font_weight = "normal"

        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                {EditorConstants.get_border_string(border_color, EditorConstants.BORDER_WIDTH(), EditorConstants.BORDER_RADIUS_MEDIUM())}
                padding: {padding};
                {EditorConstants.get_font_string(font_weight)}
                min-height: {EditorConstants.BUTTON_HEIGHT()}px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {EditorConstants.PRESSED_COLOR()};
            }}
            QPushButton:disabled {{
                background-color: {EditorConstants.GRAY_50()};
                color: {EditorConstants.DISABLED_COLOR()};
                border-color: {EditorConstants.GRAY_200()};
            }}
        """

    @staticmethod
    def get_scrollbar_style():
        """Generate unified scrollbar style"""
        return f"""
            QScrollBar:vertical {{
                border: none;
                background: {EditorConstants.GRAY_50()};
                width: {EditorConstants.SCROLLBAR_WIDTH()}px;
                margin: 0px;
                border-radius: {EditorConstants.SCROLLBAR_BORDER_RADIUS()}px;
            }}
            QScrollBar::handle:vertical {{
                background: {EditorConstants.GRAY_300()};
                min-height: {EditorConstants.SCROLLBAR_HANDLE_MIN()}px;
                border-radius: {EditorConstants.SCROLLBAR_BORDER_RADIUS()}px;
                margin: {EditorConstants.SCROLLBAR_MARGIN()}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {EditorConstants.GRAY_400()};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background-color: {EditorConstants.GRAY_50()};
            }}
            
            QScrollBar:horizontal {{
                border: none;
                background: {EditorConstants.GRAY_50()};
                height: {EditorConstants.SCROLLBAR_WIDTH()}px;
                margin: 0px;
                border-radius: {EditorConstants.SCROLLBAR_BORDER_RADIUS()}px;
            }}
            QScrollBar::handle:horizontal {{
                background: {EditorConstants.GRAY_300()};
                min-width: {EditorConstants.SCROLLBAR_HANDLE_MIN()}px;
                border-radius: {EditorConstants.SCROLLBAR_BORDER_RADIUS()}px;
                margin: {EditorConstants.SCROLLBAR_MARGIN()}px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {EditorConstants.GRAY_400()};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background-color: {EditorConstants.GRAY_50()};
            }}
        """

    @staticmethod
    def get_table_style():
        """Generate complete table style with dynamic sizing"""
        return f"""
            QTableWidget {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                gridline-color: {EditorConstants.HOVER_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                selection-background-color: {EditorConstants.HOVER_COLOR()};
                selection-color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.TABLE_FONT_SIZE()}px;
            }}
            QTableWidget::item {{
                padding: {EditorConstants.PADDING_MEDIUM()};
                border: none;
                color: {EditorConstants.TEXT_COLOR()};
                min-height: {EditorConstants.TABLE_ROW_HEIGHT()}px;
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.TABLE_FONT_SIZE()}px;
            }}
            QTableWidget::item:selected {{
                background-color: {EditorConstants.HOVER_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
            }}
            QTableWidget QLineEdit {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                border: 1px solid {EditorConstants.GRAY_400()};
                border-radius: 0px;
                padding: 0px 2px;
                margin: 0px;
                min-height: 0px;
                min-width: 0px;
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.TABLE_FONT_SIZE()}px;
            }}
            QTableWidget QDoubleSpinBox, QTableWidget QSpinBox {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                border: 1px solid {EditorConstants.GRAY_400()};
                border-radius: 0px;
                padding: 0px 2px;
                margin: 0px;
                min-height: 0px;
                min-width: 0px;
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.TABLE_FONT_SIZE()}px;
            }}
            QHeaderView::section {{
                background-color: {EditorConstants.GRAY_50()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                padding: {EditorConstants.PADDING_LARGE()};
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                {EditorConstants.get_font_string("bold")}
                font-size: {EditorConstants.HEADER_FONT_SIZE()}px;
                min-height: {EditorConstants.HEADER_MIN_HEIGHT()}px;
                max-height: {EditorConstants.HEADER_MIN_HEIGHT() + 5}px;
            }}
            QHeaderView::section:hover {{
                background-color: {EditorConstants.HOVER_COLOR()};
            }}
            QTableCornerButton::section {{
                background-color: {EditorConstants.GRAY_50()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
            }}
            {EditorConstants.get_scrollbar_style()}
        """

    @staticmethod
    def get_checkbox_style():
        """Get enhanced checkbox styling"""
        return f"""
            QCheckBox {{
                background-color: transparent;
                color: {EditorConstants.TEXT_COLOR()};
                spacing: {EditorConstants.CHECKBOX_SPACING()}px;
                {EditorConstants.get_font_string()}
                font-size: {EditorConstants.CHECKBOX_FONT_SIZE()}px;
                padding: {EditorConstants.CHECKBOX_PADDING()};
                margin: {EditorConstants.CHECKBOX_MARGIN()};
                outline: none;
                min-height: {EditorConstants.CHECKBOX_HEIGHT()}px;
            }}

            QCheckBox::indicator {{
                width: {EditorConstants.ICON_MEDIUM()}px;
                height: {EditorConstants.ICON_MEDIUM()}px;
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border: 1px solid {EditorConstants.GRAY_400()};
            }}

            QCheckBox::indicator:unchecked {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border: 1px solid {EditorConstants.GRAY_400()};
            }}

            QCheckBox::indicator:checked {{
                background-color: {EditorConstants.PRIMARY_BLUE()};
                border: 1px solid {EditorConstants.PRIMARY_BLUE()};
                image: url({red_cross_path});
            }}

            /* Keep width constant on hover to prevent clipping */
            QCheckBox::indicator:hover {{
                border-color: {EditorConstants.LIGHT_BLUE()};
            }}

            QCheckBox::indicator:focus {{
                border-color: {EditorConstants.PRIMARY_BLUE()};
                border-width: 2px;
            }}

            /* Let spacing control gap; avoid extra text padding that can clip */
            QCheckBox::text {{
                color: {EditorConstants.TEXT_COLOR()};
                background-color: transparent;
                {EditorConstants.get_font_string()}
            }}
        """

    @staticmethod
    def get_spinbox_style():
        """Generate spinbox styling using constants"""
        return f"""
            QSpinBox {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border: 1px solid {EditorConstants.GRAY_300()};
                border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                padding: {EditorConstants.PADDING_SMALL()};
                color: {EditorConstants.TEXT_COLOR()};
                font-size: {EditorConstants.TABLE_FONT_SIZE()}px;
                {EditorConstants.get_font_string()}
                min-height: {EditorConstants.EDITOR_MIN_HEIGHT()}px;
                min-width: {EditorConstants.LINEEDIT_MIN_WIDTH()}px;
            }}
            
            QSpinBox:focus {{
                border-color: {EditorConstants.PRIMARY_BLUE()};
                border-width: 2px;
            }}
            
            QSpinBox::up-button, QSpinBox::down-button {{
                background-color: {EditorConstants.GRAY_50()};
                width: {EditorConstants.COMBO_DROPDOWN_WIDTH()}px;
                height: {EditorConstants.PADDING_XL()};
                border: none;
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
            }}
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {EditorConstants.HOVER_COLOR()};
            }}
            
            QSpinBox::up-arrow {{
                image: url({up_arrow_path});
                width: {EditorConstants.ICON_SMALL()}px;
                height: {EditorConstants.ICON_SMALL()}px;
            }}
            
            QSpinBox::down-arrow {{
                image: url({down_arrow_path});
                width: {EditorConstants.ICON_SMALL()}px;
                height: {EditorConstants.ICON_SMALL()}px;
            }}
        """

    @staticmethod
    def get_groupbox_style():
        """Generate group box styling using constants"""
        return f"""
            QGroupBox {{
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), EditorConstants.BORDER_WIDTH_FOCUS(), EditorConstants.BORDER_RADIUS_LARGE())}
                margin-top: 1ex;
                {EditorConstants.get_font_string("bold")}
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {EditorConstants.ICON_SMALL()}px;
                padding: 0 {EditorConstants.PADDING_LARGE()} 0 {EditorConstants.PADDING_LARGE()};
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                {EditorConstants.get_font_string()}
            }}
        """

    @staticmethod
    def get_tab_style():
        """Generate tab widget styling using constants"""
        return f"""
            QTabWidget::pane {{
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QTabBar::tab {{
                background-color: {EditorConstants.GRAY_50()};
                color: {EditorConstants.TEXT_COLOR()};
                padding: {EditorConstants.TAB_PADDING()};
                margin-right: {EditorConstants.BORDER_RADIUS_SMALL()}px;
                border-top-left-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                border-top-right-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                border-bottom: none;
                {EditorConstants.get_font_string()}
            }}
            QTabBar::tab:selected {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                border-bottom: {EditorConstants.BORDER_WIDTH()} solid {EditorConstants.BACKGROUND_COLOR()};
            }}
            QTabBar::tab:hover {{
                background-color: {EditorConstants.HOVER_COLOR()};
            }}
        """

    @staticmethod
    def get_menu_style():
        return f"""
        QMenuBar {{
            background-color: {EditorConstants.BACKGROUND_COLOR()};
            color: {EditorConstants.TEXT_COLOR()};
            border: none;
            font-family: {EditorConstants.FONT_FAMILY()};
            font-size: {EditorConstants.MENU_FONT_SIZE()}px;  /* Control menu bar font size */
            font-weight: normal;
            padding: 2px;
        }}
        
        QMenuBar::item {{
            background-color: transparent;
            color: {EditorConstants.TEXT_COLOR()};
            padding: 4px 8px;
            font-size: {EditorConstants.MENU_FONT_SIZE()}px;  /* Control menu item font size */
            border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
        }}
        
        QMenuBar::item:selected {{
            background-color: {EditorConstants.HOVER_COLOR()};
            color: {EditorConstants.TEXT_COLOR()};
        }}
        
        QMenuBar::item:pressed {{
            background-color: {EditorConstants.PRIMARY_BLUE()};
            color: {EditorConstants.WHITE()};
        }}
        
        QMenu {{
            background-color: {EditorConstants.BACKGROUND_COLOR()};
            color: {EditorConstants.TEXT_COLOR()};
            border: 1px solid {EditorConstants.GRAY_300()};
            border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
            font-family: {EditorConstants.FONT_FAMILY()};
            font-size: {EditorConstants.MENU_FONT_SIZE()}px;  /* Control dropdown menu font size */
            padding: 2px;
        }}
        
        QMenu::item {{
            background-color: transparent;
            color: {EditorConstants.TEXT_COLOR()};
            padding: 6px 12px;
            font-size: {EditorConstants.MENU_FONT_SIZE()}px;  /* Control dropdown item font size */
            border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
            margin: 1px;
        }}
        
        QMenu::item:selected {{
            background-color: {EditorConstants.HOVER_COLOR()};
            color: {EditorConstants.TEXT_COLOR()};
        }}
        
        QMenu::separator {{
            height: 1px;
            background-color: {EditorConstants.GRAY_300()};
            margin: 2px 0px;
        }}
        """


class StyleSheet:
    @staticmethod
    def apply_theme(theme_name):
        """Apply a theme and return the complete stylesheet"""
        ThemeManager.set_theme(theme_name)
        return StyleSheet.build_gui_style()

    @staticmethod
    def get_splitter_style():
        """Generate splitter styling using constants"""
        return f"""
            QSplitter {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            
            QSplitter::handle {{
                background-color: {EditorConstants.HOVER_COLOR()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_SMALL())}
            }}
            
            QSplitter::handle:horizontal {{
                width: {EditorConstants.SPLITTER_HANDLE_WIDTH()}px;
                margin: {EditorConstants.SPLITTER_MARGIN()};
            }}
            
            QSplitter::handle:hover {{
                background-color: {EditorConstants.PRIMARY_BLUE()};
            }}
            
            QSplitter::handle:pressed {{
                background-color: {EditorConstants.PRIMARY_BLUE()};
            }}
        """

    @staticmethod
    def get_label_style():
        """Generate label styling using constants"""
        return f"""
            QLabel {{
                color: {EditorConstants.TEXT_COLOR()};
                background-color: transparent;
                {EditorConstants.get_font_string()}
            }}
        """

    @staticmethod
    def get_scrollarea_style():
        """Generate scroll area styling using constants"""
        return f"""
            QScrollArea {{
                border: none;
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QWidget#scrollAreaWidgetContents {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
            }}
            {EditorConstants.get_scrollbar_style()}
        """

    @staticmethod
    def get_dialog_style():
        """Generate dialog styling using constants"""
        return f"""
            QDialog {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
        """

    @staticmethod
    def get_widget_style():
        """Generate base widget styling using constants"""
        return f"""
            QWidget {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                {EditorConstants.get_font_string()}
                color: {EditorConstants.TEXT_COLOR()};
            }}
        """

    @staticmethod
    def build_gui_style():
        """Build comprehensive GUI stylesheet"""
        return f"""
        /* Main Application Styling */
        * {{
            {EditorConstants.get_font_string()}
        }}
        
        {StyleSheet.get_widget_style()}
        
        /* Enhanced MenuBar and Menu Styling */
        {EditorConstants.get_menu_style()}
        
        /* Enhanced Button Styling */
        {EditorConstants.get_pushbutton_style("primary")}
        
        /* Enhanced Table Styling */
        {EditorConstants.get_table_style()}
        
        /* Enhanced Checkbox Styling */
        {EditorConstants.get_checkbox_style()}
        
        /* Enhanced ComboBox Styling */
        {EditorConstants.get_combobox_style()}
        
        /* Enhanced LineEdit Styling */
        {EditorConstants.get_lineedit_style()}
        
        /* Enhanced SpinBox Styling */
        {EditorConstants.get_spinbox_style()}
        
        /* Tab Styling */
        {EditorConstants.get_tab_style()}
        
        /* Label Styling */
        {StyleSheet.get_label_style()}
        
        /* GroupBox Styling */
        {EditorConstants.get_groupbox_style()}
        
        /* ScrollArea Styling */
        {StyleSheet.get_scrollarea_style()}
        
        /* Dialog Styling */
        {StyleSheet.get_dialog_style()}
        
        /* Splitter Styling */
        {StyleSheet.get_splitter_style()}
        """

    @staticmethod
    def get_section_header_style():
        """Get section header styling with proper font size"""
        return f"""
            QLabel[objectName="section_header"] {{
                {EditorConstants.get_font_string("bold")}
                font-size: {EditorConstants.HEADER_FONT_SIZE()}px;
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                background-color: {EditorConstants.GRAY_100()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_MEDIUM())}
                padding: 3px {EditorConstants.PADDING_LARGE()};
                margin: 2px 0px;
                min-height: {EditorConstants.HEADER_MIN_HEIGHT() - 8}px;
                max-height: {EditorConstants.HEADER_MIN_HEIGHT()}px;
            }}
        """

    @staticmethod
    def get_panel_header_style():
        """Get panel header styling with dynamic sizing"""
        return f"""
            QFrame {{
                background-color: {EditorConstants.GRAY_50()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200())}
                border-bottom: none;
                min-height: {EditorConstants.PANEL_HEADER_HEIGHT()}px;
                max-height: {EditorConstants.PANEL_HEADER_HEIGHT()}px;
            }}
            QLabel {{
                {EditorConstants.get_font_string("bold")}
                font-size: {EditorConstants.HEADER_FONT_SIZE()}px;
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """

    @staticmethod
    def apply_table_styling(table):
        """Apply enhanced table styling to a QTableWidget"""
        table.setStyleSheet(EditorConstants.get_table_style())

        # Set row height based on font size
        table.verticalHeader().setDefaultSectionSize(
            EditorConstants.TABLE_FONT_SIZE() + 24
        )

        # Set header height
        if hasattr(table.horizontalHeader(), "setMinimumSectionSize"):
            table.horizontalHeader().setMinimumSectionSize(
                EditorConstants.HEADER_HEIGHT() - 5
            )

        # IMPORTANT: Disable alternating row colors programmatically
        table.setAlternatingRowColors(False)

        # Ensure all existing items have consistent styling
        # Skip items with custom backgrounds (e.g. Labile column colours)
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item and item.background().style() == Qt.BrushStyle.NoBrush:
                    item.setForeground(QColor(EditorConstants.TEXT_COLOR()))


class DelegateStyles:
    """Enhanced styling for table delegates and custom widgets"""

    @staticmethod
    def apply_combobox_style(widget):
        """Apply consistent combo box styling"""
        widget.setStyleSheet(EditorConstants.get_combobox_style())
