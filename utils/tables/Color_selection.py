from PyQt6.QtWidgets import (QStyledItemDelegate, QColorDialog)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt
class ColorDelegate(QStyledItemDelegate):
    """
    A delegate that shows a QColorDialog when the user edits the cell.
    Once a color is chosen, it stores the HEX code (#RRGGBB) in the cell text.
    Also displays the color as background.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, parent, option, index):
        """
        Called when the user wants to edit the cell. We'll open a QColorDialog here.
        """
        # Step 1: open a color dialog
        dialog = QColorDialog(parent)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        
        # Apply consistent styling to the dialog
        dialog.setStyleSheet("""
            QColorDialog {
                background-color: #ffffff;
                color: #333333;
                font-family: "Segoe UI", "Arial", sans-serif;
            }
        """)
        
        # If the cell already has a color, pre-load it
        existing_text = index.data()  # e.g. "#FF0000"
        if existing_text:
            color = QColor(existing_text)
            if color.isValid():
                dialog.setCurrentColor(color)
        
        # Execute dialog and get result
        if dialog.exec():
            chosen_color = dialog.currentColor()
            # Convert to hex string
            chosen_color.setAlpha(255)
            # Convert to plain "#RRGGBB" format
            hex_str = chosen_color.name()  # e.g. "#FF0000", no alpha
            
            # Immediately update the model with the new color
            model = index.model()
            model.setData(index, hex_str, Qt.ItemDataRole.EditRole)
            model.setData(index, hex_str, Qt.ItemDataRole.DisplayRole)
            
            # Trigger a repaint
            if hasattr(parent, 'viewport'):
                parent.viewport().update()
        
        # Return None to prevent creating a standard editor
        return None
        
    def paint(self, painter, option, index):
        """
        Custom paint method to show the color as background
        """
        # Get the color value from the model
        color_value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        
        if color_value:
            try:
                color = QColor(color_value)
                if color.isValid():
                    # Fill the cell with the color
                    painter.fillRect(option.rect, color)
                    
                    # Add text with contrasting color
                    text_color = QColor("white") if color.lightness() < 128 else QColor("black")
                    painter.setPen(text_color)
                    painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, color_value)
                    return
            except Exception:
                pass
        
        # Fallback to default painting
        super().paint(painter, option, index)