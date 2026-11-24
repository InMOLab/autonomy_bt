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

FONT_NAME = "Arial"
FONT_SIZE = 16
MIN_FONT_SIZE = 8

_fonts = {}

def _font(size):
    # Labels are re-rendered every frame at the current scale, so fonts are cached per size
    if size not in _fonts:
        _fonts[size] = pygame.font.SysFont(FONT_NAME, size)
    return _fonts[size]

def get_status(node) -> str:
    status = getattr(node, "status", None)
    if hasattr(status, "name"):
        return status.name
    return "UNKNOWN"

def _layout_tree(node, direction: str):
    # Fill each depth left to right with each parent centred over its children;
    # if that spot is taken, shift the whole subtree right.
    slot, depth_of, next_free = {}, {}, {}

    def shift(cur, dx):
        slot[cur] += dx
        depth = depth_of[cur]
        next_free[depth] = max(next_free.get(depth, 0), slot[cur] + 1)
        for child in getattr(cur, "children", None) or []:
            shift(child, dx)

    def visit(cur, depth):
        depth_of[cur] = depth
        children = getattr(cur, "children", None) or []
        for child in children:
            visit(child, depth + 1)
        slot[cur] = (slot[children[0]] + slot[children[-1]]) / 2 if children else next_free.get(depth, 0)
        if slot[cur] < next_free.get(depth, 0):
            shift(cur, next_free[depth] - slot[cur])
        next_free[depth] = slot[cur] + 1

    visit(node, 0)
    if direction == "Horizontal":
        return {n: (depth_of[n], s) for n, s in slot.items()}
    return {n: (s, depth_of[n]) for n, s in slot.items()}

def _grid_to_px(grid_xy, direction: str) -> Tuple[int, int]:
    gx, gy = grid_xy
    x = gx * (NODE_WIDTH + X_SPACING) + X_SPACING
    y = gy * (NODE_HEIGHT + Y_SPACING) + Y_SPACING
    return x, y

def _draw_node(surface, node, pos_xy, scale=1.0):
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
    # Show node.label if set (e.g. "MoveTo\n(Target_1)", one line per "\n"), else the name
    lines = (getattr(node, "label", None) or getattr(node, "name", "Node")).split("\n")
    # Shrink the font until the text fits (ellipses are narrower at the edges)
    max_w = w * 3 // 4 if getattr(node, "type", None) == "Condition" else w - 8
    size = max(MIN_FONT_SIZE, int(FONT_SIZE * scale))
    texts = [_font(size).render(line, True, TEXT_COLOR) for line in lines]
    while size > MIN_FONT_SIZE and (max(t.get_width() for t in texts) > max_w or sum(t.get_height() for t in texts) > h):
        size -= 1
        texts = [_font(size).render(line, True, TEXT_COLOR) for line in lines]
    ty = y + (h - sum(t.get_height() for t in texts)) // 2
    for text_surface in texts:
        surface.blit(text_surface, (x + (w - text_surface.get_width()) // 2, ty))
        ty += text_surface.get_height()

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

        # Shrink the tree to fit the window (never enlarge) and centre it horizontally
        tree_w = max(x for x, _ in positions.values()) + NODE_WIDTH + X_SPACING
        tree_h = max(y for _, y in positions.values()) + NODE_HEIGHT + Y_SPACING
        scale = min(1.0, surface.get_width() / tree_w, surface.get_height() / tree_h) * self.scale
        offset_x = (surface.get_width() - tree_w * scale) / 2

        def tx(pt):
            x, y = pt
            x = int(x * scale + offset_x) + self.pan_x
            y = int(y * scale) + self.pan_y
            return x, y

        for parent, ppos in positions.items():
            if hasattr(parent, "children"):
                for child in parent.children:
                    cpos = positions[child]
                    active = (get_status(parent) == get_status(child) == "RUNNING")
                    _draw_edge(surface, tx(ppos), tx(cpos), self.direction, active, scale=scale)

        for node, pos in positions.items():
            _draw_node(surface, node, tx(pos), scale=scale)
