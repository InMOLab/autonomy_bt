"""Centralized GRAPE for cen_wrapper. Ported from
`space-simulator-cendec/scenarios/features/cenwrapper/cen_grape.py`.

Used as a *comparison baseline* against `CentralisationWrapper +
AssignTask(GRAPE)`. Loaded by the `AssignCenTask` BT node via
`decision_making.cen_plugin` in yaml — same plugin pattern as the
dec-side plugins.

NOTE: distance-based partition init / re-init (yaml options
`initialize_partition` and `reinitialize_partition_on_completion`) are
*intentionally* not honoured here, mirroring the shared
`plugins/mrta/grape/grape.GRAPE` which also ignores those options. This
keeps the centralised baseline algorithmically aligned with the dec
plugin so the 3-way equivalence experiment is apples-to-apples.
"""
import time

from core.utils import config


COST_WEIGHT_FACTOR = config['decision_making']['GRAPE']['cost_weight_factor']
SOCIAL_INHIBITION_FACTOR = config['decision_making']['GRAPE']['social_inhibition_factor']


class CenGRAPE:
    """Centralised GRAPE — runs on the leader, computes a partition for all
    followers in one centralised pass, writes `task_allocations` to the
    blackboard.

    Mirrors shared GRAPE's per-tick semantics so the 3-way comparison
    (pure-dec / wrapper / cen_grape) reaches the same nash equilibrium under
    a fully-connected network with deterministic mutex (`time_stamp = agent_id`):
      1. Snapshot partition at start of each pass — no within-pass cascade.
      2. Each agent independently proposes its max-utility switch.
      3. Mutex: only the highest-agent_id switcher commits this pass.
      4. Repeat until no agent wants to switch.
    """

    def __init__(self, agent):
        self.agent = agent  # leader
        self.partition = {}
        self.agents_state = {}

    def decide(self, blackboard):
        _local_tasks_info = list(blackboard['local_tasks_info'].values())
        _local_agents_info = blackboard['local_agents_info']

        self._init_partition_structure(_local_tasks_info)
        self._init_agents_state(_local_agents_info)

        # Give up the decision-making process if there is no task nearby
        if len(_local_tasks_info) == 0:
            return None

        self._compute_cen_grape(_local_agents_info, _local_tasks_info)

        task_allocations = {}
        for other_agent in _local_agents_info:
            agent_id = other_agent.agent_id
            allocation = self.agents_state.get(agent_id, {}).get('allocation', None)
            task_allocations[agent_id] = [allocation] if allocation is not None else []
            if allocation is not None:
                assigned_task = next((t for t in _local_tasks_info if t.task_id == allocation), None)
                other_agent.set_planned_tasks([assigned_task] if assigned_task else [])
            else:
                other_agent.set_planned_tasks([])

        blackboard["central_plan"] = {
            'task_allocations': task_allocations,
            'created_at': time.time(),
        }

    def _init_partition_structure(self, tasks_info):
        for task in tasks_info:
            if task.task_id not in self.partition:
                self.partition[task.task_id] = set()

    def _init_agents_state(self, _local_agents_info):
        for other_agent in _local_agents_info:
            agent_id = other_agent.agent_id
            if agent_id not in self.agents_state:
                self.agents_state[agent_id] = {'allocation': None}

    def _compute_cen_grape(self, _local_agents_info, _local_tasks_info):
        consensus_step = 0

        while True:
            # Phase 1: snapshot partition — every agent in this pass evaluates
            # against the same view (no cascade from earlier agents' switches).
            partition_snapshot = {k: set(v) for k, v in self.partition.items()}

            # Phase 2: each agent independently proposes a max-utility switch.
            proposals = []  # [(agent_id, current_task_id, max_task_id), ...]
            for other_agent in _local_agents_info:
                agent_id = other_agent.agent_id
                agent_state = self.agents_state.get(agent_id)
                if agent_state is None:
                    continue
                current_task_id = agent_state['allocation']
                max_task_id, _ = self.find_max_utility_task(
                    other_agent, _local_tasks_info, partition=partition_snapshot,
                )
                if current_task_id != max_task_id:
                    proposals.append((agent_id, current_task_id, max_task_id))

            if not proposals:
                break  # all agents satisfied with current allocation

            # Phase 3: mutex — only the highest-agent_id switcher commits.
            # Analog of shared GRAPE's d-mutex under `time_stamp = agent_id`:
            # at equal evolution_number, the highest agent_id wins next tick.
            winner_id, winner_current, winner_max = max(proposals, key=lambda p: p[0])
            self.discard_agent_from_coalition(winner_id, winner_current)
            self.partition.setdefault(winner_max, set())
            self.partition[winner_max].add(winner_id)
            self.agents_state[winner_id]['allocation'] = winner_max

            consensus_step += 1

        return consensus_step

    def find_max_utility_task(self, other_agent, tasks_info, partition=None):
        _current_utilities = {
            task.task_id: self.compute_utility(other_agent, task, partition)
            for task in tasks_info
        }

        _max_task_id = max(_current_utilities, key=_current_utilities.get)
        _max_utility = _current_utilities[_max_task_id]

        return _max_task_id, _max_utility

    def compute_utility(self, other_agent, task, partition=None):
        if task is None:
            return float('-inf')

        if partition is None:
            partition = self.partition
        partition.setdefault(task.task_id, set())
        num_collaborator = len(partition[task.task_id])
        if other_agent.agent_id not in partition[task.task_id]:
            num_collaborator += 1

        distance = (other_agent.position - task.position).length()
        utility = task.amount / (num_collaborator) - COST_WEIGHT_FACTOR * distance * (num_collaborator ** SOCIAL_INHIBITION_FACTOR)
        return utility

    def discard_agent_from_coalition(self, agent_id, task_id):
        if task_id is not None and task_id in self.partition:
            self.partition[task_id].discard(agent_id)
