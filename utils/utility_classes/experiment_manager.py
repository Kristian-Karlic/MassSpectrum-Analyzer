import logging
import os
import pickle
from datetime import datetime
import pandas as pd
from typing import List, Tuple

logger = logging.getLogger(__name__)

class ExperimentManager:
    """Utility class for saving/loading experiments"""

    @staticmethod
    def create_experiment_data(app_instance) -> dict:
        """Create experiment data dictionary from app state"""


        return {
            'metadata': {
                'created_date': datetime.now().isoformat(),
                'version': '1.0',
                'app_version': 'Labile Annotation v1.0',
                'total_psms': len(app_instance.merged_df) if hasattr(app_instance, 'merged_df') else 0,
                'unique_peptides': app_instance.merged_df['Peptide'].nunique() if hasattr(app_instance, 'merged_df') and 'Peptide' in app_instance.merged_df.columns else 0,
                'raw_files_count': len(app_instance.raw_files),
                'search_files_count': len(app_instance.search_files),
                'description': f"Experiment with {len(app_instance.merged_df) if hasattr(app_instance, 'merged_df') else 0} PSMs"
            },
            'file_paths': {
                'raw_files': app_instance.raw_files,
                'search_files': app_instance.search_files,
                'df_file_paths': app_instance.df_file_paths.to_dict('records') if not app_instance.df_file_paths.empty else []
            },
            'settings': {
                'ppm_tolerance': app_instance.ppm_tolerance_input.value(),
                'text_annotation_threshold': app_instance.text_annotation_threshold.value()
            },
            'extracted_spectral_data': getattr(app_instance, 'extracted_spectral_data', {}),
            'merged_df': app_instance.merged_df.to_dict('records') if hasattr(app_instance, 'merged_df') else []
        }

    @staticmethod
    def save_experiment(app_instance, file_path: str) -> bool:
        """Save experiment to file"""
        try:
            experiment_data = ExperimentManager.create_experiment_data(app_instance)

            with open(file_path, 'wb') as f:
                pickle.dump(experiment_data, f)
            return True
        except Exception as e:
            logger.error(f"Error saving experiment: {e}")
            return False

    @staticmethod
    def load_experiment(file_path: str) -> Tuple[bool, dict, str]:
        """Load experiment from file"""
        try:

            with open(file_path, 'rb') as f:
                experiment_data = pickle.load(f)

            if ExperimentManager.validate_experiment_file(experiment_data):
                return True, experiment_data, ""
            else:
                return False, {}, "Invalid experiment file format"

        except Exception as e:
            return False, {}, f"Error loading experiment: {str(e)}"

    @staticmethod
    def validate_experiment_file(experiment_data: dict) -> bool:
        """Validate experiment file structure"""
        try:
            required_keys = ['metadata', 'file_paths', 'merged_df']
            for key in required_keys:
                if key not in experiment_data:
                    return False

            metadata = experiment_data['metadata']
            if not isinstance(metadata, dict) or 'created_date' not in metadata:
                return False

            file_paths = experiment_data['file_paths']
            if not isinstance(file_paths, dict):
                return False

            merged_df = experiment_data['merged_df']
            if not isinstance(merged_df, list):
                return False

            return True
        except:
            return False

    @staticmethod
    def check_file_existence(file_paths: dict) -> List[str]:
        """Check which files are missing"""
        missing_files = []

        for raw_file in file_paths.get('raw_files', []):
            if not os.path.exists(raw_file):
                missing_files.append(f"Raw: {os.path.basename(raw_file)}")

        for search_file in file_paths.get('search_files', []):
            if not os.path.exists(search_file):
                missing_files.append(f"Search: {os.path.basename(search_file)}")

        return missing_files
