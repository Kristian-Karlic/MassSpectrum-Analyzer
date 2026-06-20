import os
import pandas as pd
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QLabel,
)
from utils.style.style import EditorConstants

# Tuple indices for matched_fragments entries
_MZ = 0
_INTENSITY = 1
_MATCHED = 2
_ERROR_PPM = 3
_ION_NUMBER = 4
_ION_TYPE = 5
_FRAGMENT_SEQ = 6
_NEUTRAL_LOSS = 7
_CHARGE = 8
_ISOTOPE = 9
_COLOR = 10
_BASE_TYPE = 11
_MODIFIED_FRAGMENT = 12

# PSM metadata columns to carry into the long-format file (in order)
_PSM_META_COLS = [
    ("Group", "Group"),
    ("Replicate", "Replicate"),
    ("Spectrum file", "Spectrum file"),
    ("index", "index"),
    ("Peptide", "Peptide"),
    ("Modified Peptide", "Modified Peptide"),
    ("Parsed Modifications", "Parsed Modifications"),
    ("Charge", "Precursor.charge"),
]


class ExportOptionsDialog(QDialog):
    """Dialog for selecting export options including matched fragment details."""

    def __init__(self, ion_config=None, parent=None):
        super().__init__(parent)
        self.ion_config = ion_config
        self.setWindowTitle("Export Options")
        self.setMinimumWidth(400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.fragment_toggle = QCheckBox("Export matched fragments as companion CSV")
        self.fragment_toggle.setChecked(False)
        layout.addWidget(self.fragment_toggle)

        if self.ion_config is None:
            self.fragment_toggle.setEnabled(False)
            self.fragment_toggle.setToolTip(
                "Fragment data not available (run rescoring first)"
            )
        else:
            info = QLabel(
                "A separate <em>_fragments.csv</em> file will be saved alongside the main results.\n"
                "It contains one row per matched fragment ion, linked to the PSM by "
                "<em>spectrum_file</em> and <em>scan_index</em>. All ion types are included — filter downstream as needed."
            )
            info.setWordWrap(True)
            info.setStyleSheet("color: gray; font-size: 11px;")
            info.setEnabled(False)
            self.fragment_toggle.toggled.connect(info.setEnabled)
            layout.addWidget(info)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_button = QPushButton("OK")
        ok_button.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        ok_button.clicked.connect(self.accept)
        button_layout.addWidget(ok_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def include_fragments(self):
        """Return True if the user wants the companion fragment CSV."""
        return self.fragment_toggle.isChecked()


def build_fragment_long_format(debug_df):
    """Build a long-format DataFrame of matched fragment ions, one row per ion.

    Tuple indices in matched_fragments:
        [0] m/z  [1] intensity  [2] Matched  [3] error_ppm  [4] Ion Number
        [5] Ion Type  [6] Fragment Sequence  [7] Neutral Loss  [8] Charge
        [9] Isotope  [10] Color  [11] Base Type  [12] Modified Fragment

    Args:
        debug_df: DataFrame containing a 'matched_fragments' column (list of tuples).

    Returns:
        Long-format DataFrame with columns:
            spectrum_file, scan_index, peptide, modified_peptide,
            parsed_modifications, precursor_charge,
            base_type, ion_type, ion_number, fragment_sequence, modified_fragment,
            mz, intensity, charge, neutral_loss, isotope, error_ppm
    """
    if "matched_fragments" not in debug_df.columns:
        return pd.DataFrame()

    rows = []
    columns = list(debug_df.columns)
    col_idx = {col: pos for pos, col in enumerate(columns, start=1)}
    idx_matched = col_idx.get("matched_fragments")

    for row_tuple in debug_df.itertuples(index=False, name=None):
        row_dict = dict(zip(columns, row_tuple))
        fragments = (
            row_dict.get("matched_fragments", None) if idx_matched is not None else None
        )
        if not fragments:
            continue

        # Collect PSM-level metadata once per PSM
        meta = {}
        for src_col, dest_col in _PSM_META_COLS:
            meta[dest_col] = (
                row_dict.get(src_col, None) if src_col in debug_df.columns else None
            )

        for frag in fragments:
            if len(frag) < _ISOTOPE + 1:
                continue
            if frag[_MATCHED] == "No Match":
                continue

            base_type = (
                str(frag[_BASE_TYPE]).strip()
                if len(frag) > _BASE_TYPE and frag[_BASE_TYPE]
                else str(frag[_ION_TYPE])
            )

            modified_frag = (
                str(frag[_MODIFIED_FRAGMENT])
                if len(frag) > _MODIFIED_FRAGMENT
                and frag[_MODIFIED_FRAGMENT] is not None
                else (
                    str(frag[_FRAGMENT_SEQ]) if frag[_FRAGMENT_SEQ] is not None else ""
                )
            )

            fragment_row = {
                **meta,
                "base_type": base_type,
                "ion_type": str(frag[_ION_TYPE]) if frag[_ION_TYPE] is not None else "",
                "ion_number": frag[_ION_NUMBER],
                "fragment_sequence": (
                    str(frag[_FRAGMENT_SEQ]) if frag[_FRAGMENT_SEQ] is not None else ""
                ),
                "modified_fragment": modified_frag,
                "mz": round(float(frag[_MZ]), 5),
                "intensity": round(float(frag[_INTENSITY]), 2),
                "charge": int(frag[_CHARGE]) if frag[_CHARGE] is not None else 1,
                "neutral_loss": (
                    str(frag[_NEUTRAL_LOSS])
                    if frag[_NEUTRAL_LOSS] is not None
                    else "None"
                ),
                "isotope": int(frag[_ISOTOPE]),
                "error_ppm": (
                    round(float(frag[_ERROR_PPM]), 4)
                    if frag[_ERROR_PPM] is not None
                    else None
                ),
            }
            rows.append(fragment_row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def companion_fragment_path(main_csv_path):
    """Derive the companion fragment CSV path from the main results path.

    E.g. 'results.csv' -> 'results_fragments.csv'
    """
    base, ext = os.path.splitext(main_csv_path)
    return f"{base}_fragments{ext}"
