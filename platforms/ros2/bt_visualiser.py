# platforms/ros2/bt_visualiser.py
import pygame
from typing import Dict, Tuple

COLOR_MAP = {
    "RUNNING": (0, 102, 204),
    "SUCCESS": (0, 153, 0),
    "FAILURE": (204, 0, 0),
    "UNKNOWN": (128, 128, 128),
}
EDGE_ACTIVE = (0, 102, 204)
EDGE_INACTIVE = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)
BG_COLOR = (255, 255, 255)

NODE_WIDTH = 120
NODE_HEIGHT = 30
X_SPACING = 30
Y_SPACING = 50

FONT_NAME = "Arial"  # <- 추가: 폰트명 상수

def get_status(node) -> str:
    status = getattr(node, "status", None)
    if hasattr(status, "name"):
        return status.name
    return "UNKNOWN"

def _layout_tree(node, direction: str, depth: int = 0, layout=None, level_tracker=None):
    if layout is None:
        layout = {}
    if level_tracker is None:
        level_tracker = {}
    if depth not in level_tracker:
        level_tracker[depth] = 0
    else:
        level_tracker[depth] += 1
    axis_pos = level_tracker[depth]
    if direction == "Horizontal":
        layout[node] = (depth, axis_pos)
    else:
        layout[node] = (axis_pos, depth)
    if hasattr(node, "children"):
        for child in node.children:
            _layout_tree(child, direction, depth + 1, layout, level_tracker)
    return layout

def _grid_to_px(grid_xy, direction: str) -> Tuple[int, int]:
    gx, gy = grid_xy
    x = gx * (NODE_WIDTH + X_SPACING) + X_SPACING
    y = gy * (NODE_HEIGHT + Y_SPACING) + Y_SPACING
    return x, y

def _draw_node(surface, font, node, pos_xy, scale=1.0):
    x, y = pos_xy
    w = int(NODE_WIDTH * scale)
    h = int(NODE_HEIGHT * scale)
    status = get_status(node)
    fill = COLOR_MAP.get(status, (0, 0, 0))
    if getattr(node, "type", None) == "Condition":
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.ellipse(surface, fill, rect)
        pygame.draw.ellipse(surface, (0, 0, 0), rect, max(1, int(1*scale)))
    else:
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surface, fill, rect, border_radius=max(4, int(6*scale)))
        pygame.draw.rect(surface, (0, 0, 0), rect, max(1, int(1*scale)), border_radius=max(4, int(6*scale)))
    name = getattr(node, "name", "Node")
    text_surface = font.render(name, True, TEXT_COLOR)
    if text_surface.get_width() > w - 8:
        # 수정: get_name() 제거하고 고정 폰트명 사용
        small_font = pygame.font.SysFont(FONT_NAME, max(10, int(font.get_height() * 0.9)))
        text_surface = small_font.render(name, True, TEXT_COLOR)
    surface.blit(text_surface, (x + (w - text_surface.get_width()) // 2,
                                y + (h - text_surface.get_height()) // 2))

def _draw_edge(surface, pxy, cxy, direction: str, active: bool, scale=1.0):
    px, py = pxy
    cx, cy = cxy
    w = int(NODE_WIDTH * scale)
    h = int(NODE_HEIGHT * scale)
    color = EDGE_ACTIVE if active else EDGE_INACTIVE
    width = max(1, int(3*scale)) if active else max(1, int(1*scale))
    if direction == "Horizontal":
        start = (px + w, py + h//2)
        end   = (cx,     cy + h//2)
    else:
        start = (px + w//2, py + h)
        end   = (cx + w//2, cy)
    pygame.draw.line(surface, color, start, end, width)

class BTViewer:
    """Render-only viewer to draw a BT onto an existing pygame Surface."""
    def __init__(self, direction: str = "Vertical"):
        self.direction = direction
        self.scale = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self._dragging = False
        self._drag_origin = (0, 0)
        self._pan_origin = (0, 0)
        self.font = pygame.font.SysFont(FONT_NAME, 16)  # <- 동일 폰트 사용

    def handle_events(self, events) -> bool:
        """Return False if user requested to close via ESC."""
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    self.scale = min(2.5, self.scale + 0.1)
                elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                    self.scale = max(0.4, self.scale - 0.1)
                elif event.key == pygame.K_r:
                    self.scale = 1.0
                    self.pan_x = 0
                    self.pan_y = 0
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self._dragging = True
                    self._drag_origin = pygame.mouse.get_pos()
                    self._pan_origin = (self.pan_x, self.pan_y)
                elif event.button == 4:
                    self.scale = min(2.5, self.scale + 0.1)
                elif event.button == 5:
                    self.scale = max(0.4, self.scale - 0.1)
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self._dragging = False
            elif event.type == pygame.MOUSEMOTION and self._dragging:
                mx, my = pygame.mouse.get_pos()
                dx = mx - self._drag_origin[0]
                dy = my - self._drag_origin[1]
                self.pan_x = self._pan_origin[0] + dx
                self.pan_y = self._pan_origin[1] + dy
        return True

    def render_tree(self, surface, tree):
        surface.fill(BG_COLOR)
        layout = _layout_tree(tree, direction=self.direction)
        positions: Dict[object, Tuple[int, int]] = {
            node: _grid_to_px(grid_xy, self.direction) for node, grid_xy in layout.items()
        }

        def tx(pt):
            x, y = pt
            x = int(x * self.scale) + self.pan_x
            y = int(y * self.scale) + self.pan_y
            return x, y

        for parent, ppos in positions.items():
            if hasattr(parent, "children"):
                for child in parent.children:
                    cpos = positions[child]
                    active = (get_status(parent) == get_status(child) == "RUNNING")
                    _draw_edge(surface, tx(ppos), tx(cpos), self.direction, active, scale=self.scale)

        for node, pos in positions.items():
            _draw_node(surface, self.font, node, tx(pos), scale=self.scale)
