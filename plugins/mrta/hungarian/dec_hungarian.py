import time

import numpy as np
from scipy.optimize import linear_sum_assignment
from core.utils import config, extract_agent_id, extract_task_id

# Configuration
LAMBDA = config['decision_making']['Hungarian']['task_reward_discount_factor']
DUMMY_COST = config['decision_making']['Hungarian']['dummy_cost']


class DistributedHungarian:

    def __init__(self, agent):
        self.agent = agent

        # Rebuilt each tick from messages by `_perceive_world`.
        self.perceived_agents = []
        self.perceived_tasks = []

        self.assigned_task = None

    # ==============================================================
    # Main Decision Logic
    # ==============================================================
    
    def decide(self, blackboard):
        _local_tasks_info = blackboard.get('local_tasks_info', {})
        messages = self.agent.messages_received

        self._perceive_world(messages, _local_tasks_info)
        self.assigned_task = self._run_centralized_hungarian()
        self._update_visualization()
        self._update_message(_local_tasks_info)

        return self.assigned_task.task_id if self.assigned_task else None

    # ==============================================================
    # Cluster / Task Synchronization (R / P)
    # ==============================================================

    def _perceive_world(self, messages, local_tasks):
        """Rebuild perceived_agents (cluster) and perceived_tasks from this
        tick's messages.
        """
        valid_msgs = [m for m in messages if m and 'agent_id' in m]

        candidates = {self.agent.agent_id: {
            'agent_id': self.agent.agent_id,
            'position': self.agent.position,
        }}
        for msg in valid_msgs:
            for peer in msg.get('agents_info', []):
                aid = extract_agent_id(peer)
                if aid is None or aid in candidates:
                    continue
                candidates[aid] = peer
        self.perceived_agents = [candidates[aid] for aid in sorted(candidates)]

        # perceived_tasks: own local + transitive (peers' tasks_info).
        tasks_by_id = dict(local_tasks)
        for msg in valid_msgs:
            for task in msg.get('tasks_info', []):
                tid = extract_task_id(task)
                if tid is None or tid in tasks_by_id:
                    continue
                tasks_by_id[tid] = task
        self.perceived_tasks = [tasks_by_id[tid] for tid in sorted(tasks_by_id)]

    # ==============================================================
    # Messaging
    # ==============================================================
    def _update_message(self, local_tasks):
        self.agent.message_to_share = {
            'agent_id': self.agent.agent_id,
            'position': self.agent.position,
            'agents_info': self.perceived_agents,
            'tasks_info': list(local_tasks.values()),
            'assigned_task_id': self.assigned_task.task_id if self.assigned_task else None,
            'updated_at': time.time(),
        }

    def _update_visualization(self):
        if self.assigned_task:
            self.agent.set_planned_tasks([self.assigned_task])
        else:
            self.agent.set_planned_tasks([])

    # ==============================================================
    # Centralised Hungarian Logic
    # ==============================================================

    AGENT_SPEED = 0.5  # used in the discounted-reward cost function

    def _run_centralized_hungarian(self):
        """Build the cost matrix from perceived_agents/perceived_tasks,
        solve via scipy's Hungarian, and return *this* agent's assigned
        Task object (or None).
        """
        local_agents = self.perceived_agents
        local_tasks = self.perceived_tasks
        num_agents = len(local_agents)
        num_tasks = len(local_tasks)
        n = max(num_agents, num_tasks)

        # Cost matrix — distance-discounted reward; dummy rows/cols padded with DUMMY_COST.
        weights = np.full((n, n), DUMMY_COST, dtype=float)
        if num_agents > 0 and num_tasks > 0:
            agent_pos = np.array([[a.get('position').x, a.get('position').y] for a in local_agents])
            task_pos = np.array([[t.position.x, t.position.y] for t in local_tasks])
            diff = agent_pos[:, np.newaxis, :] - task_pos[np.newaxis, :, :]
            distances = np.sqrt((diff ** 2).sum(axis=2))
            weights[:num_agents, :num_tasks] = 1.0 / (LAMBDA ** (distances / self.AGENT_SPEED))

        # Solve. `linear_sum_assignment` minimises cost
        w = np.where(np.isinf(weights), 1e9, weights)
        row_ind, col_ind = linear_sum_assignment(w)

        # Pick out my own (agent_id == self.agent.agent_id) row's match.
        my_agent_id = self.agent.agent_id
        for i, j in zip(row_ind.tolist(), col_ind.tolist()):
            if i >= num_agents:
                continue  # dummy agent row
            if extract_agent_id(local_agents[i]) != my_agent_id:
                continue
            return local_tasks[j] if j < num_tasks else None
        return None
