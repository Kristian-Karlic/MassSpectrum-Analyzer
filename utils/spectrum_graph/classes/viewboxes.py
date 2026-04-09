import pyqtgraph as pg
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QGraphicsItem
from ..config.constants import PlotConstants


class _ViewBoxMixin:
    """Shared functionality for spectrum and error plot viewboxes."""

    def _init_common(self):
        self.initial_x_range = None
        self.initial_y_range = None
        self.plot_item = None
        self.linked_viewbox = None
        self.setMenuEnabled(False)

    def contextMenuEvent(self, ev):
        """Override to show custom context menu"""
        if hasattr(self, 'viewer_instance') and self.viewer_instance:
            pos = self.mapSceneToView(ev.pos())
            global_pos = ev.screenPos()
            self.viewer_instance.show_custom_context_menu(global_pos, self, pos)
        ev.accept()

    def set_plot_item(self, plot_item):
        """Store reference to the plot item for tick updates"""
        self.plot_item = plot_item

    def set_linked_viewbox(self, linked_viewbox):
        """Set reference to the linked viewbox for synchronized tick updates"""
        self.linked_viewbox = linked_viewbox

    def update_adaptive_x_ticks(self):
        """Update X-axis ticks using centralized logic with size awareness"""
        if hasattr(self, 'viewer_instance') and self.viewer_instance:
            x_range, _ = self.viewRange()
            plots = [self.plot_item]
            if self.linked_viewbox and self.linked_viewbox.plot_item:
                plots.append(self.linked_viewbox.plot_item)
            widget_width = self.size().width() if self.size().width() > 0 else 800
            self.viewer_instance._update_plot_ticks(x_range, plots, widget_width=widget_width)

    def _check_movable_item_under_cursor(self, ev):
        """Check if there's a movable item under the cursor that should handle the drag.
        Returns True if the event should be ignored (item handles it)."""
        if ev.button() == pg.QtCore.Qt.MouseButton.LeftButton:
            try:
                items = self.scene().items(ev.scenePos())
                for item in items:
                    if hasattr(item, 'flags') and callable(item.flags):
                        if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                            ev.ignore()
                            return True
            except Exception:
                pass
        return False

    def _enforce_min_x_range(self):
        """Enforce minimum X-axis zoom limit. Returns the current x_range."""
        x_range, _ = self.viewRange()
        x_width = x_range[1] - x_range[0]
        if x_width < PlotConstants.MIN_X_RANGE:
            x_center = (x_range[0] + x_range[1]) / 2
            self.setXRange(x_center - PlotConstants.MIN_X_RANGE / 2,
                           x_center + PlotConstants.MIN_X_RANGE / 2, padding=0)
            x_range = self.viewRange()[0]
        return x_range

    def _apply_smooth_wheel_zoom(self, ev, axis=None):
        """Apply wheel zoom with smoothness factor, returns original scale factor."""
        original_scale_factor = self.state['wheelScaleFactor']
        self.state['wheelScaleFactor'] = original_scale_factor * PlotConstants.ZOOM_SCALE_FACTOR
        pg.ViewBox.wheelEvent(self, ev, axis)
        self.state['wheelScaleFactor'] = original_scale_factor
        return original_scale_factor

    def _update_x_ticks_on_linked(self, x_range):
        """Update X-axis ticks using viewer instance for initial range."""
        if hasattr(self, 'viewer_instance') and self.viewer_instance and x_range:
            plots = [self.plot_item]
            if self.linked_viewbox and self.linked_viewbox.plot_item:
                plots.append(self.linked_viewbox.plot_item)
            self.viewer_instance._update_plot_ticks(x_range, plots)


