"""Task class for cen_wrapper. Ported from `space-simulator-cendec/scenarios/features/cenwrapper/task.py`.

Only the import paths are changed:
  modules.utils                   →  core.utils + platforms.pygame.utils_pygame
  modules.base_task               →  platforms.pygame.base_task
  generate_task_positions(...)    →  generate_positions(...)
"""
import pygame
import random

from core.utils import config
from platforms.pygame.utils_pygame import generate_positions, generate_task_colors
from platforms.pygame.base_task import BaseTask


dynamic_task_generation = config['tasks'].get('dynamic_task_generation', {})
max_generations = (
    dynamic_task_generation.get('max_generations', 0)
    if dynamic_task_generation.get('enabled', False) else 0
)
tasks_per_generation = (
    dynamic_task_generation.get('tasks_per_generation', 0)
    if dynamic_task_generation.get('enabled', False) else 0
)

task_colors = generate_task_colors(
    config['tasks']['quantity'] + tasks_per_generation * max_generations
)


class Task(BaseTask):
    def __init__(self, task_id, position):
        super().__init__(task_id, position)
        self.amount = random.uniform(
            config['tasks']['amounts']['min'],
            config['tasks']['amounts']['max'],
        )
        self.radius = self.amount / config['simulation']['task_visualisation_factor']
        self.color = task_colors.get(self.task_id, (0, 0, 0))

    def draw(self, screen):
        self.radius = self.amount / config['simulation']['task_visualisation_factor']
        if not self.completed:
            pygame.draw.circle(screen, self.color, self.position, int(self.radius))

    def draw_task_id(self, screen):
        if not self.completed:
            text_surface = self.font.render(
                f"task_id {self.task_id}: {self.amount:.2f}",
                True, (250, 250, 250),
            )
            screen.blit(text_surface, (self.position[0], self.position[1]))


def generate_tasks(task_quantity=None, task_id_start=0, seed=None):
    if task_quantity is None:
        task_quantity = config['tasks']['quantity']
    task_locations = config['tasks']['locations']

    # cendec 의 modules/utils.generate_task_positions 와 동일한 seed
    # 분리 — task RNG 가 agent RNG 와 독립이도록 +1000 오프셋.
    task_seed = seed + 1000 if seed is not None else None

    tasks_positions = generate_positions(
        task_quantity,
        task_locations['x_min'],
        task_locations['x_max'],
        task_locations['y_min'],
        task_locations['y_max'],
        radius=task_locations['non_overlap_radius'],
        seed=task_seed,
    )

    return [Task(idx + task_id_start, pos) for idx, pos in enumerate(tasks_positions)]
