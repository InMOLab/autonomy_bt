"""
Agent for the letter_show scenario.

Extensions over MonaAgent:
  * Battery:
      - full_simulation mode → drains 3 % per 1000 px moved. Read from yaml
        as a fixed initial value or randomised 40~90 % when not specified.
      - puppet mode (real robot) → the simulated drain is disabled; the
        robot's own battery telemetry (UDP, see ``battery_receiver``) drives
        it instead. The displayed value still *starts* at the yaml
        ``fixed_batteries`` value — only the drop the robot has reported since
        its first packet is subtracted (and clamped to be monotonic), so the
        curve keeps the configured starting point while following the real
        consumption.
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
from scenarios.mona.letter_show.sim.battery_receiver import BatteryReceiver


# Battery drain (simulation only): 3% per 1000 px moved.
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

        # full_simulation drain bookkeeping.
        self._prev_distance = 0.0

        # puppet-mode bookkeeping: keep the configured start value fixed and
        # subtract the (monotonic) drop the real robot reports via UDP.
        #   battery = sim_initial - max(0, base - received)
        # e.g. sim_initial=64.9, base(first packet)=41%, received=40%
        #      -> drop=1% -> battery=63.9%
        self._sim_initial_battery = self.battery   # frozen start value
        self._real_battery_base = None             # robot's % at first packet
        self._max_real_drop = 0.0                  # largest drop seen so far
        self._battery_receiver = (
            BatteryReceiver.get_instance(config) if self.is_real_robot else None
        )

    def update(self):
        super().update()

        # puppet mode: track the real robot's battery delta.
        if self._battery_receiver is not None and self._is_robot_connected():
            received = self._battery_receiver.get_battery(self.agent_id)
            if received is not None:
                if self._real_battery_base is None:
                    self._real_battery_base = received
                drop = self._real_battery_base - received
                # Monotonic: ignore upward noise spikes in the reported %.
                self._max_real_drop = max(self._max_real_drop, drop)
                self.battery = max(0.0, self._sim_initial_battery - self._max_real_drop)
            return

        # full_simulation: drain with distance moved.
        delta = self.distance_moved - self._prev_distance
        self.battery = max(0.0, self.battery - delta * _BATTERY_DRAIN_PER_PX)
        self._prev_distance = self.distance_moved

    def update_color(self):
        st_id = getattr(self, 'assigned_super_task_id', None)
        self.color = _ST_COLORS.get(st_id, (0, 0, 0))   # unassigned → black
