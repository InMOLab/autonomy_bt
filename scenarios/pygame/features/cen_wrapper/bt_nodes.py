"""BT nodes for cen_wrapper. Ported from
`space-simulator-cendec/scenarios/features/cenwrapper/bt_nodes.py`.

The student's code is preserved as-is — only the import chain is rewired
to autonomy_bt's 4-layer structure:

  modules.base_bt_nodes  →  core.bt_nodes (control flow + base classes)
                          + platforms.pygame.bt_nodes_pygame (private base
                            nodes like _IsTaskCompleted, _MoveToTask,
                            _ExecuteTaskWhileFollowing, _ExploreArea,
                            _IsArrivedAtTask, plus GatherLocalInfo)
                          + core.bt_nodes_common (AssignTask)
  modules.utils          →  core.utils

The `time.time()` use in `CentralisationWrapper.run` and
`AssignCenTask._assign` is intentionally kept (per `TODO.md` item 1-6 —
to be unified with the broader timing-model cleanup later).
"""
import importlib
import time

# Control-flow + base classes
from core.bt_nodes import (
    BTNodeList, Status, Node,
    Sequence, Fallback, ReactiveSequence, ReactiveFallback, Parallel,
    SyncAction, SyncCondition,
)
# NOTE: We do NOT import the global `AssignTask` from `core.bt_nodes_common`.
# `CentralisationWrapper` invokes its child (`AssignTask`) per follower
# in turn — each call needs the decision-maker tied to the *target*
# agent, not to a fixed leader-side instance. The student's cendec uses
# a per-agent `agent.decision_maker` pattern; we mirror it in the
# `AssignTask` class defined further down.
# Pygame-platform private base nodes (we override GatherLocalInfo locally
# below to mirror cendec's accumulate-then-pick-latest message pattern;
# autonomy_bt's default GatherLocalInfo resets messages_received per tick,
# which breaks the leader→follower broadcast handshake used here).
from platforms.pygame.bt_nodes_pygame import (
    _IsTaskCompleted,
    _IsArrivedAtTask,
    _MoveToTask,
    _ExecuteTaskWhileFollowing,
    _ExploreArea,
)

from core.utils import config


# ─── BT Node Registration ──────────────────────────────────────────────
CUSTOM_ACTION_NODES = [
    'GatherLocalInfo',
    'AssignTask',         # dec-side: per-target-agent decision_maker (used inside CentralisationWrapper)
    'AssignCenTask',      # cen-side: leader runs centralised plugin (sga/cen_grape/hungarian)
    'ApplyCenTask',       # follower: applies leader's broadcast result
    'MoveToTarget',
    'ExecuteTask',
    'Explore',
    'TeachBT',
    'Halt',
]

CUSTOM_CONDITION_NODES = [
    'IsTaskCompleted',
    'IsArrivedAtTarget',
    'IsTaskAssigned',
    'IsConnectedWithLeader',
]

CUSTOM_DECORATOR_NODES = [
    'CentralisationWrapper',
]

BTNodeList.ACTION_NODES.extend(CUSTOM_ACTION_NODES)
BTNodeList.CONDITION_NODES.extend(CUSTOM_CONDITION_NODES)
BTNodeList.DECORATOR_NODES.extend(CUSTOM_DECORATOR_NODES)


# ─── Scenario-level config ─────────────────────────────────────────────
target_arrive_threshold = config['tasks']['threshold_done_by_arrival']
task_locations = config['tasks']['locations']
sampling_time = 1.0 / config['simulation']['sampling_freq']
agent_max_random_movement_duration = config.get('agents', {}).get(
    'random_exploration_duration', 1000,
) or 1000
# dec-side plugin (cbba / grape / dec_hungarian) — used by AssignTask
_dec_plugin_path = config['decision_making'].get('plugin')
decision_making_class = None
if _dec_plugin_path:
    _module_path, _class_name = _dec_plugin_path.rsplit('.', 1)
    decision_making_class = getattr(importlib.import_module(_module_path), _class_name)

# cen-side plugin (sga / cen_grape / hungarian) — used by AssignCenTask
_cen_plugin_path = config['decision_making'].get('cen_plugin')
cen_decision_making_class = None
if _cen_plugin_path:
    _module_path, _class_name = _cen_plugin_path.rsplit('.', 1)
    cen_decision_making_class = getattr(importlib.import_module(_module_path), _class_name)

leader_communication_radius = config['agents']['types']['Leader'].get(
    'communication_radius', 0,
)  # 0 means "global"; used by IsConnectedWithLeader


# =============================================================================
# Condition Nodes
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


