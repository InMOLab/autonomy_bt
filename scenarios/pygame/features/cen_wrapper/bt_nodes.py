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
    EmitProxyMessage,
    AdoptProxyState,
    KeepPlanWhenIsolated,
    CommitToPlan,
    ResetProtocolState,
    RelayMessages,
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
    'AssignCenTask',          # Leader-as-solver: leader runs the dedicated centralised solver (sga/cen_grape/hungarian)
    'ApplyCenTask',           # connected follower: applies the leader's plan
    'EmitProxyMessage',       # Leader-as-proxy, connected follower: broadcasts its proxy's protocol message
    'AdoptProxyState',        # Leader-as-proxy, follower leaving the cluster: hands its proxy's last message to its plugin (with EmitProxyMessage self_apply="1")
    'KeepPlanWhenIsolated',   # iso: isolated follower keeps its own last decision
    'CommitToPlan',           # Leader-as-solver commit: follower that left keeps the plan's bundle until it is gone (covers iso)
    'ResetProtocolState',     # Leader-as-solver reset: the follower's own protocol state is cleared on leaving
    'RelayMessages',          # relays heard follower messages (scope outside|all, nested)
    'UnpackRelayedMessages',  # flattens relayed messages into the inbox for AssignTask
    'FilterClaimedTasks',     # Leader-as-solver, disconnected follower: drops plan-claimed tasks/robots
    'ForwardCenAllocation',   # Leader-as-solver: passes the leader's plan one hop further
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
    'CentralisationWrapper',  # Leader-as-proxy: runs the decentralised plugin on proxies of the connected followers
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
