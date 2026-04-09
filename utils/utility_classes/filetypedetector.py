import os
import re
import pandas as pd

class FileTypeDetector:
    MSFRAGGER_COLUMNS = [
        "Spectrum", "Spectrum File", "Peptide", "Modified Peptide",
        "Extended Peptide", "Prev AA", "Next AA", "Peptide Length",
        "Charge", "Retention", "Observed Mass"
    ]

    # Pre-validation MSFragger format (before Philosopher/PeptideProphet)
    MSFRAGGER_PREVALIDATION_COLUMNS = [
        "scannum", "precursor_neutral_mass", "retention_time", "charge"
    ]

    MAXQUANT_COLUMNS = [
        "Raw file", "Scan number", "Scan index", "Sequence", "Length",
        "Missed cleavages", "Modifications", "Modified sequence"
    ]

    METAMORPHEUS_COLUMNS = [
        "File Name", "Scan Number", "Base Sequence", "Full Sequence",
        "Precursor Charge", "Precursor MZ", "Score", "Accession"
    ]

    BYONIC_COLUMNS = [
        "PID", "Sequence (unformatted)", "Mods (variable)",
        "Obs. m/z", "Protein Name", "Scan #", "z", "Comment"
    ]

    # psm_utils-backed format fingerprints (column subsets that are distinctive)
    PEAKS_COLUMNS = ["Source File", "Scan", "Peptide", "m/z", "z", "Score", "Mass"]
    SAGE_COLUMNS   = ["filename", "scannr", "peptide", "charge", "hyperscore", "delta_mass"]
    PERCOLATOR_COLUMNS = ["SpecId", "Label", "ScanNr", "score", "Peptide", "Proteins"]

    @staticmethod
    def detect_search_file_type(file_path: str) -> str | None:
        ext = os.path.splitext(file_path)[1].lower()

        # ── Extension-only detection ────────────────────────────────────────
        if ext == '.mzid':
            return 'mzIdentML'
        if ext == '.idxml':
            return 'IdXML'
        if ext in ('.pin', '.pout'):
            return 'Percolator'
        if ext == '.pepxml':
            return 'pepXML'

        # ── XML: distinguish X!Tandem and pepXML from other XML ────────────
        if ext == '.xml':
            return FileTypeDetector._detect_xml(file_path)

        # ── Header-based detection ──────────────────────────────────────────
        try:
            # Try TSV first
            df = pd.read_csv(file_path, sep='\t', nrows=0)
            columns = df.columns.tolist()

            # If TSV read resulted in only 1 column, try CSV
            if len(columns) == 1:
                df = pd.read_csv(file_path, sep=',', nrows=0)
                columns = df.columns.tolist()

            # Normalize column names: remove/replace whitespace variations and collapse multiple spaces
            normalized_cols = [re.sub(r'\s+', ' ', col.replace('\n', ' ').replace('\r', ' ')).strip() for col in columns]
            columns_lower = [c.lower() for c in columns]

            # ── Existing formats (checked first to avoid false positives) ───
            if (columns[0] == "scannum" and
                "modification_info" in columns and
                "peptide" in columns):
                return 'MSFragger_PreValidation'
            elif columns[:11] == FileTypeDetector.MSFRAGGER_COLUMNS:
                return 'MSFragger'
            elif all(col in columns for col in FileTypeDetector.METAMORPHEUS_COLUMNS):
                return 'MetaMorpheus'
            elif all(col in normalized_cols for col in FileTypeDetector.BYONIC_COLUMNS):
                return 'Byonic'
            elif all(col in columns for col in FileTypeDetector.MAXQUANT_COLUMNS):
                return 'MaxQuant'

            # ── psm_utils-backed formats ────────────────────────────────────
            elif all(col in columns for col in FileTypeDetector.PEAKS_COLUMNS):
                return 'PEAKS'
            elif all(col in columns_lower for col in FileTypeDetector.SAGE_COLUMNS):
                return 'Sage'
            elif all(col in columns for col in FileTypeDetector.PERCOLATOR_COLUMNS):
                return 'Percolator'

        except Exception:
            pass
        return None

    @staticmethod
    def _detect_xml(file_path: str) -> str | None:
        """Peek at the first 512 bytes of an XML file to identify its type."""
        try:
            with open(file_path, 'rb') as fh:
                header = fh.read(512).decode('utf-8', errors='ignore').lower()
            if '<bioml' in header or '<tandem' in header:
                return 'XTandem'
            if 'msms_pipeline_analysis' in header or 'spectrum_query' in header:
                return 'pepXML'
        except Exception:
            pass
        return None

    @staticmethod
    def filter_raw_files(files: list[str]) -> tuple[list[str], list[str]]:
        valid, invalid = [], []
        for file in files:
            if file.lower().endswith(('.raw', '.mzml')):
                valid.append(file)
            else:
                invalid.append(os.path.basename(file))
        return valid, invalid

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def psm_utils_format_keys() -> frozenset[str]:
        """Return the set of format keys that use the PSMUtils normalizer pathway."""
        return frozenset({'PEAKS', 'Sage', 'Percolator', 'mzIdentML', 'XTandem', 'IdXML', 'pepXML'})

    @staticmethod
    def search_file_dialog_filter() -> str:
        """Qt file-dialog filter string covering all supported search formats."""
        return (
            "Search Files "
            "(*.txt *.tsv *.psmtsv *.csv *.mzid *.idxml *.pin *.pout *.pepxml *.xml)"
            ";;All Files (*.*)"
        )