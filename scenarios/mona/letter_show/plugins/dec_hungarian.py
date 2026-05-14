"""
DistributedHungarian subclass for the letter_show scenario.

Two differences from the base class:

1. Super-task scoping:
   - ``_perceive_world()`` filters incoming messages to same-ST peers only,
     so the cost matrix never mixes agents/tasks across letter boundaries.
   - ``_update_message()`` tags outbound broadcasts with assigned_super_task_id
     so peers can apply the same filter on receive.

2. Objective function — restore the pre-``50ae3da`` formulation:
   minimise ``Σ 1/L^(d/v)`` (convex *increasing* cost) instead of
   maximise ``Σ L^(d/v)`` (convex *decreasing* reward).

   Both prefer short assignments, but on near-linear task layouts
   (e.g. the stems of letter_show letters) they pick different
   solutions: the cost form distributes burden across agents while
   the reward form concentrates it onto whoever is closest. The
   cost form matches the assignment letter_show was tuned for.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment

from plugins.mrta.hungarian.dec_hungarian import (
    DistributedHungarian as _BaseDH,
    LAMBDA,
    DUMMY_COST,
    AGENT_SPEED,
)
from core.utils import extract_agent_id


class DistributedHungarian(_BaseDH):

    def _perceive_world(self, messages, local_tasks):
        my_st_id = getattr(self.agent, 'assigned_super_task_id', None)
        scoped = [
            m for m in messages if m and
            (my_st_id is None or m.get('assigned_super_task_id') == my_st_id)
        ]
        super()._perceive_world(scoped, local_tasks)

    def _update_message(self, local_tasks):
        super()._update_message(local_tasks)
        self.agent.message_to_share['assigned_super_task_id'] = (
            getattr(self.agent, 'assigned_super_task_id', None)
        )

    def _run_centralized_hungarian(self):
        """Same structure as the base, but with the pre-``50ae3da`` cost
        formulation (``1/L^(d/v)``, minimise) instead of the reward
        formulation (``L^(d/v)``, maximise).
        """
        local_agents = self.perceived_agents
        local_tasks = self.perceived_tasks
        num_agents = len(local_agents)
        num_tasks = len(local_tasks)
        n = max(num_agents, num_tasks)

        # Cost matrix — distance-amplified cost; dummy rows/cols padded with DUMMY_COST.
        weights = np.full((n, n), DUMMY_COST, dtype=float)
        if num_agents > 0 and num_tasks > 0:
            agent_pos = np.array([[a.get('position').x, a.get('position').y] for a in local_agents])
            task_pos = np.array([[t.position.x, t.position.y] for t in local_tasks])
            diff = agent_pos[:, np.newaxis, :] - task_pos[np.newaxis, :, :]
            distances = np.sqrt((diff ** 2).sum(axis=2))
            weights[:num_agents, :num_tasks] = 1.0 / (LAMBDA ** (distances / AGENT_SPEED))

        # Solve. `linear_sum_assignment` minimises cost. Guard against inf padding
        # (LAMBDA=1.0 edge cases) by clamping to a large finite value.
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