class SpectrumPlotViewBox(_ViewBoxMixin, pg.ViewBox):
    # Signal to request custom context menu
    customContextMenuRequested = pyqtSignal(object, object)  # position, viewbox

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_common()

    def resizeEvent(self, ev):
        """Handle resize events to update tick density"""
        super().resizeEvent(ev)
        if self.plot_item and hasattr(self, 'viewer_instance'):
            x_range, _ = self.viewRange()
            plots = [self.plot_item]
            if self.linked_viewbox and self.linked_viewbox.plot_item:
                plots.append(self.linked_viewbox.plot_item)
            self.viewer_instance._update_plot_ticks(x_range, plots)

    def wheelEvent(self, ev, axis=None):
        # Get cursor position to determine which axis to zoom
        pos = ev.pos()
        plot_rect = self.sceneBoundingRect()

        y_axis_right_edge = plot_rect.left()
        x_axis_top_edge = plot_rect.bottom()

        Y_AXIS_ZONE_WIDTH = PlotConstants.Y_AXIS_WIDTH
        X_AXIS_ZONE_HEIGHT = 40

        from_left = pos.x() - y_axis_right_edge
        is_on_y_axis = (from_left < 0 and from_left >= -Y_AXIS_ZONE_WIDTH)

        from_bottom = pos.y() - x_axis_top_edge
        is_on_x_axis = (from_bottom > 0 and from_bottom <= X_AXIS_ZONE_HEIGHT)

        if is_on_y_axis:
            axis = 1
        elif is_on_x_axis:
            axis = 0
        else:
            axis = None

        self._apply_smooth_wheel_zoom(ev, axis)

        x_range = self._enforce_min_x_range()

        # Enforce minimum Y range
        _, y_range = self.viewRange()
        y_width = y_range[1] - y_range[0]
        if y_width < PlotConstants.MIN_Y_RANGE:
            y_center = (y_range[0] + y_range[1]) / 2
            self.setYRange(y_center - PlotConstants.MIN_Y_RANGE / 2,
                           y_center + PlotConstants.MIN_Y_RANGE / 2, padding=0)
            y_range = self.viewRange()[1]

        # Always keep Y minimum at 0 for spectrum plots
        self.setYRange(0, y_range[1], padding=0)

        # Prevent zooming out beyond initial X range
        if self.initial_x_range is not None:
            init_min, init_max = self.initial_x_range
            init_width = init_max - init_min
            current_width = x_range[1] - x_range[0]
            if current_width > init_width:
                self.setXRange(init_min, init_max, padding=0)

        if self.plot_item:
            self.update_adaptive_x_ticks()
            self.update_adaptive_y_ticks()

        ev.accept()

    def mouseDragEvent(self, ev, axis=None):
        if self._check_movable_item_under_cursor(ev):
            return

        super().mouseDragEvent(ev, axis)

        self._enforce_min_x_range()

        # Enforce minimum Y range
        _, y_range = self.viewRange()
        y_width = y_range[1] - y_range[0]
        if y_width < PlotConstants.MIN_Y_RANGE:
            y_center = (y_range[0] + y_range[1]) / 2
            self.setYRange(y_center - PlotConstants.MIN_Y_RANGE / 2,
                           y_center + PlotConstants.MIN_Y_RANGE / 2, padding=0)

        if self.plot_item:
            self.update_adaptive_x_ticks()
            self.update_adaptive_y_ticks()

    def update_adaptive_y_ticks(self):
        """Update Y-axis ticks based on current view range with dynamic spacing"""
        _, y_range = self.viewRange()
        y_min, y_max = y_range
        y_width = y_max - y_min

        tick_spacing = PlotConstants.auto_tick_spacing(
            y_width,
            target_ticks=PlotConstants.TARGET_SPECTRUM_Y_TICKS
        )

        tick_positions = PlotConstants.generate_tick_positions(y_min, y_max, tick_spacing)

        if tick_positions:
            y_ticks = PlotConstants.format_ticks(tick_positions, tick_spacing)
            self.plot_item.getAxis('left').setTicks(y_ticks)

    def reset_to_initial_ranges(self):
        """Reset view to initial ranges and force tick update"""
        if self.initial_x_range:
            self.setXRange(self.initial_x_range[0], self.initial_x_range[1], padding=0)
        if self.initial_y_range:
            self.setYRange(self.initial_y_range[0], self.initial_y_range[1], padding=0)

        if self.plot_item:
            left_axis = self.plot_item.getAxis('left')
            left_axis.setTicks([[(i, str(i)) for i in range(0, 101, PlotConstants.MAJOR_TICK_SPACING_SPECTRUM)]])
            self._update_x_ticks_on_linked(self.initial_x_range)


