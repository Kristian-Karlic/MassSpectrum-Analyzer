import pandas as pd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QGroupBox,
    QScrollArea, QPushButton, QWidget, QLabel
)
from PyQt6.QtCore import Qt
from utils.style.style import EditorConstants


class ExportOptionsDialog(QDialog):
    """Dialog for selecting export options including matched fragment details."""

    def __init__(self, ion_config=None, parent=None):
        super().__init__(parent)
        self.ion_config = ion_config
        self.group_checkboxes = []  # List of (category, ion_name, QCheckBox)
        self.setWindowTitle("Export Options")
        self.setMinimumWidth(400)
        self.setMinimumHeight(350)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Master toggle
        self.master_toggle = QCheckBox("Include matched fragment details")
        self.master_toggle.setChecked(False)
        self.master_toggle.toggled.connect(self._on_master_toggled)
        layout.addWidget(self.master_toggle)

        # If no ion config, disable fragment options entirely
        if self.ion_config is None:
            self.master_toggle.setEnabled(False)
            self.master_toggle.setToolTip("Fragment data not available (run rescoring first)")

        # Scroll area for ion checkboxes
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)

        if self.ion_config is not None:
            self._build_ion_groups()

        self.scroll_layout.addStretch()
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_area.setEnabled(False)
        layout.addWidget(self.scroll_area)

        # OK / Cancel buttons
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

    def _build_ion_groups(self):
        """Build checkbox groups from ion_config."""
        selected_ions = self.ion_config.get('selected_ions', [])
        selected_internal = self.ion_config.get('selected_internal_ions', [])
        custom_series = self.ion_config.get('custom_ion_series', [])
        diagnostic_ions = self.ion_config.get('diagnostic_ions', [])

        # Categorize selected_ions
        standard_ions = []
        neutral_loss_ions = []
        special_no_dash = {'z+1', 'c-1', 'MH'}

        for ion in selected_ions:
            if ion in special_no_dash or '-' not in ion:
                standard_ions.append(ion)
            else:
                neutral_loss_ions.append(ion)

        # Standard ions group
        if standard_ions:
            self._add_group("Standard Ions", [('standard', ion) for ion in standard_ions])

        # Neutral loss ions group
        if neutral_loss_ions:
            self._add_group("Neutral Loss Ions", [('neutral_loss', ion) for ion in neutral_loss_ions])

        # Internal ions group
        if selected_internal:
            internal_items = []
            for ion in selected_internal:
                prefixed = ion if ion.startswith('int-') else f'int-{ion}'
                internal_items.append(('internal', prefixed))
            self._add_group("Internal Ions", internal_items)

        # Custom ion series group
        if custom_series:
            custom_items = []
            for cs in custom_series:
                name = cs.get('Series Name', cs.get('name', ''))
                if name:
                    custom_items.append(('custom', name))
            if custom_items:
                self._add_group("Custom Ion Series", custom_items)

        # Diagnostic ions group
        if diagnostic_ions:
            self._add_group("Diagnostic Ions", [('diagnostic', 'diagnostic')])

        # Mod-NL group — granular per NL-type + base-ion sub-types
        mod_nl_subtypes = self.ion_config.get('mod_nl_subtypes', [])
        has_mod_nl = self.ion_config.get('has_mod_nl', False)
        if has_mod_nl and mod_nl_subtypes:
            mod_nl_items = [('mod_nl', subtype) for subtype in mod_nl_subtypes]
            self._add_group("Modification Neutral Losses", mod_nl_items)
        elif has_mod_nl:
            # Fallback: single bucket if no subtypes were discovered
            self._add_group("Modification Neutral Losses", [('mod_nl', 'Mod-NL')])

    def _add_group(self, title, items):
        """Add a checkbox group to the scroll area."""
        group_box = QGroupBox(title)
        group_layout = QVBoxLayout(group_box)

        for category, ion_name in items:
            cb = QCheckBox(ion_name)
            cb.setChecked(True)
            group_layout.addWidget(cb)
            self.group_checkboxes.append((category, ion_name, cb))

        self.scroll_layout.addWidget(group_box)

    def _on_master_toggled(self, checked):
        """Enable/disable all ion checkboxes based on master toggle."""
        self.scroll_area.setEnabled(checked)

    def get_selected_groups(self):
        """Return list of (category, ion_name) for checked items.
        Returns [] if master toggle is off."""
        if not self.master_toggle.isChecked():
            return []
        return [(cat, name) for cat, name, cb in self.group_checkboxes if cb.isChecked()]


