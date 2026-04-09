# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('assets', 'assets'), ('data', 'data')]
# Add ThermoFisher .NET DLLs for RawFileReader
datas += [('RawFileReader-main/RawFileReader-main/Libs/Net471', 'RawFileReader-main/RawFileReader-main/Libs/Net471')]
binaries = []
hiddenimports = ['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'pandas', 'numpy', 'pyqtgraph', 'matplotlib', 'reportlab', 'tqdm', 'pymzml', 'clr', 'pythonnet', 'psm_utils', 'psm_utils.proforma', 'psm_utils.proforma.proforma', 'utils.mod_database', 'utils.mod_database.central_mod_database', 'utils.mod_database.modification_mass_database', 'utils.mod_database.mod_database_editor', 'utils.mod_database.unknown_mods_dialog']

# Collect pyqtgraph data
tmp_ret = collect_all('pyqtgraph')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect pymzml data files (including version.txt)
datas += collect_data_files('pymzml')

# Collect reportlab data files
datas += collect_data_files('reportlab')

# Collect psm_utils data files
tmp_ret = collect_all('psm_utils')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['GUI.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MassSpectrumAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MassSpectrumAnalyzer',
)
