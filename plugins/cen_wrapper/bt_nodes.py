"""Platform-agnostic BT nodes for hybrid centralised/decentralised MRTA.

Three ways to use a leader whose communication range covers only part of the team:
  Leader-as-proxy  (CentralisationWrapper + EmitProxyMessage + RelayMessages scope="outside")
                   the leader runs the team's decentralised MRTA protocol on behalf of the
                   followers it reaches; the two parts of the team exchange protocol messages.
  Leader-as-relay  (RelayMessages scope="all" nested="1" on the leader; UnpackRelayedMessages on
                   the followers) the leader only forwards messages.
  Leader-as-solver (AssignCenTask + TeachBT on the leader; ApplyCenTask / ForwardCenAllocation /
                   RelayMessages scope="outside" nested="1" / UnpackRelayedMessages /
                   FilterClaimedTasks on the followers) the leader runs a dedicated centralised
                   solver and its plan has priority.

Originally defined inside `scenarios/pygame/features/cen_wrapper/bt_nodes.py`; extracted here so
non-pygame consumers (e.g. the ROS 2 cen_wrapper test scenario) can import the same nodes without
depending on the pygame scenario module.
"""
import importlib
import time

import pygame

from core.bt_nodes import Node, Status, SyncAction, SyncCondition
from core.utils import config, extract_agent_id, extract_task_id


# ─── Tunable parameters ───────────────────────────────────────────────
# central_plan freshness window. pygame keeps "no TTL" by default (leader is always present in current paper experiments); non-pygame consumers override this module-level constant (e.g. ROS2 with multi-hop mesh).
_CENTRAL_PLAN_TTL = float('inf')


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
        return Status.SUCCESS


class DepartedFollower:
    """Leader-side stand-in for a follower that left the leader's range (AssignCenTask keep_departed): the agent
    surface the centralised solvers read (id, type, position) plus the visualisation hook."""

    def __init__(self, source):
        self.agent_id = source.agent_id
        self.type = source.type
        self.position = pygame.Vector2(source.position)
        self.planned_tasks = []

    def set_planned_tasks(self, task_list):
        self.planned_tasks = task_list


class AssignCenTask(SyncAction):
    """[Leader] Run the centralised allocation plugin (yaml `decision_making.cen_plugin`).

    `keep_departed` 0 (default) / 1 (Leader-as-solver "grace"): a follower that leaves the range stays in the
    solver's problem as a stand-in at its last known position, until the task the solver gave it is gone or a
    relayed message from it arrives (its position and own task are then taken from that message). Without this the
    solver hands a departed follower's task to an inside robot on the tick it leaves, and takes it back when the
    follower steps in again, so the two robots chatter at the boundary.
    """

    def __init__(self, name, agent, keep_departed=0):
        super().__init__(name, self._assign)
        if cen_decision_making_class is None:
            raise RuntimeError(
                "[AssignCenTask] yaml is missing `decision_making.cen_plugin`."
            )
        self.cen_decision_maker = cen_decision_making_class(agent)
        self.keep_departed = bool(keep_departed)
        self._seen = {}       # follower_id -> last live agent object seen in range
        self._departed = {}   # follower_id -> DepartedFollower

    def _assign(self, agent, blackboard):
        if self.keep_departed:
            agents = list(blackboard.get('local_agents_info') or [])
            live_ids = {a.agent_id for a in agents}
            for a in agents:
                if a.type != 'Leader':
                    self._seen[a.agent_id] = a
                    self._departed.pop(a.agent_id, None)
            plan = (blackboard.get('central_plan') or {}).get('task_allocations') or {}
            local_task_ids = set((blackboard.get('local_tasks_info') or {}).keys())
            relayed = {}
            for message in agent.messages_received:
                for nested in message.get('relayed_messages', None) or []:
                    sid = nested.get('agent_id')
                    if sid is not None and sid not in live_ids and nested.get('type') != 'Leader':
                        relayed[sid] = nested
            for fid, src in list(self._seen.items()):
                if fid in live_ids:
                    continue
                given = [t for t in (plan.get(fid) or []) if t in local_task_ids]
                if fid not in self._departed:
                    if not given:
                        self._seen.pop(fid, None)      # left with no task: nothing to keep
                        continue
                    self._departed[fid] = DepartedFollower(src)
                stand_in = self._departed[fid]
                msg = relayed.get(fid)
                if msg is not None:
                    # A relayed message says where the departed robot is and what it chose. The solvers take no
                    # pinned assignments, so its choice is expressed as its position (standing on that task).
                    own = msg.get('assigned_task_id')
                    tasks = blackboard.get('local_tasks_info') or {}
                    if own in tasks and getattr(tasks[own], 'position', None) is not None:
                        stand_in.position = pygame.Vector2(tasks[own].position)
                    elif msg.get('position') is not None:
                        pos = msg['position']
                        stand_in.position = pygame.Vector2(pos[0], pos[1]) if isinstance(pos, (list, tuple)) else pygame.Vector2(pos)
                if not given and msg is None:
                    self._departed.pop(fid); self._seen.pop(fid, None)   # its task is gone and no news: release it
                    continue
            blackboard['local_agents_info'] = agents + list(self._departed.values())
        self.cen_decision_maker.decide(blackboard)
        # The plugin writes blackboard['central_plan']; TeachBT then broadcasts it to followers.
        return Status.SUCCESS


