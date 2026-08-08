"""
Scenario-specific Agent for the basic MONA scenario. Wires the
per-scenario ``task_colors`` palette into MonaAgent — everything else
(rotation shim, real-robot wiring, drawing, work_rate, body_radius) is
handled by MonaAgent itself based on ``mona.mode``.
"""
from platforms.mona.mona_agent import MonaAgent
from scenarios.mona.basic.sim.task import task_colors


class Agent(MonaAgent):
    def __init__(self, agent_id, position, tasks_info, rotation=0):
        super().__init__(agent_id, position, tasks_info, rotation,
                         task_colors=task_colors)
