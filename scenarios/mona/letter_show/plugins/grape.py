"""
GRAPE subclass for the letter_show scenario.

Two extensions over the global GRAPE:

1. ``reset()`` — explicit state-init for the next "generation".
   Called by ``AssignSuperTask`` whenever the task set is replaced
   (i.e. the next letter is being formed). The base GRAPE has no
   reset hook because non-letter scenarios don't replace tasks
   in-place.

2. battery-aware ``compute_utility()`` — utility of a task to an
   agent depends not just on distance/amount/coalition size but
   also on the agent's battery relative to the swarm.

   - Agents with **higher battery** prefer tasks more strongly
     (they should be the ones doing work).
   - Agents with **lower battery** disengage.
   - When the swarm's median battery is low, an extra
     ``urgency_factor`` raises everyone's utility (we still need
     to finish the letter even if everyone is tired).

   The whole formula degrades gracefully when ``agent.battery`` is
   missing (treated as 100 %), so the subclass remains compatible
   with non-battery scenarios — though letter_show is the only
   intended caller.
"""
from plugins.mrta.grape.grape import GRAPE as _BaseGRAPE
from core.utils import config


COST_WEIGHT_FACTOR = config['decision_making']['GRAPE']['cost_weight_factor']
SOCIAL_INHIBITION_FACTOR = config['decision_making']['GRAPE']['social_inhibition_factor']


class GRAPE(_BaseGRAPE):
    def reset(self):
        """Re-initialise GRAPE state for a new generation (e.g. next letter)."""
        self.satisfied = False
        self.evolution_number = 0
        self.time_stamp = 0
        self.partition = {}
        self.assigned_task = None
        self.current_utilities = {}
        self.agent.message_to_share = {
            'agent_id': self.agent.agent_id,
            'partition': self.partition,
            'evolution_number': self.evolution_number,
            'time_stamp': self.time_stamp,
        }

    def compute_utility(self, task):  # Individual Utility Function
        if task is None:
            return float('-inf')

        # Ensure partition key exists (matches the base class — important
        # for dynamic task generation when new task ids appear).
        self.partition.setdefault(task.task_id, set())
        num_collaborator = len(self.partition[task.task_id])
        if self.agent.agent_id not in self.partition[task.task_id]:
            num_collaborator += 1

        distance = (self.agent.position - task.position).length()

        # Battery-aware factors. battery may be None (not yet received from
        # a real robot) → treat as 100 % so ratios stay neutral.
        my_battery = getattr(self.agent, 'battery', None) or 100.0
        all_agents = getattr(self.agent, 'agents_info', None) or [self.agent]
        known_batteries = [
            b for b in (getattr(a, 'battery', None) for a in all_agents) if b is not None
        ]
        max_battery = max(known_batteries) if known_batteries else 100.0
        min_battery = min(known_batteries) if known_batteries else 0.0
        sorted_batteries = sorted(known_batteries)
        n = len(sorted_batteries)
        if n == 0:
            median_battery = 0.0
        elif n % 2 == 1:
            median_battery = sorted_batteries[n // 2]
        else:
            median_battery = (sorted_batteries[n // 2 - 1] + sorted_batteries[n // 2]) / 2.0

        battery_range = max_battery - min_battery
        battery_ratio = ((my_battery - min_battery) / battery_range) if battery_range > 0.0 else 1.0
        urgency_factor = (max_battery / median_battery) if median_battery > 0.0 else 1.0

        return (
            urgency_factor * battery_ratio * task.amount / num_collaborator
            - COST_WEIGHT_FACTOR * distance * (num_collaborator ** SOCIAL_INHIBITION_FACTOR)
        )
