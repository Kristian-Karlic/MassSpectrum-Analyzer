"""
Determine Protein Coverage from PSM data and a matching FASTA file, and visualize it in HTML.
"""
import pandas as pd
from typing import Dict, List, Tuple, Set
from pathlib import Path
import ast


class FastaParser:
    """Parse FASTA files and extract protein sequences."""
    
    @staticmethod
    def parse_fasta(fasta_path: str) -> Dict[str, Dict[str, str]]:
        """
        Parse a FASTA file and return protein information.
        
        Args:
            fasta_path: Path to FASTA file
            
        Returns:
            Dict mapping accession to {'description': str, 'sequence': str}
        """
        proteins = {}
        current_accession = None
        current_description = None
        current_sequence = []
        
        with open(fasta_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith('>'):
                    # Save previous protein if exists
                    if current_accession:
                        proteins[current_accession] = {
                            'description': current_description,
                            'sequence': ''.join(current_sequence)
                        }
                    
                    # Parse new header
                    header = line[1:]  # Remove '>'
                    # Extract accession (first word)
                    parts = header.split(None, 1)
                    current_accession = parts[0]
                    current_description = parts[1] if len(parts) > 1 else ""
                    current_sequence = []
                else:
                    # Accumulate sequence
                    current_sequence.append(line)
            
            # Save last protein
            if current_accession:
                proteins[current_accession] = {
                    'description': current_description,
                    'sequence': ''.join(current_sequence)
                }
        
        return proteins


class PeptideMapper:
    """Map peptides to protein sequences and calculate coverage."""
    
    @staticmethod
    def parse_peptide_modifications(parsed_mods) -> List[Tuple[int, float]]:
        """
        Convert pre-parsed modifications to 0-based (position, mass) tuples.

        Args:
            parsed_mods: List of (mass, position) tuples from 'Parsed Modifications' column,
                         or string representation, or None/NaN.

        Returns:
            List of (position, mass) tuples (0-based positions)
        """
        if parsed_mods is None or (isinstance(parsed_mods, float) and pd.isna(parsed_mods)):
            return []

        if isinstance(parsed_mods, str):
            if not parsed_mods:
                return []
            parsed_mods = ast.literal_eval(parsed_mods)

        if not parsed_mods:
            return []

        # Convert from (mass, position) 1-based to (position-1, mass) 0-based
        return [(pos - 1, mass) for mass, pos in parsed_mods]
    
    
    @staticmethod
    def find_peptide_positions(peptide: str, protein_sequence: str) -> List[int]:
        """
        Find all positions where peptide occurs in protein sequence.
        
        Args:
            peptide: Cleaned peptide sequence
            protein_sequence: Full protein sequence
            
        Returns:
            List of starting positions (0-based)
        """
        positions = []
        start = 0
        
        while True:
            pos = protein_sequence.find(peptide, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + 1
        
        return positions
    
    @staticmethod
    def calculate_coverage(covered_positions: Set[int], protein_length: int) -> float:
        """
        Calculate protein coverage percentage.
        
        Args:
            covered_positions: Set of covered amino acid positions (0-based)
            protein_length: Total length of protein
            
        Returns:
            Coverage percentage (0-100)
        """
        if protein_length == 0:
            return 0.0
        return (len(covered_positions) / protein_length) * 100


class ProteinCoverageAnalyzer:
    """Main class for analyzing protein coverage from PSM data."""
    
    def __init__(self, fasta_path: str):
        """
        Initialize with FASTA file.
        
        Args:
            fasta_path: Path to protein FASTA file
        """
        self.proteins = FastaParser.parse_fasta(fasta_path)
        print(f"Loaded {len(self.proteins)} proteins from FASTA")
    
    def analyze_psm_data(self, psm_df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze PSM data and calculate protein coverage.
        
        Args:
            psm_df: DataFrame with columns including 'Protein', 'Peptide', 'Assigned Modifications'
            
        Returns:
            DataFrame with columns: Protein, Unique_Peptides, Coverage_Percent, 
                                   Length, Covered_AAs, Description, Sequence
        """
        # Ensure required columns exist
        if 'Protein' not in psm_df.columns:
            raise ValueError("PSM DataFrame must contain 'Protein' column")
        
        if 'Peptide' not in psm_df.columns:
            raise ValueError("PSM DataFrame must contain 'Peptide' column")

        results = []
        
        # Group by protein
        grouped = psm_df.groupby('Protein')
        
        for protein_accession, group in grouped:
            # Get unique peptides and filter out NaN/empty values
            unique_peptides_data = group[['Peptide', 'Assigned Modifications', 'Peptide Length']].drop_duplicates()
            unique_peptides_data = unique_peptides_data[unique_peptides_data['Peptide'].notna()]
            
            # Skip if no valid peptides
            if len(unique_peptides_data) == 0:
                continue
            
            # Check if protein exists in FASTA
            if protein_accession not in self.proteins:
                print(f"Warning: Protein '{protein_accession}' not found in FASTA file")
                continue
            
            protein_info = self.proteins[protein_accession]
            protein_sequence = protein_info['sequence']
            protein_length = len(protein_sequence)
            
            # Track covered positions and modifications
            covered_positions = set()
            peptide_mappings = []
            modification_sites = {}  # {protein_position: [mod_masses]}
            
            for _, row in unique_peptides_data.iterrows():
                peptide = row['Peptide']
                parsed_mods = row.get('Parsed Modifications')
                peptide_length = int(row.get('Peptide Length', len(peptide)))

                # Skip empty or invalid peptides
                if not isinstance(peptide, str) or peptide.strip() == '':
                    continue

                # Use pre-parsed modifications directly
                peptide_mods = PeptideMapper.parse_peptide_modifications(parsed_mods)
                
                # Find positions in protein
                positions = PeptideMapper.find_peptide_positions(
                    peptide, protein_sequence
                )
                
                if positions:
                    peptide_mappings.append({
                        'peptide': peptide,
                        'cleaned': peptide,
                        'positions': positions,
                        'modifications': peptide_mods
                    })
                    
                    # Mark covered positions and modifications
                    for start_pos in positions:
                        for i in range(len(peptide)):
                            covered_positions.add(start_pos + i)
                        
                        # Map modifications to protein positions
                        for peptide_pos, mod_mass in peptide_mods:
                            protein_pos = start_pos + peptide_pos
                            if protein_pos not in modification_sites:
                                modification_sites[protein_pos] = []
                            if mod_mass not in modification_sites[protein_pos]:
                                modification_sites[protein_pos].append(mod_mass)
                else:
                    print(f"Warning: Peptide '{peptide}' not found in protein '{protein_accession}'")
            
            # Calculate coverage
            coverage_percent = PeptideMapper.calculate_coverage(
                covered_positions, protein_length
            )
            
            results.append({
                'Protein': protein_accession,
                'Description': protein_info['description'],
                'Unique_Peptides': len(unique_peptides_data),
                'Length': protein_length,
                'Covered_AAs': len(covered_positions),
                'Coverage_Percent': coverage_percent,
                'Sequence': protein_sequence,
                'Peptide_Mappings': peptide_mappings,
                'Covered_Positions': covered_positions,
                'Modification_Sites': modification_sites
            })
        
        # Create DataFrame
        results_df = pd.DataFrame(results)
        
        # Sort by coverage descending
        results_df = results_df.sort_values('Coverage_Percent', ascending=False)
        
        return results_df


class CoverageHTMLGenerator:
    """Generate HTML visualizations for protein coverage."""
    
    # Color palette for modifications
    MOD_COLORS = [
        '#e74c3c',  # Red
        '#f39c12',  # Orange
        '#f1c40f',  # Yellow
        '#2ecc71',  # Green
        '#1abc9c',  # Turquoise
        '#3498db',  # Blue (default coverage)
        '#9b59b6',  # Purple
        '#e91e63',  # Pink
        '#ff5722',  # Deep Orange
        '#795548',  # Brown
        '#607d8b',  # Blue Grey
        '#00bcd4',  # Cyan
    ]
    
    @staticmethod
    def assign_modification_colors(modification_sites: Dict[int, List[float]]) -> Dict[float, str]:
        """
        Assign unique colors to each unique modification mass.
        
        Args:
            modification_sites: Dict mapping position to list of modification masses
            
        Returns:
            Dict mapping modification mass to color hex code
        """
        # Get all unique modification masses
        unique_mods = set()
        for mods in modification_sites.values():
            unique_mods.update(mods)
        
        # Sort for consistency
        sorted_mods = sorted(unique_mods)
        
        # Assign colors
        mod_color_map = {}
        for idx, mod_mass in enumerate(sorted_mods):
            color_idx = idx % len(CoverageHTMLGenerator.MOD_COLORS)
            mod_color_map[mod_mass] = CoverageHTMLGenerator.MOD_COLORS[color_idx]
        
        return mod_color_map
    
    @staticmethod
    def generate_coverage_html(protein_accession: str, 
                               description: str,
                               sequence: str, 
                               covered_positions: Set[int],
                               peptide_mappings: List[Dict],
                               coverage_percent: float,
                               modification_sites: Dict[int, List[float]] = None) -> str:
        """
        Generate HTML visualization of protein coverage with modifications.
        
        Args:
            protein_accession: Protein identifier
            description: Protein description
            sequence: Full protein sequence
            covered_positions: Set of covered positions (0-based)
            peptide_mappings: List of peptide mapping information
            coverage_percent: Coverage percentage
            modification_sites: Dict mapping position to list of modification masses
            
        Returns:
            HTML string with highlighted coverage and modifications
        """
        if modification_sites is None:
            modification_sites = {}
        
        # Assign colors to modifications
        mod_color_map = CoverageHTMLGenerator.assign_modification_colors(modification_sites)
        html_parts = []
        
        # Header
        html_parts.append("""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: 'Courier New', monospace;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background-color: #2c3e50;
            color: white;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
        }
        .coverage-stats {
            background-color: #ecf0f1;
            padding: 10px;
            margin-bottom: 20px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }
        .sequence-container {
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            line-height: 1.8;
            font-size: 14px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .covered {
            background-color: #3498db;
            color: white;
            padding: 2px 1px;
            font-weight: bold;
        }
        .modified {
            color: white;
            padding: 2px 1px;
            font-weight: bold;
            border: 2px solid #2c3e50;
            position: relative;
        }
        .not-covered {
            color: #95a5a6;
        }
        .position-marker {
            color: #7f8c8d;
            font-size: 10px;
            display: inline-block;
            width: 60px;
            margin-right: 10px;
        }
        .sequence-line {
            margin: 5px 0;
        }
        .peptide-list {
            background-color: #ecf0f1;
            padding: 15px;
            margin-top: 20px;
            border-radius: 5px;
        }
        .peptide-item {
            margin: 5px 0;
            padding: 5px;
            background-color: white;
            border-radius: 3px;
        }
        .modification-legend {
            background-color: #ecf0f1;
            padding: 15px;
            margin-top: 20px;
            border-radius: 5px;
        }
        .mod-legend-item {
            display: inline-block;
            margin: 5px 10px 5px 0;
            padding: 5px 10px;
            border-radius: 3px;
            color: white;
            font-weight: bold;
            border: 2px solid #2c3e50;
        }
    </style>
</head>
<body>
""")
        
        # Protein header
        html_parts.append(f"""
    <div class="header">
        <h2>{protein_accession}</h2>
        <p>{description}</p>
    </div>
""")
        
        # Coverage statistics
        total_aa = len(sequence)
        covered_aa = len(covered_positions)
        num_modified_sites = len(modification_sites)
        
        html_parts.append(f"""
    <div class="coverage-stats">
        <strong>Coverage:</strong> {coverage_percent:.2f}% 
        ({covered_aa} / {total_aa} amino acids)<br>
        <strong>Unique Peptides:</strong> {len(peptide_mappings)}<br>
        <strong>Modified Sites:</strong> {num_modified_sites}
    </div>
""")
        
        # Modification legend (if any modifications exist)
        if mod_color_map:
            html_parts.append("""
    <div class="modification-legend">
        <h3>Modification Legend:</h3>
""")
            for mod_mass, color in sorted(mod_color_map.items()):
                html_parts.append(f"""
        <span class="mod-legend-item" style="background-color: {color};">
            {mod_mass:+.2f} Da
        </span>
""")
            html_parts.append("""
    </div>
""")
        
        # Sequence with highlighting
        html_parts.append('    <div class="sequence-container">\n')
        
        # Display sequence in lines of 60 characters
        line_length = 60
        for i in range(0, len(sequence), line_length):
            line_seq = sequence[i:i+line_length]
            html_parts.append(f'        <div class="sequence-line">')
            html_parts.append(f'<span class="position-marker">{i+1:5d}</span>')
            
            # Highlight each amino acid
            for j, aa in enumerate(line_seq):
                pos = i + j
                
                # Check if this position has modifications
                if pos in modification_sites and modification_sites[pos]:
                    # Use the first modification's color (if multiple, pick first)
                    mod_mass = modification_sites[pos][0]
                    color = mod_color_map[mod_mass]
                    # Create tooltip showing all modifications at this site
                    mods_str = ', '.join([f'{m:+.2f}' for m in modification_sites[pos]])
                    html_parts.append(
                        f'<span class="modified" style="background-color: {color};" '
                        f'title="Modified: {mods_str} Da">{aa}</span>'
                    )
                elif pos in covered_positions:
                    html_parts.append(f'<span class="covered">{aa}</span>')
                else:
                    html_parts.append(f'<span class="not-covered">{aa}</span>')
            
            html_parts.append('</div>\n')
        
        html_parts.append('    </div>\n')
        
        # Peptide list
        html_parts.append("""
    <div class="peptide-list">
        <h3>Detected Peptides:</h3>
""")
        
        for mapping in peptide_mappings:
            peptide_clean = mapping['cleaned']
            peptide_orig = mapping['peptide']
            positions_str = ', '.join([f"{pos+1}" for pos in mapping['positions']])
            
            # Show modifications if present
            modifications_info = ""
            if 'modifications' in mapping and mapping['modifications']:
                mod_details = []
                for pep_pos, mod_mass in mapping['modifications']:
                    aa = peptide_clean[pep_pos]
                    mod_details.append(f"{aa}{pep_pos+1}({mod_mass:+.2f})")
                modifications_info = f" <em>[Mods: {', '.join(mod_details)}]</em>"
            
            html_parts.append(f"""
        <div class="peptide-item">
            <strong>{peptide_clean}</strong> (position{'' if len(mapping['positions']) == 1 else 's'}: {positions_str}){modifications_info}
        </div>
""")
        
        html_parts.append("""
    </div>
</body>
</html>
""")
        
        return ''.join(html_parts)