class IsTaskAssigned(SyncCondition):
    """Check whether the agent currently has a task assigned."""

    def __init__(self, name, agent):
        super().__init__(name, self._is_assigned)

    def _is_assigned(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id', None)
        if assigned_task_id is not None:
            return Status.SUCCESS
        else:
            return Status.FAILURE


class IsConnectedWithLeader(SyncCondition):
    """Check whether the agent can reach the Leader (distance-based)."""

    def __init__(self, name, agent):
        super().__init__(name, self._is_connected)
        self.leader_agent = agent.agents_info[-1]

    def _is_connected(self, agent, blackboard):
        if self.leader_agent is not None and self.leader_agent.type == 'Leader':
            distance = agent.position.distance_to(self.leader_agent.position)
        else:
            agents_info = getattr(agent, 'agents_info', {})
            self.leader_agent = None
            for agent_info in agents_info:
                if agent_info.type == 'Leader':
                    self.leader_agent = agent_info
                    distance = agent.position.distance_to(self.leader_agent.position)
                    break

        if self.leader_agent is None:
            return Status.FAILURE

        if distance < leader_communication_radius:
            return Status.SUCCESS
        else:
            return Status.FAILURE


# =============================================================================
# Action Nodes
# =============================================================================

class MoveToTarget(_MoveToTask):
    def _update(self, agent, blackboard):
        return super()._update(agent, blackboard, task_id_key='assigned_task_id')


class ExecuteTask(_ExecuteTaskWhileFollowing):
    def _update(self, agent, blackboard):
        return super()._update(agent, blackboard, task_id_key='assigned_task_id')


class Explore(_ExploreArea):
    def _update(self, agent, blackboard):
        return super()._update(
            agent, blackboard,
            agent_max_random_movement_duration=agent_max_random_movement_duration,
            exploration_area=task_locations,
            sampling_time=sampling_time,
        )


class TeachBT(SyncAction):
    """Broadcast the central MRTA allocation result to followers."""

    def __init__(self, name, agent):
        super().__init__(name, self._teach)

    def _teach(self, agent, blackboard):
        task_allocations = blackboard.get('task_allocations', {})

        agent.message_to_share['task_allocations'] = task_allocations
        agent.broadcast_message(to_all=False)

        return Status.SUCCESS


class ApplyCenTask(SyncAction):
    """[Follower] Receives the MRTA allocation broadcast by the leader and
    applies it as its own assigned task. (Companion to leader-side
    `AssignCenTask` — 'Assign' on the leader runs the algorithm, 'Apply'
    on the follower adopts the result.)
    """

    def __init__(self, name, agent):
        super().__init__(name, self._apply)

    def _apply(self, agent, blackboard):
        latest_task_allocations = {}
        latest_timestamp = 0

        for msg in agent.messages_received:
            _task_allocations = msg.get('task_allocations', {})
            if _task_allocations and isinstance(_task_allocations, dict):
                msg_timestamp = _task_allocations.get('timestamp', 0)
                if msg_timestamp > latest_timestamp:
                    latest_timestamp = msg_timestamp
                    latest_task_allocations = _task_allocations

        blackboard['assigned_task_id'] = latest_task_allocations.get(agent.agent_id, None)
        agent.assigned_task_id = blackboard['assigned_task_id']

        return Status.SUCCESS


class AssignCenTask(SyncAction):
    """[Leader] Runs a centralised algorithm (sga / cen_grape / hungarian)
    that assigns tasks to all followers in a single pass. The plugin
    class is dispatched from yaml's `decision_making.cen_plugin` — same
    pattern as `AssignTask` dispatching the dec-side plugin via
    `decision_making.plugin`.
    """

    def __init__(self, name, agent):
        super().__init__(name, self._assign)
        if cen_decision_making_class is None:
            raise RuntimeError(
                "[AssignCenTask] yaml is missing `decision_making.cen_plugin`."
            )
        self.cen_decision_maker = cen_decision_making_class(agent)

    def _assign(self, agent, blackboard):
        self.cen_decision_maker.decide(blackboard)
        # The plugin writes blackboard['task_allocations']; TeachBT then
        # broadcasts it to followers.
        return Status.SUCCESS


class Halt(SyncAction):
    """Stop all movement of the agent."""

    def __init__(self, name, agent):
        super().__init__(name, self._halt)

    def _halt(self, agent, blackboard):
        agent.reset_movement()
        return Status.RUNNING


class AssignTask(SyncAction):
    """cendec's `AssignTask` pattern — per-agent `decision_maker`
    instance.

    When `CentralisationWrapper` invokes its child on each follower in
    turn, each follower lazy-instantiates its own `decision_maker` and
    reuses it on subsequent calls. The difference from autonomy_bt's
    global `core.bt_nodes_common.AssignTask` is the *instance owner*:
    autonomy_bt binds it to the BT node, while cendec binds it to the
    agent.
    """

    def __init__(self, name, agent):
        super().__init__(name, self._decide)

    def _decide(self, agent, blackboard):
        if not hasattr(agent, 'decision_maker') or agent.decision_maker is None:
            agent.decision_maker = decision_making_class(agent, blackboard)
        assigned_task_id = agent.decision_maker.decide(blackboard)
        agent.assigned_task_id = assigned_task_id
        blackboard['assigned_task_id'] = assigned_task_id
        if assigned_task_id is None:
            return Status.FAILURE
        else:
            return Status.SUCCESS


class GatherLocalInfo(SyncAction):
    """Mirrors cendec's GatherLocalInfo — appends each peer's
    `message_to_share` to `messages_received` *without resetting* the
    queue per tick.

    autonomy_bt's default `local_message_receive` resets the queue at
    the start of every tick (a fix for a mona-scenario regression).
    Using that default here would break the leader → follower broadcast
    handshake, since the follower's `ApplyCenTask` may not run on the
    same tick the message arrives. We override locally to preserve
    cendec's accumulate-then-pick-latest semantics.

    `ApplyCenTask` picks the message with the largest timestamp out of
    the accumulated queue, so unbounded accumulation is safe. (Memory
    grows with simulation length, but the experiment horizon is short
    enough to ignore.)
    """

    def __init__(self, name, agent):
        super().__init__(name, self._local_sensing)

    def _local_sensing(self, agent, blackboard):
        # The student's dec plugins (CBBA / GRAPE / dec_hungarian) all
        # expect `local_tasks_info` as a *list[Task]*, so emit a list
        # directly. The cen plugins (CenGRAPE / Hungarian / SGA) have an
        # `isinstance(..., dict)` guard at decide() entry, so a list
        # passes through unchanged.
        blackboard['local_tasks_info'] = agent.get_tasks_nearby(with_completed_task=False)

        # Same as cendec's BaseAgent.local_message_receive — accumulate
        # without resetting.
        agent.agents_nearby = agent.get_agents_nearby()
        for other_agent in agent.agents_nearby:
            if other_agent.agent_id != agent.agent_id:
                agent.receive_message(other_agent.message_to_share)

        blackboard['local_agents_info'] = agent.agents_nearby
        blackboard['messages_received'] = agent.messages_received
        return Status.SUCCESS


# =============================================================================
# Decorator Node — the paper's central contribution
# =============================================================================

class CentralisationWrapper(Node):
    """Decorator that centralises an MRTA allocation algorithm.

    Placed inside the leader's BT. Every tick it iterates over each
    connected agent and *simulates* the child (a dec-side `AssignTask`)
    on behalf of that target agent — the leader's aggregated information
    is fed into the per-call blackboard. Once consensus is reached
    (current allocation equals the previous tick's), the leader
    broadcasts the result and returns SUCCESS.
    """

    def __init__(self, name, child):
        super().__init__(name)
        self.type = "CentralisationWrapper"
        self.children = [child]
        self.previous_allocations = {}

    async def run(self, agent, blackboard):
        agents = getattr(agent, 'agents_nearby', [])

        current_tick_allocations = {}
        _blackboard = {}
        _blackboard['local_tasks_info'] = agent.blackboard.get('local_tasks_info', {})
        _blackboard['local_agents_info'] = agent.blackboard.get('local_agents_info', {})
        _blackboard['messages_received'] = agent.blackboard.get('messages_received', [])

        for target_agent in agents:
            if target_agent.type == 'Leader':
                continue

            child_status = await self.children[0].run(target_agent, _blackboard)

            assigned_task_id = _blackboard.get('assigned_task_id', None)
            if assigned_task_id is not None:
                current_tick_allocations[target_agent.agent_id] = assigned_task_id
            else:
                current_tick_allocations[target_agent.agent_id] = None

        agent.reset_messages_received()
        consensus_reached = self._is_consensus_reached(current_tick_allocations)

        if consensus_reached:
            blackboard['task_allocations'] = {k: v for k, v in current_tick_allocations.items()}
            blackboard['task_allocations']['timestamp'] = time.time()
            blackboard['consensus_reached'] = True

            return Status.SUCCESS
        else:
            self.previous_allocations = current_tick_allocations.copy()
            blackboard['consensus_reached'] = False

            return Status.RUNNING

    def _is_consensus_reached(self, current_allocations):
        """Compare current vs previous tick's allocations to decide whether
        consensus has been reached."""
        if not self.previous_allocations:
            return False

        for agent_id in current_allocations:
            if agent_id not in self.previous_allocations:
                return False
            if current_allocations[agent_id] != self.previous_allocations[agent_id]:
                return False

        return True
