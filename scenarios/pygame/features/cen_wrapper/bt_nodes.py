"""BT nodes for the cen_wrapper scenario."""
import importlib
import time

import pygame

# Composite/decorator names re-exported here so the BT XML parser (`getattr(bt_module, node_type)`) can resolve them from the scenario's `bt_nodes` namespace.
from core.bt_nodes import (
    BTNodeList, Node, Status,
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

from core.utils import config, extract_agent_id, extract_task_id


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
    'Explore',
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
target_arrive_threshold = config['tasks']['threshold_done_by_arrival']
task_locations = config['tasks']['locations']
sampling_time = 1.0 / config['simulation']['sampling_freq']
agent_max_random_movement_duration = config.get('agents', {}).get(
    'random_exploration_duration', 1000,
) or 1000


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
    """SUCCESS iff `blackboard['assigned_task_id']` is set."""

    def __init__(self, name, agent):
        super().__init__(name, self._is_assigned)

    def _is_assigned(self, agent, blackboard):
        assigned_task_id = blackboard.get('assigned_task_id', None)
        if assigned_task_id is not None:
            return Status.SUCCESS
        else:
            return Status.FAILURE


class IsConnectedWithLeader(SyncCondition):
    """SUCCESS iff a Leader-marked broadcast is in the inbox this tick."""

    def __init__(self, name, agent):
        super().__init__(name, self._is_connected)

    def _is_connected(self, agent, blackboard):
        for message in agent.messages_received:
            if message.get('type') == 'Leader':
                return Status.SUCCESS
        return Status.FAILURE


class IsAllocationConverged(SyncCondition):
    """Gate that opens once the team's allocation snapshot is stable for two ticks."""

    def __init__(self, name, agent):
        super().__init__(name, self._check)
        self.previous_snapshot = None

    def _check(self, agent, blackboard):
        def as_bundle(outbox):
            bundle = outbox.get('planned_tasks_id')
            primary = list(bundle) if bundle is not None else [outbox.get('assigned_task_id')]
            # GRAPE-only: outbox is rebound only on Phase 2 improvement, so
            # `updated_at` is a reliable per-agent iteration counter — append it
            # to make snapshot equality detect "no improvement for 2 ticks".
            # CBBA / Hungarian rebind every tick (consensus/perception always
            # broadcast), so `updated_at` is useless for them; their task_id
            # alone is enough.
            if 'evolution_number' in outbox:
                primary.append(outbox.get('updated_at'))
            return primary

        leader_team = None
        peers_seen = {agent.agent_id}
        current_snapshot = {agent.agent_id: as_bundle(agent.message_to_share)}

        for message in agent.messages_received:
            # Centralised Plan
            plan = message.get('central_plan')
            if isinstance(plan, dict):
                allocations = plan.get('task_allocations', {})
                for follower_id, bundle in allocations.items():
                    current_snapshot[follower_id] = list(bundle) if bundle else []
                leader_team = set(allocations.keys())
                continue
            # Decentralised Plan
            peer_id = message.get('agent_id')
            if peer_id is None or message.get('type') == 'Leader':
                continue
            peers_seen.add(peer_id)
            current_snapshot[peer_id] = as_bundle(message)

        # Partial-radius: leader broadcast covers only the cen-cluster, dec peers fill in via direct messages — union to capture the whole team.
        expected = peers_seen | (leader_team or set())

        if not expected.issubset(current_snapshot):
            return Status.FAILURE
        if self.previous_snapshot == current_snapshot:
            return Status.SUCCESS
        self.previous_snapshot = current_snapshot
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
        # Stamp type marker at construction so the BTRunner's tick-0 snapshot already advertises the leader. Followers' message-based `IsConnectedWithLeader` then succeeds from tick 0.
        agent.message_to_share['type'] = agent.type
        agent.message_to_share['updated_at'] = time.time()

    def _teach(self, agent, blackboard):
        agent.message_to_share['central_plan'] = blackboard.get('central_plan', {})
        agent.message_to_share['updated_at'] = time.time()
        agent.broadcast_message(to_all=False)
        return Status.SUCCESS


class AssignCenTask(SyncAction):
    """[Leader] Run the centralised allocation plugin (yaml `decision_making.cen_plugin`)."""

    def __init__(self, name, agent):
        super().__init__(name, self._assign)
        if cen_decision_making_class is None:
            raise RuntimeError(
                "[AssignCenTask] yaml is missing `decision_making.cen_plugin`."
            )
        self.cen_decision_maker = cen_decision_making_class(agent)

    def _assign(self, agent, blackboard):
        self.cen_decision_maker.decide(blackboard)
        # The plugin writes blackboard['central_plan']; TeachBT then broadcasts it to followers.
        return Status.SUCCESS


class Halt(SyncAction):
    """Stop all movement of the agent."""

    def __init__(self, name, agent):
        super().__init__(name, self._halt)

    def _halt(self, agent, blackboard):
        agent.reset_movement()
        return Status.RUNNING


# =============================================================================
# Mesh-relay shared helpers
# =============================================================================

def _get_latest_central_plan(agent):
    """Pick the freshest `central_plan` ({'task_allocations', 'created_at'}) from the inbox (or None)."""
    latest_plan, latest_created_at = None, -1
    for message in agent.messages_received:
        plan = message.get('central_plan')
        if isinstance(plan, dict):
            created_at = plan.get('created_at', 0)
            if created_at > latest_created_at:
                latest_created_at = created_at
                latest_plan = plan
    return latest_plan


def _strip_nested_relay(msg):
    """Shallow copy of `msg` without `relayed_messages` (cap relay at 1 hop)."""
    return {k: v for k, v in msg.items() if k != 'relayed_messages'}


def _freshness_score(msg):
    """Plugin-agnostic message freshness — wall-clock `updated_at` stamp."""
    return msg.get('updated_at', 0) or 0


# =============================================================================
# Cen branch (in-range follower) — order matches `bt_follower_static_full.xml`
# =============================================================================

class ApplyCenTask(SyncAction):
    """Adopt this follower's primary from the leader's broadcast."""

    def __init__(self, name, agent):
        super().__init__(name, self._apply)

    def _apply(self, agent, blackboard):
        latest_plan = _get_latest_central_plan(agent)
        # Cache for downstream `ForwardCenAllocation` (symmetric with FilterClaimedTasks on the dec branch).
        blackboard['_latest_central_plan'] = latest_plan
        bundle = (latest_plan or {}).get('task_allocations', {}).get(agent.agent_id, [])
        primary_task_id = bundle[0] if bundle else None
        blackboard['assigned_task_id'] = primary_task_id
        agent.assigned_task_id = primary_task_id
        return Status.SUCCESS


class ForwardCenAllocation(SyncAction):
    """Re-publish the leader's allocation so out-of-range peers can learn it."""

    def __init__(self, name, agent):
        super().__init__(name, self._forward)

    def _forward(self, agent, blackboard):
        latest_plan = blackboard.get('_latest_central_plan')
        if latest_plan is None:
            return Status.SUCCESS

        agent.message_to_share['central_plan'] = latest_plan
        agent.message_to_share['updated_at'] = time.time()
        return Status.SUCCESS


class RelayDecMessages(SyncAction):
    """Bundle 1-hop dec-peer messages into our outbox so cen-followers bridge the mesh."""

    def __init__(self, name, agent):
        super().__init__(name, self._stage)

    def _stage(self, agent, blackboard):
        self_agent_id = agent.agent_id
        relayed_by_sender_id = {}     # peer agent_id → flattened message dict
        score_by_sender_id = {}       # peer agent_id → freshness score
        direct_sender_ids = set()     # peers reached 1-hop direct (always trump nested)

        # Pass 1: direct copies — always 1-hop, trump any prior/later nested.
        for message in agent.messages_received:
            sender_id = message.get('agent_id')
            if sender_id is None or sender_id == self_agent_id:
                continue
            if message.get('type') == 'Leader':
                continue
            relayed_by_sender_id[sender_id] = _strip_nested_relay(message)
            score_by_sender_id[sender_id] = _freshness_score(message)
            direct_sender_ids.add(sender_id)

        # Pass 2: nested copies — direct trumps nested; among nested-only peers
        # pick the highest freshness score (otherwise iteration order can let a
        # stale snapshot win and propagate forever).
        for message in agent.messages_received:
            sender_id = message.get('agent_id')
            for nested_message in message.get('relayed_messages', []):
                nested_sender_id = nested_message.get('agent_id')
                if (nested_sender_id is None
                        or nested_sender_id == self_agent_id
                        or nested_sender_id == sender_id):
                    continue
                if nested_sender_id in direct_sender_ids:
                    continue  # direct trumps nested
                nested_score = _freshness_score(nested_message)
                if (nested_sender_id not in relayed_by_sender_id
                        or nested_score > score_by_sender_id[nested_sender_id]):
                    relayed_by_sender_id[nested_sender_id] = _strip_nested_relay(nested_message)
                    score_by_sender_id[nested_sender_id] = nested_score

        agent.message_to_share['relayed_messages'] = list(relayed_by_sender_id.values())
        agent.message_to_share['updated_at'] = time.time()
        return Status.SUCCESS


# =============================================================================
# Dec branch (out-of-range follower) — order matches `bt_follower_static_full.xml`
# =============================================================================

class UnpackRelayedMessages(SyncAction):
    """Splice relay payload into the inbox so dec plugins see relayed peers as direct."""

    def __init__(self, name, agent):
        super().__init__(name, self._unpack)

    def _unpack(self, agent, blackboard):
        self_agent_id = agent.agent_id
        flattened_by_sender_id = {}     # peer_id → message
        scores_by_sender_id = {}        # peer_id → freshness score
        direct_sender_ids = set()       # peer_ids reached via 1-hop direct

        # Pass 1: direct copies — always 1-hop, always fresher than nested.
        for message in agent.messages_received:
            sender_id = message.get('agent_id')
            if sender_id is None or sender_id == self_agent_id:
                continue
            flattened_by_sender_id[sender_id] = message
            scores_by_sender_id[sender_id] = _freshness_score(message)
            direct_sender_ids.add(sender_id)

        # Pass 2: nested (relayed) copies — direct trumps relayed;
        # among nested-only peers pick the highest freshness score
        # (otherwise iteration order can let a stale snapshot win).
        for message in agent.messages_received:
            sender_id = message.get('agent_id')
            for nested_message in message.get('relayed_messages', []):
                nested_sender_id = nested_message.get('agent_id')
                if (nested_sender_id is None
                        or nested_sender_id == self_agent_id
                        or nested_sender_id == sender_id):
                    continue
                if nested_sender_id in direct_sender_ids:
                    continue  # direct trumps nested
                nested_score = _freshness_score(nested_message)
                if (nested_sender_id not in flattened_by_sender_id
                        or nested_score > scores_by_sender_id[nested_sender_id]):
                    flattened_by_sender_id[nested_sender_id] = nested_message
                    scores_by_sender_id[nested_sender_id] = nested_score

        agent.messages_received = list(flattened_by_sender_id.values())
        return Status.SUCCESS


class FilterClaimedTasks(SyncAction):
    """Strip cen-claimed tasks/agents from the dec plugin's view."""

    def __init__(self, name, agent):
        super().__init__(name, self._filter)

    def _filter(self, agent, blackboard):
        latest_plan = _get_latest_central_plan(agent)
        blackboard['_latest_central_plan'] = latest_plan
        if latest_plan is None:
            return Status.SUCCESS

        cen_claimed_agent_ids = set()
        cen_claimed_task_ids = set()
        for follower_id, bundle in latest_plan.get('task_allocations', {}).items():
            if follower_id == agent.agent_id:
                continue
            if bundle:
                cen_claimed_agent_ids.add(follower_id)
                cen_claimed_task_ids.update(t for t in bundle if t is not None)

        # Filter centrally-claimed tasks in "blackboard['local_tasks_info']"
        if cen_claimed_task_ids:
            local_tasks = blackboard.get('local_tasks_info', {})
            blackboard['local_tasks_info'] = {
                task_id: task for task_id, task in local_tasks.items()
                if task_id not in cen_claimed_task_ids
            }

        # Filter centrally-claimed agents/tasks in "agent.messages_received". cen-claimed agents' real messages are replaced with a minimal "release" carrying only `agent_id` — dec plugins detect the missing payload and reset whatever stale state they hold for that sender.
        if cen_claimed_agent_ids or cen_claimed_task_ids:
            now = time.time()
            cleaned_messages = []
            for message in agent.messages_received:
                sender_id = message.get('agent_id')
                if sender_id in cen_claimed_agent_ids:
                    cleaned_messages.append({
                        'agent_id': sender_id,
                        'updated_at': now,
                    })
                    continue
                agents_info = message.get('agents_info')
                tasks_info = message.get('tasks_info')
                agents_info_dirty = isinstance(agents_info, list) and any(
                    extract_agent_id(other_agent) in cen_claimed_agent_ids
                    for other_agent in agents_info
                )
                tasks_info_dirty = isinstance(tasks_info, list) and any(
                    extract_task_id(task) in cen_claimed_task_ids
                    for task in tasks_info
                )
                if agents_info_dirty or tasks_info_dirty:
                    message = dict(message)
                    if agents_info_dirty:
                        message['agents_info'] = [
                            other_agent for other_agent in agents_info
                            if extract_agent_id(other_agent) not in cen_claimed_agent_ids
                        ]
                    if tasks_info_dirty:
                        message['tasks_info'] = [
                            task for task in tasks_info
                            if extract_task_id(task) not in cen_claimed_task_ids
                        ]
                cleaned_messages.append(message)
            agent.messages_received = cleaned_messages

        return Status.SUCCESS


# =============================================================================
# CentralisationWrapper — paper's central architectural contribution
# =============================================================================

class FollowerProxy:
    """Leader-side stand-in for a follower — mimics BaseAgent's attribute surface
    so dec MRTA plugins run unchanged inside `CentralisationWrapper`."""

    def __init__(self, agent_id, position):
        self.agent_id = agent_id
        self.position = position
        self.messages_received = []
        self.message_to_share = {}
        self.assigned_task_id = None
        self.planned_tasks = []
        # `decision_maker` is attached lazily by AssignTask on first invocation.

    def set_planned_tasks(self, task_list):
        self.planned_tasks = task_list


class CentralisationWrapper(Node):
    """Decorator: simulate the dec MRTA child on each follower; broadcast on consensus."""

    def __init__(self, name, child):
        super().__init__(name)
        self.type = "CentralisationWrapper"
        self.children = [child]
        self.previous_allocations = {}
        # Leader-side per-follower proxies. 
        self.proxies = {}  # follower_id -> FollowerProxy
        # Leader-side cache of each proxy's last-tick `message_to_share`. 
        self.proxy_outboxes = {}  # follower_id -> dict (last message_to_share)

    async def run(self, agent, blackboard):
        agents = blackboard['local_agents_info']

        # Per-tick output.
        current_tick_allocations = {}
        current_tick_primary = {}  # primary-only view, for convergence check

        local_follower_ids = {a.agent_id for a in agents if a.type != 'Leader'}
        self.proxy_outboxes = {follower_id: o for follower_id, o in self.proxy_outboxes.items() if follower_id in local_follower_ids}
        self.proxies = {follower_id: p for follower_id, p in self.proxies.items() if follower_id in local_follower_ids}

        # Sanitize cached outboxes — blocks Pass-2 ghost reintroduction via the outbox feedback loop.
        local_task_ids = set(blackboard.get('local_tasks_info', {}).keys())
        outbox_snapshot = {
            follower_id: self._sanitize_cached_outbox(msg, local_follower_ids, local_task_ids)
            for follower_id, msg in self.proxy_outboxes.items()
        }

        for target_agent in agents:
            if target_agent.type == 'Leader':
                continue
            follower_id = target_agent.agent_id
            # Lazy create proxy; decision_maker is attached on first AssignTask invocation.
            if follower_id not in self.proxies:
                self.proxies[follower_id] = FollowerProxy(follower_id, target_agent.position)
            proxy = self.proxies[follower_id]
            # Refresh per-tick fields (pygame: copy from live target).
            proxy.position = pygame.Vector2(target_agent.position)
            # Build messages_received from the frozen outbox snapshot (excluding self).
            proxy.messages_received = [
                msg for other_follower_id, msg in outbox_snapshot.items()
                if other_follower_id != follower_id and msg
            ]
            proxy.message_to_share = {}
            # Shallow-copy leader's blackboard so each per-target invocation has its own I/O scope.
            target_blackboard = dict(blackboard)
            await self.children[0].run(proxy, target_blackboard)
            primary = target_blackboard.get('assigned_task_id')
            current_tick_primary[follower_id] = primary

            # Prefer plugin's `planned_tasks_id` (CBBA) on its outbox;
            # fall back to [primary] for single-task plugins.
            bundle = proxy.message_to_share.get('planned_tasks_id') if proxy.message_to_share else None
            if not bundle:
                bundle = [primary] if primary is not None else []
            current_tick_allocations[follower_id] = list(bundle)

            # Cache this proxy's outbox — visible only on the *next* tick's iteration.
            self.proxy_outboxes[follower_id] = dict(proxy.message_to_share) if proxy.message_to_share else {}

            # Mirror the proxy's plan back onto the live target so the platform's visualisation (path overlay) reflects the wrapper's decision. 
            target_agent.set_planned_tasks(list(proxy.planned_tasks))

        agent.reset_messages_received()

        # Always publish the current plan so followers act on the most
        # recent allocation — gates on consensus only the BT status signal,
        # not the broadcast itself (avoids stale-plan windows when team
        # membership changes mid-run).
        blackboard['central_plan'] = {
            'task_allocations': dict(current_tick_allocations),
            'created_at': time.time(),
        }

        if self._is_consensus_reached(current_tick_primary):
            return Status.SUCCESS
        self.previous_allocations = current_tick_primary.copy()
        return Status.RUNNING

    def _is_consensus_reached(self, current_allocations):
        """Consensus = every currently-active agent's allocation matches the
        previous tick. Tolerates team shrinkage (member moved out of leader
        range) so the remaining members can still be considered stable.
        """
        return (bool(self.previous_allocations)
                and current_allocations.items() <= self.previous_allocations.items())

    @staticmethod
    def _sanitize_cached_outbox(msg, local_follower_ids, local_task_ids):
        """Strip agents_info/tasks_info entries outside the leader's local view."""
        sanitized = dict(msg)
        if isinstance(sanitized.get('agents_info'), list):
            sanitized['agents_info'] = [a for a in sanitized['agents_info'] if extract_agent_id(a) in local_follower_ids]
        if isinstance(sanitized.get('tasks_info'), list):
            sanitized['tasks_info'] = [t for t in sanitized['tasks_info'] if extract_task_id(t) in local_task_ids]
        return sanitized

