"""
Agent for the letter_show scenario.

Extensions over MonaAgent:
  * Battery — drains 3 % per 1000 px moved. Read from yaml as a fixed
    initial value or randomised 40~90 % when not specified.
  * ``update_color`` is driven by ``assigned_super_task_id`` (which
    super-task the agent currently belongs to), not by
    ``assigned_task_id``. This makes it visually obvious which agent
    is in which letter-cluster during phase-1 GRAPE allocation.

Everything else (rotation shim, mode-driven motion enablement, drawing
of the body circle / heading triangle, work_rate) is inherited from
``MonaAgent``.
"""
import random
from core.utils import config
from platforms.mona.mona_agent import MonaAgent


# Battery drain: 3% per 1000 px moved.
_BATTERY_DRAIN_PER_PX = 3.0 / 1000.0

# Super-task colour palette — used by Agent.update_color().
_ST_COLORS = {
    0: (30, 100, 220),   # ST_0 → blue
    1: (220, 50, 50),    # ST_1 → red
}


class Agent(MonaAgent):
    def __init__(self, agent_id, position, tasks_info, rotation=0,
                 seed=None, initial_battery=None):
        super().__init__(agent_id, position, tasks_info, rotation)

        # task_amount_done / work_rate are already initialised by MonaAgent.
        # Battery state.
        if initial_battery is not None:
            self.battery = float(initial_battery)
        else:
            rng = random.Random(seed) if seed is not None else random
            self.battery = rng.uniform(40.0, 90.0)
        self._prev_distance = 0.0

    def update(self):
        super().update()
        delta = self.distance_moved - self._prev_distance
        self.battery = max(0.0, self.battery - delta * _BATTERY_DRAIN_PER_PX)
        self._prev_distance = self.distance_moved

    def update_color(self):
        st_id = getattr(self, 'assigned_super_task_id', None)
        self.color = _ST_COLORS.get(st_id, (0, 0, 0))   # unassigned → black
