from utils.mod_database.central_mod_database import CentralModificationDatabase
from utils.mod_database.modification_mass_database import ModificationMassDatabase
from utils.mod_database.unknown_mods_dialog import UnknownModificationsDialog

# Lazy imports for heavy GUI classes - import directly when needed:
#   from utils.mod_database.mod_database_editor import ModDatabaseEditorDialog, CentralModEditorDialog


def __getattr__(name):
    if name == "ModDatabaseEditorDialog":
        from utils.mod_database.mod_database_editor import ModDatabaseEditorDialog
        return ModDatabaseEditorDialog
    if name == "CentralModEditorDialog":
        from utils.mod_database.mod_database_editor import CentralModEditorDialog
        return CentralModEditorDialog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CentralModificationDatabase",
    "ModificationMassDatabase",
    "ModDatabaseEditorDialog",
    "CentralModEditorDialog",
    "UnknownModificationsDialog",
]