class ErrorplotViewBox(_ViewBoxMixin, pg.ViewBox):
    """Bottom plot logic: only X zoom, clamp Y to [-10,10] or threshold."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_common()
        self.setMouseEnabled(x=True, y=False)
        self.fixed_y_min = PlotConstants.ERROR_Y_RANGE[0]
        self.fixed_y_max = PlotConstants.ERROR_Y_RANGE[1]

    def mouseMoveEvent(self, ev):
        """Handle mouse movement over the error plot"""
        super().mouseMoveEvent(ev)

        if hasattr(self, 'viewer_instance') and self.viewer_instance:
            pos = self.mapSceneToView(ev.scenePos())
            self.viewer_instance.handle_error_plot_hover(pos)

        ev.accept()

    def update_y_axis_limits(self, ppm_tolerance):
        """Update Y-axis limits and ticks for new PPM tolerance with padding"""
        padding_factor = 0.1
        padding = ppm_tolerance * padding_factor

        self.fixed_y_min = -ppm_tolerance - padding
        self.fixed_y_max = ppm_tolerance + padding

        if self.initial_y_range is None:
            self.initial_y_range = (self.fixed_y_min, self.fixed_y_max)

        self.setYRange(self.fixed_y_min, self.fixed_y_max, padding=0)

        QTimer.singleShot(0, lambda: self._delayed_tick_update(ppm_tolerance))

    def _delayed_tick_update(self, user_tolerance):
        """Delayed tick update to ensure range is set first"""
        self.update_adaptive_y_ticks(user_tolerance)

    def update_adaptive_y_ticks(self, user_tolerance=None):
        """Update Y-axis ticks with maximum 5 ticks to prevent overlap"""
        if not self.plot_item:
            return

        if user_tolerance is not None:
            y_range_total = user_tolerance * 2
            user_min = -user_tolerance
            user_max = user_tolerance
        else:
            y_range_total = self.fixed_y_max - self.fixed_y_min
            user_min = self.fixed_y_min
            user_max = self.fixed_y_max

        tick_spacing = PlotConstants.auto_tick_spacing(
            y_range_total,
            target_ticks=4
        )

        tick_positions = PlotConstants.generate_tick_positions(user_min, user_max, tick_spacing)

        # If we still have too many ticks (>5), double the spacing
        if len(tick_positions) > 5:
            tick_spacing *= 2
            tick_positions = PlotConstants.generate_tick_positions(user_min, user_max, tick_spacing)

        if tick_positions:
            y_ticks = PlotConstants.format_ticks(tick_positions, tick_spacing)
            self.plot_item.getAxis('left').setTicks(y_ticks)

    def mouseDragEvent(self, ev, axis=None):
        if self._check_movable_item_under_cursor(ev):
            return

        super().mouseDragEvent(ev, axis)

        self._enforce_min_x_range()

        # Always clamp to current fixed limits after any drag
        self.setYRange(self.fixed_y_min, self.fixed_y_max, padding=0)
        if self.plot_item:
            self.update_adaptive_x_ticks()

    def reset_to_initial_ranges(self):
        """Reset view to initial ranges and force tick update"""
        if self.initial_x_range:
            self.setXRange(self.initial_x_range[0], self.initial_x_range[1], padding=0)
        if self.initial_y_range:
            self.setYRange(self.initial_y_range[0], self.initial_y_range[1], padding=0)

        if self.plot_item:
            y_range_total = self.fixed_y_max - self.fixed_y_min
            user_tolerance = y_range_total / 2.2

            QTimer.singleShot(0, lambda: self._delayed_tick_update(user_tolerance))
            self._update_x_ticks_on_linked(self.initial_x_range)

    def wheelEvent(self, ev, axis=None):
        """Enforce minimum X-axis zoom limit with improved sensitivity for smoothness"""
        self._apply_smooth_wheel_zoom(ev, axis)

        self._enforce_min_x_range()

        # Always clamp Y to fixed limits
        self.setYRange(self.fixed_y_min, self.fixed_y_max, padding=0)

        if self.plot_item:
            self.update_adaptive_x_ticks()
        ev.accept()
