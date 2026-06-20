import logging
import re

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QMessageBox,
)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator

from utils.style.GUI_dimensions import LayoutConstants
from utils.utilities import CacheManager, IonTypeGenerator
from utils.resource_path import get_data_file_path
from utils import TableUtils
from utils.peak_matching.persistent_fragmentation_worker import (
    PersistentFragmentationManager,
)
from utils.utility_classes.scoring_settings_dialog import ScoringSettingsDialog

logger = logging.getLogger(__name__)


class _GUIDataMixin:

    def _init_scan_selection_controls(self):
        """Initialize controls for direct scan selection with improved sizing"""

        # Add section header
        scan_selection_header = self._create_section_header("Direct Scan Selection")
        self.left_layout.addWidget(scan_selection_header)

        # Add checkbox to enable/disable this feature
        self.enable_direct_scan_checkbox = QCheckBox("Enable Direct Scan Selection")
        self.enable_direct_scan_checkbox.setChecked(False)
        self.enable_direct_scan_checkbox.stateChanged.connect(
            self.toggle_direct_scan_mode
        )
        self.enable_direct_scan_checkbox.setMaximumWidth(
            LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20
        )
        self.enable_direct_scan_checkbox.setMinimumHeight(25)
        self.left_layout.addWidget(self.enable_direct_scan_checkbox)

        # Raw file dropdown with improved layout
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)

        file_label = QLabel("Raw File:")
        file_label.setMaximumWidth(70)
        file_label.setMinimumHeight(28)
        file_layout.addWidget(file_label)

        self.raw_file_combo = QComboBox()
        self.raw_file_combo.setEnabled(False)
        self.raw_file_combo.setMaximumWidth(
            LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 95
        )
        self.raw_file_combo.setMinimumHeight(28)
        file_layout.addWidget(self.raw_file_combo)

        # Create container widget for the layout
        file_widget = QWidget()
        file_widget.setLayout(file_layout)
        file_widget.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        file_widget.setMinimumHeight(35)
        self.left_layout.addWidget(file_widget)

        # Scan number input
        scan_layout = QHBoxLayout()
        scan_layout.setSpacing(8)

        scan_label = QLabel("Scan:")
        scan_label.setMaximumWidth(45)
        scan_label.setMinimumHeight(28)
        scan_layout.addWidget(scan_label)

        self.scan_number_input = QLineEdit()
        self.scan_number_input.setEnabled(False)
        self.scan_number_input.setValidator(
            QRegularExpressionValidator(QRegularExpression("^[0-9]*$"))
        )
        self.scan_number_input.setMaximumWidth(90)
        self.scan_number_input.setMinimumHeight(28)
        scan_layout.addWidget(self.scan_number_input)

        # Extract button
        self.extract_scan_button = QPushButton("Extract")
        self.extract_scan_button.setEnabled(False)
        self.extract_scan_button.clicked.connect(self.extract_scan_data)
        self.extract_scan_button.setMaximumWidth(75)
        self.extract_scan_button.setMinimumHeight(28)
        scan_layout.addWidget(self.extract_scan_button)

        # Add stretch to push everything left
        scan_layout.addStretch()

        # Create container widget for the scan layout
        scan_widget = QWidget()
        scan_widget.setLayout(scan_layout)
        scan_widget.setMaximumWidth(LayoutConstants.LEFT_PANEL_INITIAL_WIDTH - 20)
        scan_widget.setMinimumHeight(35)
        self.left_layout.addWidget(scan_widget)

    def _populate_glycan_combo(self):
        """Populate the glycan composition combo in the left panel."""
        if not hasattr(self, "glycan_composition_combo"):
            return
        combo = self.glycan_composition_combo
        current_text = combo.currentText()

        # Pre-compute masses so they appear in the display label and are searchable
        try:
            from utils.peak_matching.constants import load_custom_monosaccharides
            mass_lookup, _ = load_custom_monosaccharides()
        except Exception:
            mass_lookup = {}

        combo.blockSignals(True)
        combo.clear()
        for name, composition in getattr(self, "glycan_compositions", []):
            mass = self._calculate_glycan_composition_mass(composition, mass_lookup)
            mass_str = f"{mass:.2f} Da" if mass is not None else "? Da"
            label = f"{name}  ({mass_str})"
            combo.addItem(label, userData=composition)

        if current_text:
            idx = combo.findText(current_text)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(current_text)
        combo.blockSignals(False)

    def _on_glycan_settings_changed(self):
        """Push glycan Y-ion settings to the MassSpecViewer and trigger re-fragmentation."""
        viewer = getattr(
            getattr(self, "annotation_tab_manager", None), "mass_spec_viewer", None
        )
        if not viewer:
            return

        viewer.glycan_y_enabled = self.glycan_enabled_cb.isChecked()

        idx = self.glycan_composition_combo.currentIndex()
        if idx >= 0:
            user_data = self.glycan_composition_combo.itemData(idx)
            composition = (
                user_data
                if user_data
                else self.glycan_composition_combo.currentText().strip()
            )
        else:
            composition = self.glycan_composition_combo.currentText().strip()

        viewer.glycan_composition_str = composition
        viewer.glycan_max_charge = self.glycan_max_charge_spin.value()

        if hasattr(viewer, "glycanSettingsChanged"):
            viewer.glycanSettingsChanged.emit()

    def _extract_mod_masses(self, parsed_mods: list) -> list[float]:
        """Extract numeric modification masses from supported parsed-mod formats."""
        masses = []
        for mod in parsed_mods or []:
            mass_val = None
            if isinstance(mod, (tuple, list)) and mod:
                mass_val = mod[0]
            elif isinstance(mod, dict):
                for key in ("mass", "Mass", "mod_mass", "modMass"):
                    if key in mod:
                        mass_val = mod[key]
                        break
            if mass_val is None:
                continue
            try:
                masses.append(float(mass_val))
            except (TypeError, ValueError):
                continue
        return masses

    @staticmethod
    def _calculate_glycan_composition_mass(
        composition: str, mass_lookup: dict[str, float]
    ) -> float | None:
        """Calculate glycan residue mass from a composition string."""
        tokens = re.findall(r"([A-Za-z]+)\((\d+)\)", composition or "")
        if not tokens:
            return None
        total = 0.0
        for name, count_str in tokens:
            mass = mass_lookup.get(name)
            if mass is None:
                return None
            total += mass * int(count_str)
        return total

    def _autoselect_glycan_from_parsed_mods(
        self, parsed_mods: list, tolerance_da: float = 0.02
    ) -> bool:
        """Auto-select glycan composition when a mod mass matches a glycan mass."""
        if not hasattr(self, "glycan_composition_combo"):
            return False
        if not getattr(self, "glycan_compositions", None):
            return False

        mod_masses = self._extract_mod_masses(parsed_mods)
        if not mod_masses:
            return False

        from utils.peak_matching.constants import load_custom_monosaccharides

        mass_lookup, _ = load_custom_monosaccharides()

        best_match = None
        for name, composition in self.glycan_compositions:
            glycan_mass = self._calculate_glycan_composition_mass(composition, mass_lookup)
            if glycan_mass is None:
                continue
            for mod_mass in mod_masses:
                delta = abs(mod_mass - glycan_mass)
                if delta > tolerance_da:
                    continue
                candidate = (delta, name, composition, mod_mass, glycan_mass)
                if best_match is None or candidate < best_match:
                    best_match = candidate

        if best_match is None:
            return False

        _, name, composition, mod_mass, glycan_mass = best_match
        combo = self.glycan_composition_combo

        current_idx = combo.currentIndex()
        if current_idx >= 0:
            current_data = combo.itemData(current_idx)
            current_comp = current_data if current_data else combo.currentText().strip()
            if current_comp == composition:
                return False

        target_idx = -1
        for idx in range(combo.count()):
            if combo.itemData(idx) == composition:
                target_idx = idx
                break

        combo.blockSignals(True)
        if target_idx >= 0:
            combo.setCurrentIndex(target_idx)
        else:
            combo.setEditText(composition)
        combo.blockSignals(False)

        self._on_glycan_settings_changed()
        logger.info(
            "[GLYCAN] Auto-selected '%s' (%s) from mod mass %.4f (glycan %.4f, Δ=%.4f Da)",
            name,
            composition,
            mod_mass,
            glycan_mass,
            abs(mod_mass - glycan_mass),
        )
        return True

    def _on_glycan_snfg_toggled(self, checked):
        """Toggle SNFG shape rendering on the MassSpecViewer (no re-fragmentation needed)."""
        viewer = getattr(
            getattr(self, "annotation_tab_manager", None), "mass_spec_viewer", None
        )
        if viewer and hasattr(viewer, "_on_snfg_toggled"):
            viewer._on_snfg_toggled(bool(checked))

    def _open_glycan_database_editor(self):
        """Open the glycan database editor (glycan structures + custom monosaccharides)."""
        from utils.mod_database.glycan_database_editor import GlycanDatabaseEditor

        dialog = GlycanDatabaseEditor(self)

        def _on_data_changed():
            try:
                from utils.resource_path import get_data_file_path
                import csv as _csv

                glycan_list = []
                with open(
                    get_data_file_path("glycan_compositions.csv"),
                    newline="",
                    encoding="utf-8",
                ) as f:
                    reader = _csv.reader(f)
                    for i, row in enumerate(reader):
                        if len(row) >= 2:
                            if i == 0 and row[0].strip().lower() in (
                                "name",
                                "glycan name",
                            ):
                                continue
                            glycan_list.append((row[0].strip(), row[1].strip()))
                self.glycan_compositions = glycan_list
                self._populate_glycan_combo()
                self._autoselect_glycan_from_parsed_mods(
                    getattr(self, "current_interactive_mods", [])
                )
                viewer = getattr(
                    getattr(self, "annotation_tab_manager", None),
                    "mass_spec_viewer",
                    None,
                )
                if viewer:
                    viewer._glycan_compositions_list = glycan_list
            except Exception:
                pass
            try:
                from utils.peak_matching.constants import load_snfg_shapes
                from utils.utility_classes.htmlformating import HTMLFormatter

                HTMLFormatter.update_snfg_shapes(load_snfg_shapes())
            except Exception:
                pass

        dialog.data_changed.connect(_on_data_changed)
        dialog.exec()

    def edit_mod_databases(self):
        """Open the modification mass database editor."""
        from utils.mod_database import ModDatabaseEditorDialog, ModificationMassDatabase
        from utils.resource_path import get_data_file_path

        maxquant_db = getattr(self.experiment_data_manager, "maxquant_mod_db", None)
        metamorpheus_db = getattr(
            self.experiment_data_manager, "metamorpheus_mod_db", None
        )

        if maxquant_db is None:
            maxquant_db = ModificationMassDatabase(
                get_data_file_path("maxquant_mods.json")
            )
            self.experiment_data_manager.maxquant_mod_db = maxquant_db
        if metamorpheus_db is None:
            metamorpheus_db = ModificationMassDatabase(
                get_data_file_path("metamorpheus_mods.json")
            )
            self.experiment_data_manager.metamorpheus_mod_db = metamorpheus_db

        dialog = ModDatabaseEditorDialog(maxquant_db, metamorpheus_db, self)
        dialog.exec()

    def combine_and_process_psm_files(self):
        """Delegate to experiment data manager and sync data"""
        result = self.experiment_data_manager.combine_and_process_psm_files()

        # Sync the data across tabs
        if hasattr(self.experiment_data_manager, "merged_df"):
            self.sync_psm_data_across_tabs(self.experiment_data_manager.merged_df)

        return result

    def sync_psm_data_across_tabs(self, data) -> None:
        """Sync PSM data across all tabs that need it"""
        try:
            # Update annotation tab PSM summary
            if (
                self.annotation_tab_manager
                and self.annotation_tab_manager.psm_summary_widget
            ):
                self.annotation_tab_manager.psm_summary_widget.setData(data)
                logger.debug(
                    f"Updated annotation tab PSM summary with {len(data)} records"
                )

            # Update fragmentation tab PSM summary
            if (
                hasattr(self, "frag_psm_summary_widget")
                and self.frag_psm_summary_widget
            ):
                self.frag_psm_summary_widget.setData(data)
                logger.debug(
                    f"Updated fragmentation tab PSM summary with {len(data)} records"
                )

            # Update protein coverage tab with PSM data
            if self.protein_coverage_tab_manager:
                self.protein_coverage_tab_manager.set_psm_data(data)
                logger.debug(f"Updated protein coverage tab with {len(data)} records")

            logger.debug(f"Synced PSM data across tabs: {len(data)} records")

        except Exception:
            logger.exception("Failed to sync PSM data across tabs")

    def on_peptide_selected(
        self, peptide: str, parsed_mods: list, charge: int, row_data: dict
    ):
        """Legacy method - delegate to event handlers for backward compatibility"""
        return self.event_handlers.on_peptide_selected(
            peptide, parsed_mods, charge, row_data
        )

    def populate_mz_table(self, mz_array, intensity_array):
        """Populate the m/z table with given arrays"""
        self.event_handlers.set_populating_table(True)
        try:
            data_pairs = list(zip(mz_array, intensity_array))
            TableUtils.populate_two_column_table(self.mz_table, data_pairs)
        finally:
            self.event_handlers.set_populating_table(False)

        # Trigger validation after populating data (only once)
        self.validate_fragmentation_inputs()
        # Trigger one adaptive update after population is complete
        self.on_settings_changed()

    def on_interactive_modifications_changed(self, modifications: list):
        """Legacy method - delegate to event handlers for backward compatibility"""
        return self.event_handlers.on_interactive_modifications_changed(modifications)

    def toggle_direct_scan_mode(self, state):
        """Delegate to event handlers"""
        return self.event_handlers.on_direct_scan_toggle(state)

    def edit_data_list(self, data_type: str) -> None:
        """Edit data lists with proper update propagation - NON-MODAL"""
        # Central modification database gets its own dedicated editor
        if data_type == "modifications":
            self._edit_central_modifications()
            return

        data_map = {
            "diagnostic_ions": (
                self.diagnostic_ions,
                "Diagnostic Ions",
                get_data_file_path("diagnostic_ions.csv"),
            ),
            "custom_ion_series": (
                self.custom_ion_series,
                "Custom Ion Series",
                get_data_file_path("custom_ion_series.csv"),
            ),
        }

        if data_type not in data_map:
            logger.warning(f"Unknown data type for editing: {data_type}")
            return

        current_data, title, file_path = data_map[data_type]

        # Use the dialog manager to open the editor
        self.dialog_manager.open_editor(data_type, current_data, file_path, title)

    def _edit_central_modifications(self):
        """Open the central modification database editor."""
        from utils.mod_database import CentralModEditorDialog

        dialog_attr = "_modifications_editor_dialog"
        if hasattr(self, dialog_attr) and getattr(self, dialog_attr) is not None:
            existing = getattr(self, dialog_attr)
            existing.raise_()
            existing.activateWindow()
            return

        editor = CentralModEditorDialog(self.central_mod_db, self)
        setattr(self, dialog_attr, editor)

        def on_finished():
            # Refresh the backward-compat DataFrame view
            self.available_mods = self.central_mod_db.as_dataframe()
            self.annotation_tab_manager.set_available_modifications(
                self.central_mod_db.as_modification_list()
            )
            # Clear fragmentation cache so new NL definitions take effect
            if hasattr(self, "persistent_fragmentation_manager"):
                self.persistent_fragmentation_manager.fragment_cache.clear()
            self.show_toast_message("Central modifications updated!")
            setattr(self, dialog_attr, None)

        def on_closed():
            setattr(self, dialog_attr, None)

        editor.finished.connect(on_finished)
        editor.rejected.connect(on_closed)
        editor.show()

    def _toggle_scoring_method(self, method_key, enabled):
        """Toggle a scoring method on/off and recalculate"""
        self.scoring_methods[method_key] = enabled
        self._save_scoring_settings()
        self.on_settings_changed()

    def _open_scoring_settings(self):
        """Open the scoring settings dialog."""
        dlg = ScoringSettingsDialog(self)
        dlg.exec()

    def _toggle_annotation_mode(self):
        """Switch between auto and manual annotation modes."""
        if self.manual_annotation_action.isChecked():
            self.annotation_mode = "manual"
            self.annotate_button.setEnabled(True)
        else:
            self.annotation_mode = "auto"
            self.annotate_button.setEnabled(False)
            self.event_handlers.perform_adaptive_update()

    def _load_scoring_settings(self):
        """Load persisted scoring settings from QSettings."""
        from PyQt6.QtCore import QSettings

        s = QSettings(self.SETTINGS_ORGANIZATION, self.SETTINGS_APP_NAME)
        for key in self.scoring_methods:
            val = s.value(f"scoring/{key}")
            if val is not None:
                self.scoring_methods[key] = str(val).lower() in ("true", "1")
        mc = s.value("scoring/max_charge")
        if mc is not None:
            try:
                self.scoring_max_charge = int(mc)
            except (ValueError, TypeError):
                pass
        nl_val = s.value("scoring/nl_in_count")
        if nl_val is not None:
            self.scoring_nl_in_count = str(nl_val).lower() in ("true", "1")
        iso_val = s.value("scoring/calculate_isotopes")
        if iso_val is not None:
            self.calculate_isotopes = str(iso_val).lower() in ("true", "1")
        iso_max_val = s.value("scoring/isotope_max")
        if iso_max_val is not None:
            try:
                self.isotope_max = max(1, min(4, int(iso_max_val)))
            except (ValueError, TypeError):
                pass

    def _save_scoring_settings(self):
        """Persist current scoring settings to QSettings."""
        from PyQt6.QtCore import QSettings

        s = QSettings(self.SETTINGS_ORGANIZATION, self.SETTINGS_APP_NAME)
        for key, val in self.scoring_methods.items():
            s.setValue(f"scoring/{key}", val)
        s.setValue("scoring/max_charge", self.scoring_max_charge)
        s.setValue("scoring/nl_in_count", self.scoring_nl_in_count)
        s.setValue("scoring/calculate_isotopes", self.calculate_isotopes)
        s.setValue("scoring/isotope_max", self.isotope_max)

    def generate_dynamic_ion_types(self):
        """Generate ion types using utility"""

        return IonTypeGenerator.generate_dynamic_ion_types(
            self.normal_ion_checkboxes,
            self.neutral_ion_checkboxes,
            self.max_neutral_losses_input.value(),
        )

    def _load_glycan_compositions(self):
        """Load glycan composition database from data/glycan_compositions.csv."""
        import csv as _csv

        path = get_data_file_path("glycan_compositions.csv")
        compositions = []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    name = row.get("Name", "").strip()
                    comp = row.get("Composition", "").strip()
                    if name and comp:
                        compositions.append((name, comp))
        except Exception:
            pass
        return compositions

    def clear_fragment_cache(self) -> None:
        """Clear cache using utility"""
        cleared_count = CacheManager.clear_cache(self.persistent_fragmentation_manager)
        logger.info(f"Cleared {cleared_count} cached fragments")
        self.cache_hit_count = 0
        self.cache_miss_count = 0

    def show_cache_statistics(self):
        """Show cache statistics using utility"""
        # Update manager with current counts
        if self.persistent_fragmentation_manager:
            self.persistent_fragmentation_manager.cache_hit_count = self.cache_hit_count
            self.persistent_fragmentation_manager.cache_miss_count = (
                self.cache_miss_count
            )

        stats = CacheManager.get_cache_stats(self.persistent_fragmentation_manager)

        message = f"""Fragment Cache Statistics:
        
Cache Size: {stats['cache_size']} / {stats['max_cache_size']} entries
Total Requests: {stats['total_requests']}
Cache Hits: {stats['hit_count']}
Cache Misses: {stats['miss_count']}
Hit Rate: {stats['hit_rate_percent']:.1f}%
Memory Usage: ~{stats['cache_size'] * 50:.0f} KB (estimated)"""

        QMessageBox.information(self, "Cache Statistics", message)

    def _setup_persistent_fragmentation(self) -> None:
        """Setup persistent fragmentation manager"""
        # Initialize cache tracking counters
        self.cache_hit_count = 0
        self.cache_miss_count = 0

        self.persistent_fragmentation_manager = PersistentFragmentationManager()

        logger.debug("Persistent fragmentation manager initialized")
