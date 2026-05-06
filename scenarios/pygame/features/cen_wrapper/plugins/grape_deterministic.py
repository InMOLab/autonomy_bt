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
from plugins.mrta.grape.grape import GRAPE as SharedGRAPE


class GRAPE(SharedGRAPE):
    def _initial_time_stamp(self):
        return self.agent.agent_id

    def _new_time_stamp(self):
        return self.agent.agent_id