def build_fragment_columns(debug_df, selected_groups):
    """Build per-ion-type fragment detail columns from matched_fragments.

    Args:
        debug_df: DataFrame with 'matched_fragments' column (list of tuples).
        selected_groups: List of (category, ion_name) from ExportOptionsDialog.

    Returns:
        DataFrame with fragment detail columns, indexed to match debug_df.
    """
    # Tuple indices:
    # [0] m/z, [1] intensity, [2] Matched, [4] Ion Number, [5] Ion Type,
    # [7] Neutral Loss, [8] Charge, [9] Isotope

    if 'matched_fragments' not in debug_df.columns:
        return pd.DataFrame(index=debug_df.index)

    # For custom ions, do a first pass to discover neutral loss variants
    custom_names = {name for cat, name in selected_groups if cat == 'custom'}
    custom_nl_variants = {name: set() for name in custom_names}

    if custom_names:
        for fragments in debug_df['matched_fragments']:
            if not fragments:
                continue
            for frag in fragments:
                if len(frag) < 10:
                    continue
                ion_type = frag[5]
                isotope = frag[9]
                if isotope != 0:
                    continue
                matched = frag[2]
                if matched == "No Match":
                    continue
                for cname in custom_names:
                    if ion_type.startswith(cname + '-') and ion_type != cname:
                        custom_nl_variants[cname].add(ion_type)

    # Build the full list of column sets to generate
    column_specs = []  # List of (prefix, filter_func)

    for category, ion_name in selected_groups:
        if category == 'standard':
            column_specs.append((ion_name, _make_standard_filter(ion_name)))
        elif category == 'neutral_loss':
            column_specs.append((ion_name, _make_neutral_loss_filter(ion_name)))
        elif category == 'internal':
            column_specs.append((ion_name, _make_internal_filter(ion_name)))
        elif category == 'custom':
            # Base custom matches (no neutral loss)
            column_specs.append((ion_name, _make_custom_base_filter(ion_name)))
            # Neutral loss variants discovered
            for variant in sorted(custom_nl_variants.get(ion_name, [])):
                column_specs.append((variant, _make_neutral_loss_filter(variant)))
        elif category == 'diagnostic':
            column_specs.append(('diagnostic', _make_diagnostic_filter()))
        elif category == 'mod_nl':
            if ion_name == 'Mod-NL':
                # Legacy single-bucket fallback
                column_specs.append(('Mod-NL', _make_mod_nl_filter()))
            else:
                # Granular: ion_name is e.g. 'ModNL1-y', 'LabileLoss-b'
                nl_label, base_type = ion_name.split('-', 1)
                column_specs.append((ion_name, _make_mod_nl_granular_filter(nl_label, base_type)))

    # Process all rows
    result_data = {f'{prefix}-matched': [] for prefix, _ in column_specs}
    result_data.update({f'{prefix}-matched-mz': [] for prefix, _ in column_specs})
    result_data.update({f'{prefix}-matched-intensity': [] for prefix, _ in column_specs})

    for fragments in debug_df['matched_fragments']:
        if not fragments:
            for prefix, _ in column_specs:
                result_data[f'{prefix}-matched'].append('')
                result_data[f'{prefix}-matched-mz'].append('')
                result_data[f'{prefix}-matched-intensity'].append('')
            continue

        # Pre-filter to only matched, monoisotopic fragments
        matched_frags = []
        for frag in fragments:
            if len(frag) < 10:
                continue
            if frag[2] == "No Match":
                continue
            if frag[9] != 0:  # Isotope != 0
                continue
            matched_frags.append(frag)

        for prefix, filter_func in column_specs:
            hits = filter_func(matched_frags)
            if hits:
                ids = []
                mzs = []
                intensities = []
                for frag in hits:
                    ids.append(_format_fragment_id(
                        frag,
                        is_diagnostic=(prefix == 'diagnostic'),
                    ))
                    mzs.append(f"{frag[0]:.4f}")
                    intensities.append(f"{frag[1]:.1f}")
                result_data[f'{prefix}-matched'].append(','.join(ids))
                result_data[f'{prefix}-matched-mz'].append(','.join(mzs))
                result_data[f'{prefix}-matched-intensity'].append(','.join(intensities))
            else:
                result_data[f'{prefix}-matched'].append('')
                result_data[f'{prefix}-matched-mz'].append('')
                result_data[f'{prefix}-matched-intensity'].append('')

    return pd.DataFrame(result_data, index=debug_df.index)