# =============================================================================
# Mesh-relay shared helpers
# =============================================================================

def _get_latest_central_plan(messages_received, ttl_seconds=float('inf')):
    """Pick the freshest central_plan from the inbox, rejecting any older than ttl_seconds (default: no TTL)."""
    now = time.time()
    latest_plan, latest_created_at = None, -1
    for message in messages_received:
        plan = message.get('central_plan')
        if plan is None:
            continue
        created_at = plan['created_at']
        if now - created_at > ttl_seconds:
            continue
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
# Cen branch (in-range follower)
# =============================================================================

class ApplyCenTask(SyncAction):
    """Adopt this follower's primary from the leader's broadcast."""

    def __init__(self, name, agent):
        super().__init__(name, self._apply)

    def _apply(self, agent, blackboard):
        latest_plan = _get_latest_central_plan(agent.messages_received, _CENTRAL_PLAN_TTL)
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
            # Leader gone or plan stale — drop it from outbox so peers stop relaying stale plan via mesh.
            agent.message_to_share.pop('central_plan', None)
            return Status.SUCCESS

        agent.message_to_share['central_plan'] = latest_plan
        agent.message_to_share['updated_at'] = time.time()
        return Status.SUCCESS


class EmitProxyMessage(SyncAction):
    """[Connected follower] Broadcast the protocol message computed by this follower's proxy.

    Must come after ApplyCenTask (which caches the latest plan on the blackboard). The plan carries a
    per-follower proxy message for boundary followers (CentralisationWrapper) and, with export="merged",
    one consensus copy plus every proxy's own fields, from which this node rebuilds the proxy message of
    any connected follower. Whenever a proxy message is available the outbox is replaced by it, so a
    connected follower never keeps broadcasting the stale message its own plugin wrote before it entered.

    `self_apply` 0 (default) / 1: also keep the proxy message for the follower itself (`_proxy_message_for_self`,
    with the leader's id in `_leader_id`); `AdoptProxyState` hands it to the plugin when the follower leaves.
    """

    def __init__(self, name, agent, self_apply=0):
        super().__init__(name, self._emit)
        self.self_apply = bool(self_apply)

    def _emit(self, agent, blackboard):
        plan = blackboard.get('_latest_central_plan') or {}
        proxy_message = (plan.get('proxy_messages') or {}).get(agent.agent_id)
        own = (plan.get('proxy_own') or {}).get(agent.agent_id)
        if own is not None and plan.get('proxy_common'):
            # export="merged": the consensus copy plus this follower's own fields is its proxy's message
            proxy_message = dict(plan['proxy_common'])
            proxy_message.update(own)
            if 'agent_id' not in proxy_message:
                proxy_message['agent_id'] = agent.agent_id
        if proxy_message is not None:
            agent.message_to_share = dict(proxy_message)
            if self.self_apply:
                agent._proxy_message_for_self = dict(proxy_message)
                leader_ids = [m.get('agent_id') for m in agent.messages_received if m.get('type') == 'Leader']
                if leader_ids:
                    agent._leader_id = leader_ids[0]
        return Status.SUCCESS


