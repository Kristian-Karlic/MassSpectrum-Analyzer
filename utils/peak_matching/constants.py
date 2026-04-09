"""Mass constants, amino acid data, ion colors, and lookup tables for peptide fragmentation."""

__all__ = [
    'AMINO_ACID_MASSES', 'SIDECHAIN_LEAVING_GROUPS', 'V_ION_EXCLUDED_AA',
    'H', 'E', 'Neu', 'N', 'O', 'C', 'P', 'S', 'C13',
    'H2O', 'NH3', 'NH2', 'H_ion', 'H3PO4', 'CO', 'SOCH4', 'C2H2NO', 'O',
    'ion_colors', '_SUPERSCRIPT',
]

AMINO_ACID_MASSES = {
    "A": 71.037113805, "C": 103.009184505, "D": 115.026943065, "E": 129.042593135,
    "F": 147.068413945, "G": 57.021463735, "H": 137.058911875, "I": 113.084064015,
    "K": 128.094963050, "L": 113.084064015, "M":  131.040484645, "N": 114.042927470,
    "P": 97.052763875, "Q": 128.058577540, "R": 156.101111050, "S": 87.032028435,
    "T": 101.047678505, "V": 99.068413945, "W": 186.079312980, "Y": 163.063328575
}

# Sidechain leaving groups for d/w satellite ions (Cb radical loss)
# Maps amino acid -> list of (label_suffix, monoisotopic_radical_mass)
# "a" suffix = lighter loss (heavier product), "b" = heavier loss (lighter product)
# G, A, P have no satellite ions (empty list)
SIDECHAIN_LEAVING_GROUPS = {
    "G": [],
    "A": [],
    "P": [],
    "V": [("a", 15.023475)],          # CH3 (two identical Cb substituents)
    "L": [("a", 43.054775)],          # C3H7 (isopropyl)
    "I": [("a", 29.039125),           # CH3 (lighter loss -> heavier product)
          ("b", 15.023475)],           # C2H5 (heavier loss -> lighter product)
    "T": [("a", 17.002740),           # CH3 (lighter loss -> heavier product)
          ("b", 15.023475)],           # OH (heavier loss -> lighter product)
    "S": [("a", 17.002740)],          # OH 17.002740
    "C": [("a", 32.979896)],          # SH
    "M": [("a", 61.011196)],          # CH2SCH3
    "D": [("a", 44.997655)],          # COOH
    "E": [("a", 59.013305)],          # CH2COOH
    "N": [("a", 44.013639)],          # CONH2
    "Q": [("a", 58.029289)],          # CH2CONH2
    "K": [("a", 58.065674)],          # (CH2)3NH2
    "R": [("a", 86.071822)],          # (CH2)2NHC(=NH)NH2
    "H": [("a", 67.029623)],          # Imidazolyl (C3H3N2)
    "F": [("a", 77.039125)],          # Phenyl (C6H5)
    "Y": [("a", 93.034040)],          # 4-OH-Phenyl (C6H4OH)
    "W": [("a", 115.042199)],         # Indolyl (C8H5N)
}

# Amino acids excluded from v ion generation (no meaningful sidechain loss)
V_ION_EXCLUDED_AA = {"G", "A", "P"}

# Mass constants
H = 1.007825     # Hydrogen mass
E = 0.000549     # Electron mass
Neu = 1.00866491588  # Mass of neutron
N = 14.003074    # Nitrogen mass
O = 15.994915    # Oxygen mass
C = 12.0000000   # Carbon mass
P = 30.973762
S = 32.065
C13 = 1.0033548378  # Carbon-13 mass (difference from C12)
H2O = 2*H + O
NH3 = N + 3*H
NH2 = N + 2*H
H_ion = 1.007276
H3PO4 = 3*H + P + 4*O
CO = C + O
SOCH4 = S + O + C + 4*H

C2H2NO = 2*C + 2*H + N + O  # for v ion calculation

ion_colors = {
    "a": "purple",
    "b": "blue",
    "c": "green",
    "c-1": "green",
    "x": "brown",
    "y": "red",
    "z": "orange",
    "MH": "black",
    "da": "teal", "db": "teal",
    "wa": "darkcyan", "wb": "darkcyan",
    "v": "magenta",
    "d-H2O": "teal", "d-NH3": "teal",
    "w-H2O": "darkcyan", "w-NH3": "darkcyan",
    "v-H2O": "magenta", "v-NH3": "magenta",
    "y-H2O": "red", "a-H2O": "purple", "b-H2O": "blue",
    "y-NH3": "red", "a-NH3": "purple", "b-NH3": "blue", "z+1": "orange",
    "a-H3PO4": "purple", "b-H3PO4": "blue", "y-H3PO4": "red",
    "b-SOCH4": "blue", "y-SOCH4": "red",
    "MH-H2O": "black", "MH-NH3": "black",
}

_SUPERSCRIPT = str.maketrans("0123456789", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079")
