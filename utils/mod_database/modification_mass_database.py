import json
import os
from typing import Optional


class ModificationMassDatabase:
    """Persistent database mapping modification names to masses (Da).

    Stored as a JSON file.  Separate instances are used for MaxQuant and
    MetaMorpheus so that engine-specific names never collide.
    """

    DEFAULT_MODIFICATIONS = {
        "Carbamidomethyl": 57.02146,
        "Oxidation": 15.9949,
        "Phospho": 79.9663,
        "Acetyl": 42.0106,
        "Deamidation": 0.9840,
        "Methylation": 14.0157,
        "Dimethylation": 28.0313,
        "Trimethylation": 42.0470,
        "HexNAc": 203.0794,
        "Hex": 162.0528,
        "dHex": 146.0579,
        "NeuAc": 291.0954,
        "NeuGc": 307.0903,
        "Sulfo": 79.9568,
    }

    def __init__(self, json_path: str):
        self.json_path = json_path
        self.mods: dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------
    #  Persistence
    # ------------------------------------------------------------------
    def _load(self):
        if os.path.exists(self.json_path):
            with open(self.json_path, "r") as f:
                self.mods = json.load(f)
        else:
            self.mods = dict(self.DEFAULT_MODIFICATIONS)
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        with open(self.json_path, "w") as f:
            json.dump(self.mods, f, indent=2, sort_keys=True)

    # ------------------------------------------------------------------
    #  Queries
    # ------------------------------------------------------------------
    def get_mass(self, mod_name: str) -> Optional[float]:
        return self.mods.get(mod_name)

    def has_mod(self, mod_name: str) -> bool:
        return mod_name in self.mods

    def get_all_mods(self) -> dict[str, float]:
        return dict(self.mods)

    # ------------------------------------------------------------------
    #  Mutations (auto-save)
    # ------------------------------------------------------------------
    def add_mod(self, mod_name: str, mass: float):
        self.mods[mod_name] = mass
        self._save()

    def remove_mod(self, mod_name: str):
        if mod_name in self.mods:
            del self.mods[mod_name]
            self._save()

    def update_batch(self, mod_dict: dict[str, float]):
        self.mods.update(mod_dict)
        self._save()