class AdoptProxyState(SyncAction):
    """[Disconnected follower, before AssignTask] Feed the follower's last proxy message to its plugin.

    Pairs with `EmitProxyMessage self_apply="1"`. While connected, the follower's own plugin does not run, so its
    state is stale when it leaves. On the first decentralised tick the kept proxy message is appended to the inbox
    once, and the plugin merges it the way it merges any neighbour's message. It is handed over under the leader's
    id, because a consensus protocol ignores a message carrying the receiver's own id (CBBA skips it). Without a kept
    message the node does nothing.
    """

    def __init__(self, name, agent):
        super().__init__(name, self._adopt)

    def _adopt(self, agent, blackboard):
        proxy_message = getattr(agent, '_proxy_message_for_self', None)
        if proxy_message is not None:
            message = dict(proxy_message)
            leader_id = getattr(agent, '_leader_id', None)
            if leader_id is not None:
                message['agent_id'] = leader_id
            message['adopted'] = True   # so that KeepPlanWhenIsolated's isolation test ignores it (it is not a neighbour)
            agent.messages_received = list(agent.messages_received) + [message]
            agent._proxy_message_for_self = None
        return Status.SUCCESS


class ResetProtocolState(SyncAction):
    """[Disconnected follower, before AssignTask] Give the follower's plugin a fresh state on the first tick after it
    leaves the cluster (Leader-as-solver "reset").

    While connected, the follower's own plugin does not run, so its protocol state (CBBA winning lists, GRAPE
    partition) is stale when it leaves. A dedicated solver produces only a plan, not protocol state the follower
    could inherit (cf. AdoptProxyState), so the plugin is re-created and rebuilds its state from the messages it now
    hears. Algorithm-agnostic: it re-instantiates whatever `agent.decision_maker` is.
    """

    def __init__(self, name, agent):
        super().__init__(name, self._reset)
        self._reset_for_plan = None     # created_at of the plan the follower held at its last reset
        self._branch_cached = object()  # created_at of the plan this branch itself cached at its previous tick

    def _reset(self, agent, blackboard):
        # `_latest_central_plan` is written by ApplyCenTask (connected branch: the leader's plan) and, in the solver
        # tree, by FilterClaimedTasks later in this branch (a plan a neighbour forwarded). The follower has just left
        # if the plan on the blackboard is not the one this branch cached at its previous tick and is newer than the
        # plan at the last reset.
        plan = blackboard.get('_latest_central_plan') or {}
        created = plan.get('created_at')
        if created is not None and created != self._reset_for_plan and created != self._branch_cached:
            if getattr(agent, 'decision_maker', None) is not None:
                agent.decision_maker = type(agent.decision_maker)(agent)
            self._reset_for_plan = created
        # What FilterClaimedTasks will cache this tick; a forwarded plan may also arrive nested in a relayed message.
        inbox = list(agent.messages_received)
        inbox += [n for m in agent.messages_received for n in (m.get('relayed_messages') or [])]
        forwarded = _get_latest_central_plan(inbox, _CENTRAL_PLAN_TTL)
        self._branch_cached = forwarded.get('created_at') if forwarded else None
        return Status.SUCCESS


class KeepPlanWhenIsolated(SyncAction):
    """[Disconnected follower, in place of AssignTask while isolated] Keep the follower's last decision.

    Isolation: the inbox holds no message from another robot. An isolated follower would run its plugin on itself
    alone and might pick a different task, then flip between the two at the boundary. Instead it keeps its own last
    task while that task still exists. Returns SUCCESS with the task set, or FAILURE (not isolated, or no task to
    keep) so that a ReactiveFallback continues to AssignTask:
        <ReactiveFallback> <KeepPlanWhenIsolated source="own"/> <AssignTask/> </ReactiveFallback>
    `source="own"` (the follower's own last task) is the only mode.
    """

    def __init__(self, name, agent, source="own"):
        super().__init__(name, self._keep)
        if source != "own":
            raise ValueError(f"[KeepPlanWhenIsolated] source must be 'own', not {source!r}")

    def _keep(self, agent, blackboard):
        # The message AdoptProxyState hands over (marked `adopted`) is the follower's own proxy state, not a neighbour.
        if any(not m.get('adopted') for m in agent.messages_received):
            return Status.FAILURE
        task_id = getattr(agent, 'assigned_task_id', None)
        if task_id is None or task_id not in (blackboard.get('local_tasks_info') or {}):
            return Status.FAILURE
        blackboard['assigned_task_id'] = task_id
        agent.assigned_task_id = task_id
        return Status.SUCCESS


