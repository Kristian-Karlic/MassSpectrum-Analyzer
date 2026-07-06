import importlib
import logging

# Silence matplotlib font_manager debug logs
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

_EXPORTS = {
    "calculate_fragment_ions": (
        "utils.peak_matching.peptide_fragmentation",
        "calculate_fragment_ions",
    ),
    "match_fragment_ions": (
        "utils.peak_matching.peptide_fragmentation",
        "match_fragment_ions",
    ),
    "match_fragment_ions_fast": (
        "utils.peak_matching.peptide_fragmentation",
        "match_fragment_ions_fast",
    ),
    "filter_ions": ("utils.peak_matching.peptide_fragmentation", "filter_ions"),
    "ColorDelegate": ("utils.tables.Color_selection", "ColorDelegate"),
    "MassSpecViewer": (
        "utils.spectrum_graph.mass_spec_viewer_widget",
        "MassSpecViewer",
    ),
    "PSMSummaryWidget": ("utils.tables.psm_summary_widget", "PSMSummaryWidget"),
    "DataframeViewerDialog": (
        "utils.spectrum_graph.classes.dataframe_viewer_dialog",
        "DataframeViewerDialog",
    ),
    "FileTypeUtils": ("utils.utilities", "FileTypeUtils"),
    "TableUtils": ("utils.utilities", "TableUtils"),
    "DataLoader": ("utils.utilities", "DataLoader"),
    "InputValidator": ("utils.utilities", "InputValidator"),
    "UIHelpers": ("utils.utilities", "UIHelpers"),
    "IonCollectionUtils": ("utils.utilities", "IonCollectionUtils"),
    "FileProcessingUtils": ("utils.utilities", "FileProcessingUtils"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
