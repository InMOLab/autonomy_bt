"""Agent class for cen_wrapper. Ported from
`space-simulator-cendec/scenarios/features/cenwrapper/agent.py`.

Import path changes:
  modules.utils                   →  core.utils + platforms.pygame.utils_pygame
  modules.base_agent              →  platforms.pygame.base_agent
  generate_agent_positions(...)   →  generate_positions(...)

The per-type BT XML pattern (`agents.types.<X>.behavior_tree_xml`) is
preserved as in the cendec original — each agent picks its BT file from
its `type` config block and creates its tree before BTRunner.initialize
runs (BTRunner skips if `agent.tree` is already set).
"""
import os
import math
import pygame

from core.utils import config
from platforms.pygame.utils_pygame import generate_positions
from platforms.pygame.base_agent import BaseAgent
from scenarios.pygame.features.cen_wrapper.sim.task import task_colors


# Load agent configuration (Scenario Specific)
work_rate = config['agents']['work_rate']


class Agent(BaseAgent):
    def __init__(self, agent_id, position, tasks_info):
        super().__init__(agent_id, position, tasks_info)
        self.work_rate = work_rate
        self.task_amount_done = 0.0

    def draw(self, screen):
        size = 10
        angle = self.rotation

        p1 = pygame.Vector2(
            self.position.x + size * math.cos(angle),
            self.position.y + size * math.sin(angle),
        )
        p2 = pygame.Vector2(
            self.position.x + size * math.cos(angle + 2.5),
            self.position.y + size * math.sin(angle + 2.5),
        )
        p3 = pygame.Vector2(
            self.position.x + size * math.cos(angle - 2.5),
            self.position.y + size * math.sin(angle - 2.5),
        )

        self.update_color()
        pygame.draw.polygon(screen, self.color, [p1, p2, p3])

    def update_color(self):
        self.color = task_colors.get(
            self.assigned_task_id, (20, 20, 20)
        )  # Default to dark grey when no task assigned

    def draw_communication_radius_circle(self, screen):
        if self.communication_radius > 0:
            pygame.draw.circle(
                screen, self.color,
                (self.position[0], self.position[1]),
                self.communication_radius, 1,
            )

    def draw_leader_communication_radius_circle(self, screen):
        if self.communication_radius > 0:
            circle_color = (255, 0, 0)
            line_width = 3
            pygame.draw.circle(
                screen, circle_color,
                (int(self.position.x), int(self.position.y)),
                self.communication_radius, line_width,
            )

    def draw_leader_communication_topology(self, screen, agents):
        """Draw lines from leader to its currently nearby agents."""
        if self.type == "Leader":
            for neighbor_agent in self.agents_nearby:
                neighbor_position = agents[neighbor_agent.agent_id].position
                pygame.draw.line(
                    screen, (255, 0, 0),
                    (int(self.position.x), int(self.position.y)),
                    (int(neighbor_position.x), int(neighbor_position.y)),
                )


def generate_agents(tasks_info, seed=None):
    """Build agents from `agents.types.<TypeName>` config blocks.

    Each type can have its own quantity, BT XML, and per-type attributes
    (communication_radius, situation_awareness_radius, ...). The trees
    are pre-built here so BTRunner.initialize will skip its standard
    single-XML build path.
    """
    agent_types_cfg = config['agents']['types']
    agent_locations = config['agents']['locations']

    agent_types_sequence = []
    behavior_tree_xml_sequence = []

    # Followers first, leader last — keeps leader as the highest agent_id
    # so that other code (e.g. `agents_info[-1]`) can find the leader fast.
    for agent_type, type_cfg in agent_types_cfg.items():
        if agent_type != 'Leader':
            count = int(type_cfg['quantity'])
            bt_xml = type_cfg['behavior_tree_xml']
            agent_types_sequence.extend([str(agent_type)] * count)
            behavior_tree_xml_sequence.extend([bt_xml] * count)

    if 'Leader' in agent_types_cfg:
        leader_cfg = agent_types_cfg['Leader']
        count = int(leader_cfg['quantity'])
        bt_xml = leader_cfg['behavior_tree_xml']
        agent_types_sequence.extend(['Leader'] * count)
        behavior_tree_xml_sequence.extend([bt_xml] * count)

    total_quantity = len(agent_types_sequence)

    agents_positions = generate_positions(
        total_quantity,
        agent_locations['x_min'],
        agent_locations['x_max'],
        agent_locations['y_min'],
        agent_locations['y_max'],
        radius=agent_locations['non_overlap_radius'],
        seed=seed,
    )

    agents = [Agent(idx, pos, tasks_info) for idx, pos in enumerate(agents_positions)]

    # Per-type config keys to skip when copying onto the agent
    exclude_keys = {'behavior_tree_xml', 'quantity'}

    for agent, agent_type in zip(agents, agent_types_sequence):
        agent.set_agent_type(agent_type)

        # Copy per-type attributes onto the agent
        type_config = agent_types_cfg[agent_type]
        for key, value in type_config.items():
            if key not in exclude_keys:
                setattr(agent, key, value)

    # Provide global agent info to each agent
    for agent in agents:
        agent.set_global_info_agents(agents)

    # Pre-build per-agent behaviour trees (BTRunner.initialize will skip).
    scenario_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for agent, bt_xml in zip(agents, behavior_tree_xml_sequence):
        behavior_tree_xml_path = os.path.join(scenario_dir, bt_xml)
        agent.create_behavior_tree(behavior_tree_xml_path)

    return agents