class CommitToPlan(SyncAction):
    """[Disconnected follower, in place of AssignTask] Keep executing the plan's bundle, isolated or not.

    Leader-as-solver "commit": a follower that left the leader's range keeps the first task of the bundle the plan
    gave it that still exists, until none is left; only then does it run its own plugin. The whole bundle is followed
    because the leader's stand-in (AssignCenTask keep_departed) holds the whole bundle too. It also covers
    KeepPlanWhenIsolated. Returns SUCCESS with the task set, or FAILURE (no plan held, or every task of the bundle
    gone) so that a ReactiveFallback continues to the plugin.
    """

    def __init__(self, name, agent):
        super().__init__(name, self._keep)

    def _keep(self, agent, blackboard):
        plan = blackboard.get('_latest_central_plan') or {}
        bundle = (plan.get('task_allocations') or {}).get(agent.agent_id, []) or []
        tasks = blackboard.get('local_tasks_info') or {}
        task_id = next((t for t in bundle if t in tasks), None)
        if task_id is None:
            return Status.FAILURE
        blackboard['assigned_task_id'] = task_id
        agent.assigned_task_id = task_id
        return Status.SUCCESS


class RelayMessages(SyncAction):
    """Put the messages heard from other followers into our outbox (`relayed_messages`) so that
    they travel one hop further. Leader messages are never relayed.

    `scope`   "outside" (default): only followers that are not in the leader's latest plan, i.e. not
              leader-connected (the plan is cached by ApplyCenTask earlier in the branch); "all": every
              follower heard.
    `nested`  0 (default): first-hand copies only. 1: also pass on, for every follower not heard
              first-hand, the freshest copy that was relayed to us (two hops; the copy is stripped of its
              own relays), and stamp the outbox as fresh.

    Leader-as-proxy followers use scope="outside" (after EmitProxyMessage, which may replace the
    outbox), Leader-as-solver followers scope="outside" nested="1", and the leader of
    Leader-as-relay scope="all" nested="1".
    """

    def __init__(self, name, agent, scope="outside", nested=0):
        super().__init__(name, self._stage)
        if scope not in ("outside", "all"):
            raise ValueError(f"[RelayMessages] scope must be 'outside' or 'all', not {scope!r}")
        self.scope = scope
        self.nested = bool(nested)

    def _stage(self, agent, blackboard):
        self_agent_id = agent.agent_id
        plan = blackboard.get('_latest_central_plan') or {}
        connected_ids = set((plan.get('task_allocations') or {}).keys()) if self.scope == "outside" else set()
        relayed_by_sender_id = {}     # follower id → its message, without the relays it carries
        score_by_sender_id = {}       # follower id → freshness score of that message

        # Pass 1: first-hand copies.
        for message in agent.messages_received:
            sender_id = message.get('agent_id')
            if sender_id is None or sender_id == self_agent_id or sender_id in connected_ids:
                continue
            if message.get('type') == 'Leader':
                continue
            relayed_by_sender_id[sender_id] = _strip_nested_relay(message)
            score_by_sender_id[sender_id] = _freshness_score(message)

        # Pass 2: copies relayed to us. A first-hand copy always wins; among relayed copies the
        # freshest wins (otherwise iteration order could let a stale copy circulate forever).
        if self.nested:
            direct_sender_ids = set(relayed_by_sender_id)
            for message in agent.messages_received:
                relayer_id = message.get('agent_id')
                for nested_message in message.get('relayed_messages', None) or []:
                    nested_sender_id = nested_message.get('agent_id')
                    if (nested_sender_id is None
                            or nested_sender_id == self_agent_id
                            or nested_sender_id == relayer_id
                            or nested_sender_id in connected_ids):
                        continue
                    if nested_sender_id in direct_sender_ids:
                        continue
                    nested_score = _freshness_score(nested_message)
                    if (nested_sender_id not in relayed_by_sender_id
                            or nested_score > score_by_sender_id[nested_sender_id]):
                        relayed_by_sender_id[nested_sender_id] = _strip_nested_relay(nested_message)
                        score_by_sender_id[nested_sender_id] = nested_score

        agent.message_to_share['relayed_messages'] = list(relayed_by_sender_id.values())
        if self.nested:
            agent.message_to_share['updated_at'] = time.time()
        return Status.SUCCESS


