"""
BT nodes shared by the MONA scenarios.

All four MONA scenarios (full_simulation, puppet, p2p, offboard) drive the
same agent-level logic — move to assigned task, execute it, explore when
unassigned, idle when nothing to do — and only differ in which external
systems are connected (UDP motion, ESP32 P2P, WhyCon position). The node
behavior is therefore identical across scenarios; the differences are
absorbed by ``MonaAgent.follow()`` / ``MonaAgent.stop()``.

These nodes assume the blackboard key ``assigned_task_id`` (set by the
shared ``AssignTask`` action from ``core.bt_nodes_common``).
"""
import random

# Re-export every control-flow node (Sequence, Fallback, ReactiveSequence,
# ReactiveFallback, Parallel, ...) so that the BT XML loader can resolve
# them via getattr() against the scenario's bt_nodes module.
from core.bt_nodes import *  # noqa: F401,F403
from core.bt_nodes import BTNodeList, Status, SyncAction, SyncCondition

from core.utils import config

# Pull in platform-shared nodes so their names register with BTNodeList
# at import time. The MONA BT XML references these by name.
from platforms.pygame.bt_nodes_pygame import GatherLocalInfo  # noqa: F401
from core.bt_nodes_common import AssignTask  # noqa: F401


# Register custom node names so the BT XML loader can resolve them.
CUSTOM_ACTION_NODES = [
    'MoveToTarget',
    'ExecuteTask',
    'Explore',
    'Idle',
]
CUSTOM_CONDITION_NODES = [
    'IsTaskCompleted',
    'IsArrivedAtTarget',
]
BTNodeList.ACTION_NODES.extend(CUSTOM_ACTION_NODES)
BTNodeList.CONDITION_NODES.extend(CUSTOM_CONDITION_NODES)


# Scenario-level config
target_arrive_threshold = config['tasks']['threshold_done_by_arrival']
task_locations = config['tasks']['locations']
sampling_time = 1.0 / config['simulation']['sampling_freq']
agent_max_random_movement_duration = config.get('agents', {}).get('random_exploration_duration', None)


# ─── Conditions ────────────────────────────────────────────────────────

class IsTaskCompleted(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id')
        if assigned_task_id is None:
            return Status.RUNNING

        task = agent.tasks_info[assigned_task_id]
        if task.completed:
            blackboard['assigned_task_id'] = None
            return Status.SUCCESS
        return Status.FAILURE


class IsArrivedAtTarget(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id')
        if assigned_task_id is None:
            raise ValueError(f"[{self.name}] Error: No assigned_task_id found in the blackboard!")

        task = agent.tasks_info[assigned_task_id]
        distance = (task.position - agent.position).length()
        if distance < task.radius + target_arrive_threshold:
            return Status.SUCCESS
        return Status.FAILURE


# ─── Actions ───────────────────────────────────────────────────────────

class MoveToTarget(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id')
        if assigned_task_id is None:
            raise ValueError(f"[{self.name}] Error: No assigned_task_id found in the blackboard!")

        agent.follow(agent.tasks_info[assigned_task_id].position)
        return Status.RUNNING


class ExecuteTask(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id')
        if assigned_task_id is None:
            raise ValueError(f"[{self.name}] Error: No assigned_task_id found in the blackboard!")

        task = agent.tasks_info[assigned_task_id]
        task.reduce_amount(agent.work_rate)
        agent.update_task_amount_done(agent.work_rate)
        agent.follow(task.position)
        return Status.RUNNING


class Explore(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)
        self.random_move_time = float('inf')
        self.random_waypoint = (0, 0)

    def _update(self, agent, blackboard):
        if self.random_move_time > agent_max_random_movement_duration:
            self.random_waypoint = (
                random.randint(task_locations['x_min'], task_locations['x_max']),
                random.randint(task_locations['y_min'], task_locations['y_max']),
            )
            self.random_move_time = 0

        self.random_move_time += sampling_time
        agent.follow(self.random_waypoint)
        return Status.RUNNING

    def halt(self):
        self.random_move_time = float('inf')


class Idle(SyncAction):
    """Stop the agent. Routes through MonaAgent.stop(), so it sends STOP UDP
    when connected to a real robot and freezes velocity/rotation in simulation."""
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        agent.stop()
        return Status.RUNNING
