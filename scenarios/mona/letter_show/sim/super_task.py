import math
import pygame


def size_for_count(count):
    """Size formula: 3 tasks → 200px, 6 tasks → 300px, 9 tasks → 400px."""
    return 25 * (math.ceil(count / 3) + 1)


_COLORS = [
    (70, 130, 180),   # steel blue  – ST0
    (180,  80,  70),  # brick red   – ST1
    (70,  170,  90),  # green       – ST2
    (170, 120,  50),  # amber       – ST3
    (130,  60, 180),  # purple      – ST4
]


class SuperTask:
    """A visual grouping of consecutive Tasks shown as a semi-transparent square.

    Position  = average of member-task positions (updates each frame).
    Size (px) = size_for_count(n_members):  3→200,  6→300,  9→400.
    """

    def __init__(self, super_task_id: int, tasks: list, max_agents: int = None, size: int = None):
        self.super_task_id = super_task_id
        self.tasks = list(tasks)           # references to live Task objects
        self.size = size if size is not None else size_for_count(len(self.tasks))
        self.color = _COLORS[super_task_id % len(_COLORS)]
        self.font = pygame.font.Font(None, 22)
        self.max_agents = max_agents if max_agents is not None else len(tasks)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    # ── GRAPE / task-system compatibility aliases ──────────────────────
    @property
    def task_id(self) -> int:
        """Alias for GRAPE compatibility (expects task.task_id)."""
        return self.super_task_id

    @property
    def position(self) -> pygame.Vector2:
        """Alias so GRAPE's distance computation works (expects task.position)."""
        return self.center

    @property
    def amount(self) -> float:
        """Sum of remaining member-task amounts (used by GRAPE utility)."""
        return sum(t.amount for t in self.tasks if not t.completed)

    # ── Core properties ────────────────────────────────────────────────

    @property
    def center(self) -> pygame.Vector2:
        """Always recalculated from current task positions."""
        xs = [t.position[0] for t in self.tasks]
        ys = [t.position[1] for t in self.tasks]
        return pygame.Vector2(sum(xs) / len(xs), sum(ys) / len(ys))

    @property
    def completed(self) -> bool:
        return all(t.completed for t in self.tasks)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def draw(self, screen):
        if self.completed:
            return
        c = self.center
        half = self.size // 2
        rect = pygame.Rect(int(c.x - half), int(c.y - half), self.size, self.size)

        # Semi-transparent fill
        fill_surf = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
        fill_surf.fill((*self.color, 45))
        screen.blit(fill_surf, (rect.x, rect.y))

        # Solid border
        pygame.draw.rect(screen, self.color, rect, 2)


    def draw_id(self, screen):
        if self.completed:
            return
        c = self.center
        half = self.size // 2
        label = f"ST{self.super_task_id}  ({len(self.tasks)} tasks)"
        text_surf = self.font.render(label, True, self.color)
        screen.blit(text_surf, (int(c.x - half) + 4, int(c.y - half) + 4))
