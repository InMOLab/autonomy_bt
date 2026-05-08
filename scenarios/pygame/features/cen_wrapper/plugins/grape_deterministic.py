"""Deterministic-mutex GRAPE for cen_wrapper experiments.

Inherits shared `plugins.mrta.grape.grape.GRAPE` and only overrides the
`time_stamp` hooks so that d-mutex resolves ties by `agent_id` instead of
a random number. Under a fully-connected network this makes the winner
deterministic (highest agent_id wins at equal evolution_number), which
matches the centralised `cen_grape.CenGRAPE` baseline. The 3-way
comparison (pure-dec ↔ wrapper ↔ cen_grape) then converges to the same
nash equilibrium for the static-mode equivalence experiment.

This variant is only loaded by the cen_wrapper yaml configs that opt in
via `decision_making.plugin: scenarios.pygame.features.cen_wrapper.
plugins.grape_deterministic.GRAPE`. The shared GRAPE retains its original
random `time_stamp` behaviour for all other consumers.
"""
from core.utils import config
from plugins.mrta.grape.grape import GRAPE as SharedGRAPE


SOCIAL_INHIBITION_FACTOR = config['decision_making']['GRAPE']['social_inhibition_factor']
LAMBDA = config['decision_making']['GRAPE']['task_reward_discount_factor']
AGENT_SPEED = 0.5  # matches CBBA / Hungarian for utility unification


class GRAPE(SharedGRAPE):
    def _initial_time_stamp(self):
        return self.agent.agent_id

    def _new_time_stamp(self):
        return self.agent.agent_id

    def compute_utility(self, task):
        """Utility: lambda^(d/v) / |C|^alpha.

        Replaces the shared GRAPE's `task.amount / |C| - w * d * |C|^alpha`
        formulation so that GRAPE's optimisation target shares the
        time-discounted-reward shape used by CBBA and Hungarian, while
        preserving the social-inhibition coalition-formation pressure.
        """
        if task is None:
            return float('-inf')

        self.partition.setdefault(task.task_id, set())
        num_collaborator = len(self.partition[task.task_id])
        if self.agent.agent_id not in self.partition[task.task_id]:
            num_collaborator += 1

        distance = (self.agent.position - task.position).length()
        return (LAMBDA ** (distance / AGENT_SPEED)) / (num_collaborator ** SOCIAL_INHIBITION_FACTOR)
