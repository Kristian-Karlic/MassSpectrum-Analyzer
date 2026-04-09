from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QApplication)
from PyQt6.QtCore import Qt, QMimeData, QPoint, pyqtProperty
from PyQt6.QtGui import QDrag, QPainter, QPixmap, QColor
from utils.style.style import EditorConstants
import json
import logging

# Set up logging
logger = logging.getLogger(__name__)


class DraggableListWidget(QListWidget):
    """Custom list widget that supports drag and drop"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)  
        self.setDefaultDropAction(Qt.DropAction.CopyAction) 

        self.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {EditorConstants.GRAY_300()};
                border-radius: {EditorConstants.BORDER_RADIUS_MEDIUM()}px;
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                selection-background-color: {EditorConstants.LIGHT_BLUE()};
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 8px;
                margin: 2px;
                border-radius: {EditorConstants.BORDER_RADIUS_SMALL()}px;
                background-color: white;
                border: 1px solid {EditorConstants.GRAY_200()};
            }}
            QListWidget::item:selected {{
                background-color: {EditorConstants.PRIMARY_BLUE()};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {EditorConstants.LIGHT_BLUE()};
            }}
        """)
    
    def mousePressEvent(self, event):
        """Handle mouse press for drag initiation"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for drag detection"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        
        if not hasattr(self, 'drag_start_position'):
            return
            
        if ((event.pos() - self.drag_start_position).manhattanLength() < 
            QApplication.startDragDistance()):
            return
        
        self.performDrag()
        
    def performDrag(self):
        """Perform the drag operation"""
        item = self.currentItem()
        if not item:
            logger.debug("No item selected for drag")
            return
        
        # Create drag object
        drag = QDrag(self)
        mimeData = QMimeData()
        
        # Set text data
        mimeData.setText(item.text())
        
        # Set peptide data if available
        if hasattr(item, 'peptide_data'):
            try:
                peptide_data_json = json.dumps(item.peptide_data, default=str)
                mimeData.setData("application/x-peptide-data", peptide_data_json.encode('utf-8'))
            except Exception as e:
                logger.error(f"Error encoding peptide data: {e}")
        
        # Set the mime data BEFORE creating pixmap
        drag.setMimeData(mimeData)
        
        # Create drag pixmap for visual feedback
        try:
            pixmap = QPixmap(300, 50)
            pixmap.fill(Qt.GlobalColor.lightGray)
            painter = QPainter(pixmap)
            painter.setPen(Qt.GlobalColor.black)
            
            # Draw text, truncated if necessary
            text = item.text()
            if len(text) > 40:
                text = text[:37] + "..."
            
            painter.drawText(5, 20, text.replace('\n', ' '))
            painter.end()
            
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(10, 25))
        except Exception as e:
            logger.error(f"Error creating drag pixmap: {e}")
        
        # Execute drag
        result = drag.exec(Qt.DropAction.CopyAction)
        logger.debug(f"Drag completed with result: {result}")

class DropZoneWidget(QListWidget):
    """Drop zone for organizing peptides into comparison groups"""
    
    def __init__(self, group_name, parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        
        self.placeholder_item = None
        self._is_drag_active = False

        # Build base stylesheet from theme (shared between init and update_theme)
        self._base_stylesheet = self._build_base_stylesheet()

        self._update_border_style(False)
        self.update_placeholder()

    def _build_base_stylesheet(self):
        """Build the base stylesheet template from current theme colors."""
        return """
            QListWidget {{{{
                border: 2px dashed {border_color};
                border-radius: {border_radius_medium}px;
                background-color: {background_color};
                selection-background-color: {selection_bg_color};
                font-size: 11px;
            }}}}
            QListWidget::item {{{{
                padding: 6px;
                margin: 2px;
                border-radius: {border_radius_small}px;
                background-color: {item_bg_color};
                border: 1px solid {item_border_color};
            }}}}
        """.format(
            border_color='{border_color}',  # This stays as placeholder
            border_radius_medium=EditorConstants.BORDER_RADIUS_MEDIUM(),
            background_color=EditorConstants.GRAY_50(),
            selection_bg_color=EditorConstants.LIGHT_BLUE(),
            border_radius_small=EditorConstants.BORDER_RADIUS_SMALL(),
            item_bg_color=EditorConstants.BACKGROUND_COLOR(),
            item_border_color=EditorConstants.GRAY_200()
        )
    
    def _update_border_style(self, is_drag_active):
        """Update border color based on drag state"""
        border_color = EditorConstants.PRIMARY_BLUE() if is_drag_active else EditorConstants.GRAY_300()
        self.setStyleSheet(self._base_stylesheet.format(border_color=border_color))
        self._is_drag_active = is_drag_active
        
    def update_placeholder(self):
        """Update placeholder text based on content"""
        self._remove_placeholder_if_exists()
        
        if self.count() == 0:
            placeholder = QListWidgetItem(f"Drop peptides here for {self.group_name}")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)  
            placeholder.setForeground(QColor(EditorConstants.DISABLED_COLOR()))
            self.addItem(placeholder)
            self.placeholder_item = placeholder
        
    def clear(self):
        """Override clear method to properly reset placeholder reference"""
        self.placeholder_item = None
        super().clear()
        self.update_placeholder()
        
    def dragEnterEvent(self, event):
        """Handle drag enter"""
        if event.mimeData().hasText():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._update_border_style(True)
        else:
            logger.debug("Rejecting drag - no text data")
            event.ignore()
        
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        self._update_border_style(False)
        super().dragLeaveEvent(event)
        
    def dragMoveEvent(self, event):
        """Handle drag move"""
        if event.mimeData().hasText():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()
        
    def dropEvent(self, event):
        """Handle drop event with duplicate detection"""
        if not event.mimeData().hasText():
            event.ignore()
            self._update_border_style(False)
            return
        
        peptide_text = event.mimeData().text()
        
        # Try to get peptide data
        peptide_data = self._extract_peptide_data(event.mimeData(), peptide_text)
        
        # Check for duplicate (same scan number in same group)
        if self._is_duplicate(peptide_data):
            logger.warning(f"Duplicate peptide detected (same scan): {peptide_text}")
            event.ignore()
            self._update_border_style(False)
            return
        
        # Remove placeholder before adding item
        self._remove_placeholder_if_exists()
        
        # Create and add item
        item = QListWidgetItem(peptide_text)
        item.peptide_data = peptide_data
        self.addItem(item)
        
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        
        # Reset border color
        self._update_border_style(False)
        logger.debug(f"Added peptide to group: {peptide_text}")
    
    def _extract_peptide_data(self, mime_data, peptide_text):
        """Extract peptide data from mime data or create minimal data"""
        try:
            peptide_data_bytes = mime_data.data("application/x-peptide-data")
            if peptide_data_bytes and not peptide_data_bytes.isEmpty():
                peptide_data_str = peptide_data_bytes.data().decode('utf-8')
                peptide_data = json.loads(peptide_data_str)
                
                # Validate required fields
                if not isinstance(peptide_data, dict):
                    logger.warning("Invalid peptide data format, using fallback")
                    return {'display_text': peptide_text}
                
                return peptide_data
        except Exception as e:
            logger.error(f"Error decoding peptide data: {e}")
        
        # Fallback: create minimal peptide data
        return {'display_text': peptide_text}
    
    def _is_duplicate(self, peptide_data):
        """Check if peptide is duplicate based on scan number and spectrum file
        
        Returns True only if the exact same row (same scan number + spectrum file) 
        already exists in this group. Same peptide sequence with different scans is allowed.
        """
        if not isinstance(peptide_data, dict):
            return False
        
        # Get identifying information from new peptide
        new_scan = str(peptide_data.get('index', ''))
        new_spectrum_file = peptide_data.get('Spectrum file', '')
        
        # If we don't have scan information, can't check for duplicates
        if not new_scan or new_scan == 'Unknown':
            return False
        
        # Check existing items in this group
        for i in range(self.count()):
            item = self.item(i)
            if hasattr(item, 'peptide_data') and isinstance(item.peptide_data, dict):
                existing_scan = str(item.peptide_data.get('index', ''))
                existing_spectrum_file = item.peptide_data.get('Spectrum file', '')
                
                # Check if this is the exact same row (same scan + file)
                if existing_scan == new_scan and existing_spectrum_file == new_spectrum_file:
                    logger.info(f"Duplicate detected: scan={new_scan}, file={new_spectrum_file}")
                    return True
        
        return False

    def _remove_placeholder_if_exists(self):
        """Remove placeholder if it exists"""
        if self.placeholder_item is not None:
            row = self.row(self.placeholder_item)
            if row >= 0:
                self.takeItem(row)
            self.placeholder_item = None
    
    def update_theme(self):
        """Update theme for drop zone and all items"""
        # Rebuild base stylesheet with new theme colors
        self._base_stylesheet = self._build_base_stylesheet()
        
        # Reapply border style with current drag state
        self._update_border_style(self._is_drag_active)
        
        # Update placeholder if it exists
        if self.placeholder_item:
            self.placeholder_item.setForeground(QColor(EditorConstants.DISABLED_COLOR()))
        
        # Force repaint
        self.update()