def _format_fragment_id(frag, is_diagnostic=False):
    """Format a fragment tuple into a human-readable ID string.
    Uses Base Type (idx 11) when available so custom ions like 'y*' display
    as their base series (e.g. 'y17+2' not 'y*17+2')."""
    if is_diagnostic:
        # Diagnostic: just the fragment sequence / ion name
        return str(frag[6]) if frag[6] else str(frag[5])

    # Prefer Base Type (idx 11) over Ion Type (idx 5)
    ion_type = frag[11] if len(frag) > 11 and frag[11] else frag[5]
    ion_number = frag[4]
    charge = frag[8]

    label = f"{ion_type}{ion_number}"
    if charge and int(charge) > 1:
        label += f"+{int(charge)}"
    return label


def _make_standard_filter(ion_name):
    """Filter for standard ions: Ion Type matches and Neutral Loss is 'None'."""
    def _filter(frags):
        return [f for f in frags if f[5] == ion_name and f[7] == 'None']
    return _filter


def _make_neutral_loss_filter(ion_name):
    """Filter for neutral loss ions: Ion Type matches exactly."""
    def _filter(frags):
        return [f for f in frags if f[5] == ion_name]
    return _filter


def _make_internal_filter(ion_name):
    """Filter for internal ions: Ion Type matches exactly."""
    def _filter(frags):
        return [f for f in frags if f[5] == ion_name]
    return _filter


def _make_custom_base_filter(ion_name):
    """Filter for custom ions base: Ion Type matches and Neutral Loss is 'None'."""
    def _filter(frags):
        return [f for f in frags if f[5] == ion_name and f[7] == 'None']
    return _filter


def _make_diagnostic_filter():
    """Filter for diagnostic ions: Neutral Loss == 'Custom_Ion'."""
    def _filter(frags):
        return [f for f in frags if f[7] == 'Custom_Ion']
    return _filter


_MOD_NL_PREFIXES = ("ModNL", "LabileLoss", "ModRM")


def _is_mod_nl_label(nl_str):
    return any(nl_str.startswith(p) for p in _MOD_NL_PREFIXES)


def _make_mod_nl_filter():
    """Filter for modification neutral loss ions: Neutral Loss starts with ModNL1/ModNL2/ModNL3/LabileLoss."""
    def _filter(frags):
        return [f for f in frags if _is_mod_nl_label(str(f[7]))]
    return _filter


def _make_mod_nl_granular_filter(nl_label, base_type):
    """Filter for a specific Mod-NL sub-type by neutral loss label AND base type."""
    def _filter(frags):
        results = []
        for f in frags:
            nl = str(f[7]) if f[7] is not None else ''
            if nl != nl_label:
                continue
            bt = str(f[11]).strip() if len(f) > 11 and f[11] else str(f[5]).strip()
            if bt == base_type:
                results.append(f)
        return results
    return _filter