# =============================================================================
# Dec branch (out-of-range follower)
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
        latest_plan = _get_latest_central_plan(agent.messages_received, _CENTRAL_PLAN_TTL)
        blackboard['_latest_central_plan'] = latest_plan
        if latest_plan is None:
            return Status.SUCCESS

        cen_claimed_agent_ids = set()
        cen_claimed_task_ids = set()
        for follower_id, bundle in latest_plan.get('task_allocations', {}).items():
            if follower_id == agent.agent_id:
                continue
            # Followers in the plan are cen-covered even with an empty bundle — strip so dec doesn't re-assign them.
            cen_claimed_agent_ids.add(follower_id)
            if bundle:
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
# CentralisationWrapper (Leader-as-proxy)
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
    """[Leader] Decorator that runs the decentralised MRTA child once per leader-connected
    follower, on a proxy of that follower, and publishes the result as the leader's plan.

    The whole team runs ONE decentralised MRTA protocol. For the followers the leader reaches, the
    protocol is executed here (one FollowerProxy per follower; the plugin runs unchanged); for the
    others it is executed by the followers themselves. The two parts exchange messages in the
    protocol's own format instead of through a plan that disconnected followers must obey:

      outbound  the protocol message of a boundary follower's proxy is attached to the plan
                (`proxy_messages`); the follower broadcasts it as its own (EmitProxyMessage), so
                disconnected neighbours see an ordinary peer.
      inbound   connected followers relay what they hear first-hand from disconnected followers
                (RelayMessages scope="outside"); those messages enter every proxy's inbox, and so
                does the last message of a follower that has just entered (written while outside).

    A boundary follower is a connected follower that relayed at least one disconnected follower's
    message this tick. With the whole team connected nothing is relayed and no proxy message
    leaves the leader. The proxies keep whatever the protocol itself keeps about robots outside the
    cluster (`_sanitize_cached_outbox`), so the cluster behaves like a set of ordinary participants.

    XML attributes:
      inbound, outbound  1 (default) / 0: switch one mechanism off (ablation).
      export             "boundary" (default): attach the messages of boundary followers' proxies;
                         "merged": also attach ONE copy of the protocol's consensus fields
                         (`proxy_common`) plus every proxy's robot-specific fields (`proxy_own`), from
                         which EmitProxyMessage rebuilds the proxy message of any connected follower.
    """

    def __init__(self, name, child, inbound=1, outbound=1, export="boundary"):
        super().__init__(name)
        self.type = "CentralisationWrapper"
        self.children = [child]
        self.previous_allocations = {}
        self.inbound = bool(inbound)
        self.outbound = bool(outbound)
        if export not in ("boundary", "merged"):
            raise ValueError(f"[CentralisationWrapper] export must be 'boundary' or 'merged', not {export!r}")
        self.export = export
        # Leader-side per-follower proxies.
        self.proxies = {}  # follower_id -> FollowerProxy
        # Leader-side cache of each proxy's last-tick `message_to_share`.
        self.proxy_outboxes = {}  # follower_id -> dict (last message_to_share)
        # follower_id -> the proxy's last non-empty protocol message (export="merged"). A protocol message stays
        # valid until the plugin issues a new one; GRAPE, for one, writes a message only on a coalition change.
        self.proxy_last_messages = {}

    async def run(self, agent, blackboard):
        agents = blackboard['local_agents_info']

        local_follower_ids = {a.agent_id for a in agents if a.type != 'Leader'}
        entering_ids = local_follower_ids - set(self.proxies)   # in range now, no proxy yet: they have just entered
        self.proxy_outboxes = {follower_id: o for follower_id, o in self.proxy_outboxes.items() if follower_id in local_follower_ids}
        self.proxy_last_messages = {follower_id: o for follower_id, o in self.proxy_last_messages.items() if follower_id in local_follower_ids}
        self.proxies = {follower_id: p for follower_id, p in self.proxies.items() if follower_id in local_follower_ids}
        local_task_ids = set(blackboard.get('local_tasks_info', {}).keys())

        # Inbound: what connected followers heard from disconnected ones, plus the last message of a follower that
        # has just entered (written while it was outside, so it carries what it learnt out there).
        outside_messages, boundary_ids = self._collect_outside_messages(
            agent.messages_received, local_follower_ids)
        for message in agent.messages_received:
            if message.get('agent_id') in entering_ids and message.get('type') != 'Leader':
                outside_messages.append(_strip_nested_relay(message))
        if not self.inbound:
            outside_messages = []

        # Sanitize cached outboxes — blocks Pass-2 ghost reintroduction via the outbox feedback loop.
        outbox_snapshot = {
            follower_id: self._sanitize_cached_outbox(msg, local_follower_ids, local_task_ids)
            for follower_id, msg in self.proxy_outboxes.items()
        }
        export_ids = boundary_ids if self.outbound else set()   # outbound: proxies whose message is shipped with the plan

        current_tick_allocations = {}
        current_tick_primary = {}  # primary-only view, for convergence check
        proxy_messages = {}
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
            # Build messages_received from the frozen outbox snapshot (excluding self) and the inbound messages.
            proxy.messages_received = [
                msg for other_follower_id, msg in outbox_snapshot.items()
                if other_follower_id != follower_id and msg
            ] + list(outside_messages)
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
            if proxy.message_to_share:
                self.proxy_last_messages[follower_id] = dict(proxy.message_to_share)
                if follower_id in export_ids:
                    proxy_messages[follower_id] = dict(proxy.message_to_share)

            # Mirror the proxy's plan onto the live target for path-overlay visualisation. Defensive `hasattr` — non-pygame platforms (e.g. ROS2) pass shim agent views that don't expose this method and handle visualisation via their own broadcast topic.
            if hasattr(target_agent, 'set_planned_tasks'):
                target_agent.set_planned_tasks(list(proxy.planned_tasks))

        agent.reset_messages_received()

        # Always publish the current plan so followers act on the most
        # recent allocation — gates on consensus only the BT status signal,
        # not the broadcast itself (avoids stale-plan windows when team
        # membership changes mid-run).
        plan = {
            'task_allocations': dict(current_tick_allocations),
            'proxy_messages': proxy_messages,
            'created_at': time.time(),
        }
        if self.outbound and self.export == "merged":
            plan['proxy_common'], plan['proxy_own'] = self._merged_export()
        blackboard['central_plan'] = plan

        if self._is_consensus_reached(current_tick_primary):
            return Status.SUCCESS
        self.previous_allocations = current_tick_primary.copy()
        return Status.RUNNING

    @staticmethod
    def _collect_outside_messages(leader_inbox, local_follower_ids):
        """Returns (freshest relayed message per follower that is not leader-connected, ids of the boundary
        followers that relayed them)."""
        outside = {}
        boundary_ids = set()
        for message in leader_inbox:
            for nested in message.get('relayed_messages', None) or []:
                sender_id = nested.get('agent_id')
                if sender_id is None or sender_id in local_follower_ids:
                    continue
                if nested.get('type') == 'Leader':
                    continue
                boundary_ids.add(message.get('agent_id'))
                if (sender_id not in outside
                        or _freshness_score(nested) > _freshness_score(outside[sender_id])):
                    outside[sender_id] = _strip_nested_relay(nested)
        return list(outside.values()), boundary_ids

    def _is_consensus_reached(self, current_allocations):
        """Consensus = every currently-active agent's allocation matches the
        previous tick. Tolerates team shrinkage (member moved out of leader
        range) so the remaining members can still be considered stable.
        """
        return (bool(self.previous_allocations)
                and current_allocations.items() <= self.previous_allocations.items())

    @staticmethod
    def _sanitize_cached_outbox(msg, local_follower_ids, local_task_ids):
        """Strip only the `tasks_info` entries outside the leader's local view. `agents_info` is protocol state about
        robots outside the cluster, which the protocol itself never drops (the decentralised Hungarian coordinates
        through it alone)."""
        sanitized = dict(msg)
        if isinstance(sanitized.get('tasks_info'), list):
            sanitized['tasks_info'] = [t for t in sanitized['tasks_info'] if extract_task_id(t) in local_task_ids]
        return sanitized

    # Fields of a protocol message that belong to the sender alone; everything else is consensus state that the
    # proxies share once they agree (CBBA winning lists, GRAPE partition / evolution number, Hungarian robot list).
    OWN_FIELDS = ('agent_id', 'assigned_task_id', 'planned_tasks_id', 'position', 'mutex_tiebreak', 'updated_at')

    def _merged_export(self):
        """One consensus copy (from the freshest of the proxies' last messages) and every proxy's own fields."""
        live = {fid: m for fid, m in self.proxy_last_messages.items() if m}
        if not live:
            return {}, {}
        # A message carrying a consensus counter (`evolution_number`, GRAPE) wins by that counter, otherwise by
        # wall-clock freshness.
        freshest = max(live.values(), key=lambda m: (m.get('evolution_number', 0) or 0, _freshness_score(m)))
        common = {k: v for k, v in freshest.items() if k not in self.OWN_FIELDS}
        own = {fid: {k: v for k, v in m.items() if k in self.OWN_FIELDS} for fid, m in live.items()}
        return common, own
