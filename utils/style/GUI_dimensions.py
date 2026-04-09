"""
Centralized layout constants for flexible GUI sizing
All window sizing settings consolidated here for easy modification.
"""

class LayoutConstants:
    """Constants for GUI layout and sizing"""
    
    # Window size presets - used by WindowSizeManager
    # Modify these to adjust window sizes for different screen sizes
    WINDOW_PRESETS = {
        'small': {'width': 1200, 'height': 800},
        'medium': {'width': 1680, 'height': 900},
        'large': {'width': 1920, 'height': 980},
        'xlarge': {'width': 2560, 'height': 1440}
    }
    
    # Default size: 1680x900 centered on screen
    # Window constraints: Min 1680x780, Max 1920x980
    DEFAULT_PRESET = 'medium'
    
    # Start maximized? Set to False to use DEFAULT_PRESET size instead
    START_MAXIMIZED = False

    # Panel widths - Use minimums to allow resizing while preventing crushing
    # For 1920x1080: Left panel ~21% (400px), Right panel gets remaining space
    LEFT_PANEL_MIN_WIDTH = 350      # Minimum width before content gets cramped
    LEFT_PANEL_INITIAL_WIDTH = 400   # Starting width (can be resized by user)
    RIGHT_PANEL_MIN_WIDTH = 400      # Minimum for graphs/content

    # Minimum sizes for components
    MIN_TABLE_WIDTH = 300
    # Menu bar sizing
    MENU_BAR_HEIGHT = 30
    
    # Table sizing
    DEFAULT_TABLE_ROWS = 5
    MIN_TABLE_HEIGHT = 80
    
    # Margins and spacing
    WIDGET_MARGIN = 3
    LAYOUT_SPACING = 2