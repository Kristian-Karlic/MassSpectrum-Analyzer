class PositionCalculator:
    """Centralized position calculation for consistent coordinate mapping"""
    
    def __init__(self, start_x, letter_spacing, sequence_length):
        self.start_x = start_x  # This will now be calculated to center the sequence
        self.letter_spacing = letter_spacing
        self.sequence_length = sequence_length
    
    def get_amino_acid_position(self, index):
        """Get X position for amino acid at given index (0-based)"""
        return self.start_x + (index * self.letter_spacing)
    
    def get_amino_acid_position_1_based(self, position):
        """Get X position for amino acid at given position (1-based)"""
        return self.start_x + ((position - 1) * self.letter_spacing)
    
    def get_fragment_line_position(self, position, ion_type):
        """Get X position for fragment line based on ion type and position"""
        if ion_type.lower() in ['x', 'y', 'z', 'w', 'v', 'd']:
            # C-terminal ions: position between amino acids (after position)
            if position >= self.sequence_length:
                return self.start_x + ((self.sequence_length - 1) * self.letter_spacing) + (self.letter_spacing / 2)
            return self.start_x + ((position - 1) * self.letter_spacing) + (self.letter_spacing / 2)
        else:
            # N-terminal ions: position between amino acids (before position)
            if position <= 0:
                return self.start_x - (self.letter_spacing / 2)
            return self.start_x + ((position) * self.letter_spacing) - (self.letter_spacing / 2)
    
    def find_nearest_position_from_x(self, x_coord):
        """Find nearest amino acid position from X coordinate"""
        if self.sequence_length == 0:
            return 1
        
        # Calculate relative position from start
        relative_x = x_coord - self.start_x
        position = round(relative_x / self.letter_spacing) + 1
        
        # Clamp to valid range
        return max(1, min(position, self.sequence_length))
    
    def get_modification_position(self, position: int) -> float:
        """Get x position for modifications (1-based position)"""
        return self.get_amino_acid_position_1_based(position)
    
