import json
import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class CentralModificationDatabase:
    """Single source of truth for all modification definitions.

    Stored as a JSON file.  Each entry stores a modification mass plus
    optional neutral-loss masses, remainder-ion masses, and a labile-loss flag.

    Schema per entry (dict value keyed by modification name):
        mass            (float)  monoisotopic delta-mass
        neutral_losses  (str)    comma-separated neutral-loss masses (e.g. "100.0,150.0")
        remainder_ions  (str)    comma-separated remainder-ion masses (e.g. "203.0,406.0")
        labile_loss     (bool)   whether the entire modification can be lost
    """

    TOLERANCE = 0.01  # Da – used for mass-based lookups

    _ENTRY_DEFAULTS = {
        "mass": 0.0,
        "neutral_losses": "",
        "remainder_ions": "",
        "labile_loss": False,
    }

    # Seed data – used only when no JSON *and* no CSV exist.
    DEFAULT_MODIFICATIONS = {
        "Carbamidomethyl": {"mass": 57.02146},
        "Oxidation": {"mass": 15.9949},
        "Phospho": {"mass": 79.9663},
        "Acetylation": {"mass": 42.0106},
        "Deamidation": {"mass": 0.9840},
        "Methylation": {"mass": 14.0157},
        "Dimethylation": {"mass": 28.0313},
        "Trimethylation": {"mass": 42.0470},
        "HexNAc": {"mass": 203.0794},
        "Hex": {"mass": 162.0528},
        "dHex": {"mass": 146.0579},
        "NeuAc": {"mass": 291.0954},
        "NeuGc": {"mass": 307.0903},
        "Sulfo": {"mass": 79.9568},
        "No Modification": {"mass": 0.0},
    }

    def __init__(self, json_path: str, csv_fallback_path: str | None = None):
        self.json_path = json_path
        self._csv_fallback_path = csv_fallback_path
        self.mods: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    #  Persistence
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_float_list(csv_string: str) -> list[float]:
        """Parse a comma-separated string of floats into a list."""
        if not csv_string or not csv_string.strip():
            return []
        return [float(x.strip()) for x in csv_string.split(",") if x.strip()]

    @staticmethod
    def _migrate_entry(entry: dict) -> dict:
        """Convert old neutral_loss_1/2/3 keys to neutral_losses string."""
        if "neutral_losses" in entry:
            return entry  # already new format
        nls = []
        for key in ("neutral_loss_1", "neutral_loss_2", "neutral_loss_3"):
            val = entry.pop(key, 0.0)
            if isinstance(val, (int, float)) and val > 0:
                nls.append(str(val))
        entry["neutral_losses"] = ",".join(nls)
        entry.setdefault("remainder_ions", "")
        return entry

    def _load(self):
        if os.path.exists(self.json_path):
            with open(self.json_path, "r") as f:
                raw = json.load(f)
            migrated = False
            self.mods = {}
            for name, vals in raw.items():
                entry = {**self._ENTRY_DEFAULTS, **vals}
                if "neutral_loss_1" in vals:
                    entry = self._migrate_entry(entry)
                    migrated = True
                self.mods[name] = entry
            if migrated:
                self._save()
                logger.debug(f"Migrated {len(self.mods)} entries to new NL/RM format")
        elif self._csv_fallback_path and os.path.exists(self._csv_fallback_path):
            # Migrate from legacy modifications_list.csv
            self._migrate_from_csv(self._csv_fallback_path)
            self._save()
        else:
            # Fresh install – use defaults
            self.mods = {
                name: {**self._ENTRY_DEFAULTS, **vals}
                for name, vals in self.DEFAULT_MODIFICATIONS.items()
            }
            self._save()

    def _migrate_from_csv(self, csv_path: str):
        """Import entries from the legacy modifications_list.csv."""
        try:
            df = pd.read_csv(csv_path)
            self.mods = {}
            for _, row in df.iterrows():
                name = str(row.get("Name", "")).strip()
                if not name:
                    continue
                try:
                    mass = float(row.get("Mass", 0))
                except (ValueError, TypeError):
                    continue
                self.mods[name] = {**self._ENTRY_DEFAULTS, "mass": mass}
            logger.debug(f"Migrated {len(self.mods)} entries from {csv_path}")
        except Exception as e:
            logger.debug(f"CSV migration failed: {e} – using defaults")
            self.mods = {
                name: {**self._ENTRY_DEFAULTS, **vals}
                for name, vals in self.DEFAULT_MODIFICATIONS.items()
            }

    def _save(self):
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        with open(self.json_path, "w") as f:
            json.dump(self.mods, f, indent=2, sort_keys=True)

    # ------------------------------------------------------------------
    #  Predicates
    # ------------------------------------------------------------------
    @staticmethod
    def has_active_neutral_loss(entry: dict, enable_labile: bool = True,
                                enable_mod_nl: bool = True) -> bool:
        """Return True if *entry* has at least one active neutral loss or remainder ion."""
        nl_val = entry.get("neutral_losses", "")
        # nl_val may be a list of numbers or a comma-separated string
        if isinstance(nl_val, list):
            has_nl = bool(nl_val and any(float(x) > 0 for x in nl_val)) and enable_mod_nl
        else:
            has_nl = bool(
                nl_val and isinstance(nl_val, str) and nl_val.strip()
                and any(float(x) > 0 for x in nl_val.split(",") if x.strip())
            ) and enable_mod_nl
        has_labile = enable_labile and entry.get("labile_loss", False)
        return has_nl or has_labile

    # ------------------------------------------------------------------
    #  Queries
    # ------------------------------------------------------------------
    def get_entry(self, mod_name: str) -> Optional[dict]:
        """Return full entry dict for *mod_name*, or ``None``."""
        return self.mods.get(mod_name)

    def get_mass(self, mod_name: str) -> Optional[float]:
        entry = self.mods.get(mod_name)
        return entry["mass"] if entry else None

    def get_all_entries(self) -> dict[str, dict]:
        return dict(self.mods)

    def find_by_mass(self, mass: float, tolerance: float | None = None) -> Optional[str]:
        """Reverse-lookup: mass → modification name (first match within *tolerance*)."""
        tol = tolerance if tolerance is not None else self.TOLERANCE
        for name, entry in self.mods.items():
            if abs(entry["mass"] - mass) < tol:
                return name
        return None

    def get_neutral_losses_for_mass(self, mass: float, tolerance: float | None = None) -> Optional[dict]:
        """Return neutral-loss config for the modification matching *mass*.

        Returns a dict with keys ``neutral_losses`` (list[float]),
        ``remainder_ions`` (list[float]), ``labile_loss`` (bool),
        ``mod_mass`` (float) – or ``None`` if no entry matches.
        """
        name = self.find_by_mass(mass, tolerance)
        if name is None:
            return None
        entry = self.mods[name]
        return {
            "neutral_losses": self._parse_float_list(entry.get("neutral_losses", "")),
            "remainder_ions": self._parse_float_list(entry.get("remainder_ions", "")),
            "labile_loss": entry.get("labile_loss", False),
            "mod_mass": entry["mass"],
        }

    # ------------------------------------------------------------------
    #  Backward-compatible views
    # ------------------------------------------------------------------
    def as_modification_list(self) -> list[dict]:
        """Return ``[{'Name': ..., 'Mass': ...}, ...]`` for the spectrum viewer."""
        return [
            {"Name": name, "Mass": entry["mass"]}
            for name, entry in self.mods.items()
        ]

    def as_dataframe(self) -> "pd.DataFrame":
        """Return a DataFrame with ``['Name', 'Mass']`` columns."""
        rows = [{"Name": n, "Mass": e["mass"]} for n, e in self.mods.items()]
        return pd.DataFrame(rows, columns=["Name", "Mass"])

    # ------------------------------------------------------------------
    #  Mutations (auto-save)
    # ------------------------------------------------------------------
    def add_mod(self, name: str, mass: float, **kwargs):
        entry = {**self._ENTRY_DEFAULTS, "mass": mass, **kwargs}
        self.mods[name] = entry
        self._save()

    def update_mod(self, name: str, **kwargs):
        if name in self.mods:
            self.mods[name].update(kwargs)
            self._save()

    def remove_mod(self, name: str):
        if name in self.mods:
            del self.mods[name]
            self._save()

    def ensure_mass_exists(self, mass: float, default_name: str | None = None) -> str:
        """Ensure mass is represented in the database.

        If a matching entry already exists (within tolerance), return its name.
        Otherwise create a new entry and return the new name.
        """
        existing = self.find_by_mass(mass)
        if existing is not None:
            return existing
        name = default_name or f"+{mass:.4f}"
        self.add_mod(name, mass)
        return name
