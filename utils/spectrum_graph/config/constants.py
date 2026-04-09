import math

import pandas as pd

# Re-export for backward compatibility — new code should import from .file_utils directly.
from .file_utils import get_save_filename, save_dataframe_to_file  # noqa: F401

class PlotConstants:
    # Font settings
    LABEL_FONT_SIZE = 16
    TICK_FONT_SIZE = 15
    DEFAULT_FONT_FAMILY = "Arial"

    # Axis styling
    AXIS_PEN_WIDTH = 2
    AXIS_PEN_COLOR = 'k'
    AXIS_TEXT_COLOR = 'black'
    TICK_LENGTH = 5

    # Plot ranges
    SPECTRUM_Y_RANGE = (0, 100)
    ERROR_Y_RANGE = (-11, 11)

    # Grid settings
    SHOW_GRID = False

    # Zoom / scroll limits
    MIN_X_RANGE = 0.5       # Minimum visible m/z width
    MIN_Y_RANGE = 1.0       # Minimum visible intensity width
    ZOOM_SCALE_FACTOR = 0.5  # Wheel zoom smoothness (fraction of default)

    # Target number of ticks for each axis type
    TARGET_X_TICKS = 8
    TARGET_SPECTRUM_Y_TICKS = 6

    @staticmethod
    def auto_tick_spacing(range_max, target_ticks=8):
        """
        Return a nice tick spacing for a given range.
        
        Args:
            range_max: The total range (max - min) to display
            target_ticks: Target number of ticks (default: 8)
        
        Returns:
            A "nice" tick spacing value (1, 2, 5, 10, 20, 50, etc.)
        """
        if range_max <= 0:
            return 1
            
        raw_spacing = range_max / target_ticks
        magnitude = 10 ** math.floor(math.log10(raw_spacing))
        residual = raw_spacing / magnitude

        if residual < 1.5:
            nice_spacing = 1 * magnitude
        elif residual < 3:
            nice_spacing = 2 * magnitude
        elif residual < 7:
            nice_spacing = 5 * magnitude
        else:
            nice_spacing = 10 * magnitude

        return nice_spacing

    @staticmethod
    def generate_tick_positions(range_min, range_max, tick_spacing):
        """Generate tick positions within the given range."""
        tick_start = int(range_min // tick_spacing) * tick_spacing
        tick_positions = []
        current_tick = tick_start
        while current_tick <= range_max + tick_spacing:
            if current_tick >= range_min - tick_spacing:
                tick_positions.append(current_tick)
            current_tick += tick_spacing
        return tick_positions

    @staticmethod
    def format_ticks(positions, tick_spacing):
        """Format tick positions with appropriate decimal places based on spacing."""
        if not positions:
            return []
        if tick_spacing < 0.1:
            return [[(pos, f"{pos:.2f}") for pos in positions]]
        elif tick_spacing < 1:
            return [[(pos, f"{pos:.1f}") for pos in positions]]
        else:
            return [[(pos, f"{pos:.0f}") for pos in positions]]

    # Y-axis alignment settings
    Y_AXIS_WIDTH = 80  
    MAJOR_TICK_SPACING_SPECTRUM = 20  
    MAJOR_TICK_SPACING_ERROR = 5     

    # Detection thresholds
    MOUSE_THRESHOLD_PIXELS = 10
    MZ_TOLERANCE = 0.01
    
    # Colors
    HIGHLIGHT_COLOR = 'yellow'
    HIGHLIGHT_WIDTH = 5
    LINKED_HIGHLIGHT_COLOR = 'cyan'
    LINKED_HIGHLIGHT_WIDTH = 6
    UNMATCHED_PEAK_ALPHA = 128
    
    # Font sizes
    PEPTIDE_FONT_SIZE = 25
    ANNOTATION_FONT_SIZE = 14
    MEASUREMENT_FONT_SIZE_DEFAULT = 20
    METADATA_FONT_SIZE = 12
    DEFAULT_FONT_SIZE = 12
    
    # Plot layout
    SPECTRUM_Y_LIMIT = 110
    
    # Measurement constants
    PEAK_LINE_WIDTH = 2
    
    # Peak measurement
    PEAK_MEASURE_HIGHLIGHT_WIDTH = 5
    
    # Tooltip settings
    TOOLTIP_OFFSET_X = 15
    TOOLTIP_OFFSET_Y = 15
    TOOLTIP_FOLLOW_INTERVAL_MS = 50

    # Peak annotation
    PEAK_LABEL_OFFSET = 10

    # Error scatter
    ERROR_SCATTER_SIZE = 10
    ERROR_SCATTER_HIGHLIGHT_SIZE = 12

    # Ion fragment line offsets (shared by all fragment-drawing methods)
    ION_FRAGMENT_OFFSETS = {
        'a': {'y_offset': -145, 'color_default': 'red'},
        'b': {'y_offset': -115, 'color_default': 'blue'},
        'c': {'y_offset': -90, 'color_default': 'green'},
        'd': {'y_offset': -165, 'color_default': 'teal'},
        'x': {'y_offset': 145, 'color_default': 'orange'},
        'y': {'y_offset': 115, 'color_default': 'purple'},
        'z': {'y_offset': 90, 'color_default': 'brown'},
        'w': {'y_offset': 65, 'color_default': 'darkcyan'},
        'v': {'y_offset': 165, 'color_default': 'magenta'},
    }


def matched_mask(df, monoisotopic_only=False):
    """Return a boolean Series selecting rows that are genuinely matched.

    Args:
        df: DataFrame with at least a 'Matched' column.
        monoisotopic_only: If True, also require Isotope == 0.
    """
    mask = df['Matched'].notna() & (df['Matched'] != 'No Match')
    if monoisotopic_only:
        mask = mask & (pd.to_numeric(df['Isotope'], errors='coerce') == 0)
    return mask
