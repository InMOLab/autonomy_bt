"""Centralised Hungarian for cen_wrapper — uses scipy.linear_sum_assignment.

Algorithmically identical to the dec-side `plugins.mrta.hungarian.dec_hungarian`
(same scipy backend, same cost formula `1 / LAMBDA**(distance / AGENT_SPEED)`),
just centralised: the leader builds a single N×M cost matrix, runs scipy
once, and writes `task_allocations` to the blackboard. Loaded via yaml's
`decision_making.cen_plugin`.

A hand-rolled alternative (`hungarian_handrolled.py`) is archived for
reference — same cost formula, different bipartite-matching machinery; the
two yield identical assignments under our setup.
"""
import time
import numpy as np
import pygame
from scipy.optimize import linear_sum_assignment

from core.utils import config


LAMBDA = config['decision_making']['Hungarian']['task_reward_discount_factor']
DUMMY_COST = config['decision_making']['Hungarian'].get('dummy_cost', 0.0)
AGENT_SPEED = 0.5  # matches dec_hungarian's hardcoded value


class Hungarian:
    """Centralised Hungarian assignment via scipy.linear_sum_assignment."""

    def __init__(self, agent):
        self.agent = agent  # leader
        self.assigned_tasks = {}  # agent_id -> Task or None

    def decide(self, blackboard):
        _local_tasks_info = blackboard['local_tasks_info']
        if isinstance(_local_tasks_info, dict):
            _local_tasks_info = list(_local_tasks_info.values())
        _local_agents_info = blackboard['local_agents_info']

        # Always rerun 
        self._run_hungarian(_local_agents_info, _local_tasks_info)

        # Write central_plan + mirror to per-agent planned_tasks (visualisation).
        task_allocations = {}
        for _agent in _local_agents_info:
            agent_id = _agent.agent_id
            assigned_task = self.assigned_tasks.get(agent_id)
            _agent.set_planned_tasks([assigned_task] if assigned_task else [])
            task_allocations[agent_id] = [assigned_task.task_id] if assigned_task else []

        blackboard["central_plan"] = {
            'task_allocations': task_allocations,
            'created_at': time.time(),
        }

    def _run_hungarian(self, agents, tasks):
        """Build N×N cost matrix (square via dummy padding), run scipy, store assignment."""
        num_agents = len(agents)
        num_tasks = len(tasks)
        n = max(num_agents, num_tasks)
        weights = np.full((n, n), DUMMY_COST, dtype=float)

        if num_agents > 0 and num_tasks > 0:
            agent_pos = np.array([[a.position.x, a.position.y] for a in agents])
            task_pos = np.array([[t.position.x, t.position.y] for t in tasks])
            diff = agent_pos[:, np.newaxis, :] - task_pos[np.newaxis, :, :]
            distances = np.sqrt((diff ** 2).sum(axis=2))
            # reward = LAMBDA ** (d / AGENT_SPEED); maximised directly so the
            # algorithm's optimisation target equals the unified utility.
            weights[:num_agents, :num_tasks] = LAMBDA ** (distances / AGENT_SPEED)

        # scipy `maximize=True` maximises total reward; dummies (DUMMY_COST=0) are below any real reward in (0, 1].
        row_ind, col_ind = linear_sum_assignment(weights, maximize=True)

        self.assigned_tasks = {}
        for i, j in zip(row_ind, col_ind):
            if i >= num_agents or j >= num_tasks:
                continue  # dummy row/col — skip
            self.assigned_tasks[agents[i].agent_id] = tasks[j]

    @staticmethod
    def compute_weight_value(_self_unused, agent, task):
        """Same signature as v1 for `sim.save_static_results` score computation.
        Returns expected reward (matching the cost-matrix formula above)."""
        distance = agent.position.distance_to(pygame.Vector2(task.position))
        return LAMBDA ** (distance / AGENT_SPEED)
