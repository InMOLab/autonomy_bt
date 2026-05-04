"""BT nodes for the cen_wrapper scenario.

Most action/condition nodes are thin subclasses of platform base nodes. The scenario-specific contributions are:
  - `CentralisationWrapper` — Decorator that turns any dec MRTA plugin into a centralised one by simulating the child for each follower.
  - `AssignCenTask` / `ApplyCenTask` / `TeachBT` — leader↔follower broadcast handshake for the centralised baseline.
"""
import importlib
import time

# Composite/decorator names re-exported here so the BT XML parser (`getattr(bt_module, node_type)`) can resolve them from the scenario's `bt_nodes` namespace.
from core.bt_nodes import (
    BTNodeList, Status, Node,
    Sequence, Fallback, ReactiveSequence, ReactiveFallback, Parallel,
    SyncAction, SyncCondition,
)
from core.bt_nodes_common import AssignTask
from platforms.pygame.bt_nodes_pygame import (
    _IsTaskCompleted,
    _IsArrivedAtTask,
    _MoveToTask,
    _ExecuteTaskWhileFollowing,
    _ExploreArea,
    GatherLocalInfo,
)

from core.utils import config


# ─── BT Node Registration ──────────────────────────────────────────────
CUSTOM_ACTION_NODES = [
    # `AssignTask` and `GatherLocalInfo` come from core / platforms (imported above).
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
leader_communication_radius = config['agents']['types']['Leader'].get(
    'communication_radius', 0,
)  # 0 means "global"; used by IsConnectedWithLeader


def _load_plugin(yaml_key):
    path = config['decision_making'].get(yaml_key)
    if not path:
        return None
    module_path, class_name = path.rsplit('.', 1)
    return getattr(importlib.import_module(module_path), class_name)


# Centralised plugin (sga / cen_grape / hungarian) — consumed by AssignCenTask.
cen_decision_making_class = _load_plugin('cen_plugin')


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
        # Leader-side per-follower proxies. Each proxy carries its own decision_maker
        # (attached lazily by the child AssignTask on first invocation), which holds
        # the per-follower persistent state across BT ticks.
        self.proxies = {}  # follower_id -> FollowerProxy
        # Leader-side cache of each proxy's last-tick `message_to_share`. In real
        # distributed deployment this corresponds to "the last outbox message the
        # leader received from each follower"; here it's the last output of the
        # algorithm running on the proxy. Used to populate the next tick's
        # `proxy.messages_received` so inter-iteration consensus propagates.
        self.proxy_outboxes = {}  # follower_id -> dict (last message_to_share)

    async def run(self, agent, blackboard):
        from scenarios.pygame.features.cen_wrapper.plugins.follower_proxy import FollowerProxy
        import pygame
        agents = getattr(agent, 'agents_nearby', [])
        current_tick_allocations = {}
        # Freeze the outbox cache at tick start so all per-target invocations see the
        # same peer-message view (analog of BTRunner's tick-start snapshot — required
        # to avoid intra-tick cascade where target N+1 reads target N's just-updated outbox).
        outbox_snapshot = dict(self.proxy_outboxes)

        for target_agent in agents:
            if target_agent.type == 'Leader':
                continue
            tid = target_agent.agent_id
            # Lazy create proxy; decision_maker is attached on first AssignTask invocation.
            if tid not in self.proxies:
                self.proxies[tid] = FollowerProxy(tid, target_agent.position)
            proxy = self.proxies[tid]
            # Refresh per-tick fields (in pygame sim: copy from live target; in ROS2 deployment: populate from received topics).
            proxy.position = pygame.Vector2(target_agent.position)
            # Build messages_received from the frozen outbox snapshot (excluding self).
            proxy.messages_received = [
                msg for other_tid, msg in outbox_snapshot.items()
                if other_tid != tid and msg
            ]
            proxy.message_to_share = {}
            # Shallow-copy leader's blackboard so each per-target invocation has its own I/O scope.
            target_blackboard = dict(blackboard)
            await self.children[0].run(proxy, target_blackboard)
            current_tick_allocations[tid] = target_blackboard.get('assigned_task_id')
            # Cache this proxy's outbox — visible only on the *next* tick's iteration.
            self.proxy_outboxes[tid] = dict(proxy.message_to_share) if proxy.message_to_share else {}

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
        """Consensus = current tick's allocations match previous tick's exactly."""
        if not self.previous_allocations:
            return False

        for agent_id in current_allocations:
            if agent_id not in self.previous_allocations:
                return False
            if current_allocations[agent_id] != self.previous_allocations[agent_id]:
                return False

        return True
