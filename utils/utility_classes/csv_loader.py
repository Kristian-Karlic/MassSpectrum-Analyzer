import logging
import csv
from typing import List, Tuple, Any, Callable

logger = logging.getLogger(__name__)

class CSVLoader:
    """Utility class for loading CSV files with type conversion"""

    @staticmethod
    def load_csv_with_conversion(
        path: str,
        columns: List[Tuple[str, Callable[[str], Any]]],
        skip_on_error: bool = True
    ) -> List[tuple]:
        """
        Loads data from a CSV file with specified column names and type conversions.

        Args:
            path: Path to the CSV file
            columns: List of tuples (column_name, conversion_function)
            skip_on_error: If True, skip rows with conversion errors; if False, raise exception

        Returns:
            List of tuples containing converted values

        Example:
            columns = [
                ("Name", str),
                ("Mass", float),
                ("Count", int)
            ]
            data = CSVLoader.load_csv_with_conversion("data.csv", columns)
        """
        results = []

        with open(path, "r", newline='') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Convert each column according to its conversion function
                    converted_values = []
                    for col_name, convert_fn in columns:
                        value = row[col_name]
                        converted = convert_fn(value)
                        converted_values.append(converted)

                    results.append(tuple(converted_values))

                except (ValueError, KeyError) as e:
                    if not skip_on_error:
                        raise ValueError(f"Error processing row: {row}") from e
                    continue

        return results

class DataGatherer:
    """Utility class for gathering data from loaded DataFrames"""

    @staticmethod
    def gather_custom_ion_series(selected_custom_ions_data):
        """Gather selected custom ion series from the new selection interface"""
        custom_ion_series_list = []

        for ion_data in selected_custom_ions_data:
            try:
                mass_offset = float(ion_data['Mass Offset'])
                custom_ion_series_list.append({
                    "name": ion_data['Series Name'],
                    "base": ion_data['Base Ion'],
                    "offset": mass_offset,
                    "color": ion_data['Color'],
                    "restriction": ion_data.get('Restriction', '')
                })
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid custom ion series: {e}")
                continue

        return custom_ion_series_list

    @staticmethod
    def gather_diagnostic_ions(selected_diagnostic_ions_data):
        """Gather selected diagnostic ions from the new selection interface"""
        result = []

        for ion_data in selected_diagnostic_ions_data:
            try:
                name = ion_data.get('Name', '')
                html_name = ion_data.get('HTML Name', name)  # Use HTML Name, fallback to Name
                mass = float(ion_data.get('Mass', 0.0))
                color = ion_data.get('Color', '#000000')

                if name and mass > 0:  # Only include valid entries
                    result.append((html_name, mass, color))
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid diagnostic ion: {e}")
                continue

        return result

    @staticmethod
    def build_mod_neutral_losses(modifications, central_mod_db, enable_labile=True,
                                 enable_remainder=True, enable_mod_nl=True):
        """Build per-modification neutral-loss configs from the central database.

        Args:
            modifications: list of (mass, position) tuples from Parsed Modifications
            central_mod_db: CentralModificationDatabase instance
            enable_labile: if False, labile_loss ~ ions are suppressed
            enable_remainder: if False, remainder ^ ions are suppressed
            enable_mod_nl: if False, modification-specific neutral losses (* ions) are suppressed

        Returns:
            list[dict | None] parallel to *modifications*, or None if nothing defined.
        """
        if not modifications or central_mod_db is None:
            return None

        result = []
        has_any = False

        for mass, _position in modifications:
            nl_config = central_mod_db.get_neutral_losses_for_mass(mass)
            if nl_config is not None:
                # Need the labile block to fire if either labile or remainder is requested
                effective_labile = enable_labile or enable_remainder
                if central_mod_db.has_active_neutral_loss(nl_config, effective_labile,
                                                          enable_mod_nl=enable_mod_nl):
                    cfg = dict(nl_config)
                    # labile_loss drives the block; suppress ~ ion separately via generate_labile_ion
                    if not effective_labile:
                        cfg["labile_loss"] = False
                    cfg["generate_labile_ion"] = enable_labile
                    if not enable_remainder:
                        cfg["remainder_ions"] = []
                    if not enable_mod_nl:
                        cfg["neutral_losses"] = []
                    has_any = True
                    result.append(cfg)
                else:
                    result.append(None)
            else:
                result.append(None)

        return result if has_any else None

    @staticmethod
    def _clean_scan_number(scan_str: str) -> str:
        """Clean scan number string by removing .0 and leading zeros"""
        try:
            # Remove .0 if present
            if scan_str.endswith('.0'):
                scan_str = scan_str[:-2]

            # Remove leading zeros but keep single zero
            scan_str = str(int(scan_str))

            return scan_str
        except ValueError as e:
            logger.error(f"Error cleaning scan number '{scan_str}': {str(e)}")
            return scan_str
