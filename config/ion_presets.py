"""Ion preset definitions for common fragmentation methods"""

# Shared ion set for electron-based dissociation methods (ETD/ECD).
# Kept as separate dict entries so they can diverge independently if needed.
_ELECTRON_DISSOCIATION = {
    "normal": {"c", "z", "z+1", "MH"},
    "neutral": set(),
}

ION_PRESETS = {
    "HCD": {
        "normal": {"y", "b", "MH"},
        "neutral": {"MH-H2O", "MH-NH3"},
    },
    "ETD": {**_ELECTRON_DISSOCIATION},
    "CID": {
        "normal": {"y", "b", "MH"},
        "neutral": {"y-H2O", "b-H2O", "y-NH3", "b-NH3", "MH-H2O", "MH-NH3"},
    },
    "ECD": {**_ELECTRON_DISSOCIATION},
    "EThcD": {
        "normal": {"y", "b", "c", "z", "z+1", "MH"},
        "neutral": {"MH-H2O", "MH-NH3"},
    },
}
