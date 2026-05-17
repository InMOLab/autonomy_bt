"""BT nodes for the cen_wrapper scenario."""

# Composite/decorator names re-exported here so the BT XML parser (`getattr(bt_module, node_type)`) can resolve them from the scenario's `bt_nodes` namespace.
from core.bt_nodes import (
    BTNodeList, Status,
    Sequence, Fallback, ReactiveSequence, ReactiveFallback, Parallel,
    SyncAction,
)
from core.bt_nodes_common import AssignTask
from platforms.pygame.bt_nodes_pygame import (
    _IsTaskCompleted,
    _IsArrivedAtTask,
    _MoveToTask,
    _ExecuteTaskWhileFollowing,
    GatherLocalInfo,
)

# Platform-agnostic cen_wrapper nodes — re-exported so BT XML parser can resolve them via the scenario's bt_nodes namespace.
from plugins.cen_wrapper.bt_nodes import (
    CentralisationWrapper,
    AssignCenTask,
    TeachBT,
    ApplyCenTask,
    ForwardCenAllocation,
    RelayDecMessages,
    UnpackRelayedMessages,
    FilterClaimedTasks,
    IsConnectedWithLeader,
    IsTaskAssigned,
    IsAllocationConverged,
)

from core.utils import config


# ─── BT Node Registration ──────────────────────────────────────────────
CUSTOM_ACTION_NODES = [
    # `AssignTask` and `GatherLocalInfo` come from core / platforms (imported above).
    'AssignCenTask',          # cen-side: leader runs centralised plugin (sga/cen_grape/hungarian)
    'ApplyCenTask',           # follower: applies leader's broadcast result
    'RelayDecMessages',       # mesh-relay [cen]: stage dec-peer msgs into outgoing relay payload
    'UnpackRelayedMessages',  # mesh-relay [dec]: flatten incoming relay payload for AssignTask
    'FilterClaimedTasks',     # mesh-relay [dec]: drop cen-claimed tasks/agents from dec view
    'ForwardCenAllocation',   # mesh-relay [dec]: forward leader's task_allocations into mesh
    'MoveToTarget',
    'ExecuteTask',
    'TeachBT',
    'Halt',
]

CUSTOM_CONDITION_NODES = [
    'IsTaskCompleted',
    'IsArrivedAtTarget',
    'IsTaskAssigned',
    'IsConnectedWithLeader',
    'IsAllocationConverged',
]

CUSTOM_DECORATOR_NODES = [
    'CentralisationWrapper',
]

BTNodeList.ACTION_NODES.extend(CUSTOM_ACTION_NODES)
BTNodeList.CONDITION_NODES.extend(CUSTOM_CONDITION_NODES)
BTNodeList.DECORATOR_NODES.extend(CUSTOM_DECORATOR_NODES)


# ─── Scenario-level config ─────────────────────────────────────────────
target_arrive_threshold = config.get('tasks', {}).get('threshold_done_by_arrival')


# =============================================================================
# Pygame-specific condition/action nodes
# =============================================================================

class IsTaskCompleted(_IsTaskCompleted):
    def _update(self, agent, blackboard):
        result = super()._update(agent, blackboard, task_id_key='assigned_task_id')
        if result is Status.SUCCESS:
            blackboard['assigned_task_id'] = None
        return result


class IsArrivedAtTarget(_IsArrivedAtTask):
    def _update(self, agent, blackboard):
        return super()._update(
            agent, blackboard,
            task_id_key='assigned_task_id',
            arrive_threshold=target_arrive_threshold,
        )


class MoveToTarget(_MoveToTask):
    def _update(self, agent, blackboard):
        return super()._update(agent, blackboard, task_id_key='assigned_task_id')


class ExecuteTask(_ExecuteTaskWhileFollowing):
    def _update(self, agent, blackboard):
        return super()._update(agent, blackboard, task_id_key='assigned_task_id')


class Halt(SyncAction):
    """Stop all movement of the agent."""

    def __init__(self, name, agent):
        super().__init__(name, self._halt)

    def _halt(self, agent, blackboard):
        agent.reset_movement()
        return Status.RUNNING
