"""
Behaviour-tree nodes for the letter_show scenario.

The BT runs a 2-phase auction every tick:

  Phase 1: ``AssignSuperTask`` — GRAPE decides which super-task
           (= cluster of pixels for one letter / sub-region) each
           agent should belong to. Once **all** agents have stabilised
           on a super-task for ``super_task_dwell_seconds``, the
           result is latched on the blackboard and Phase 1 stops
           re-running.

  ``RebalanceGroups`` — after GRAPE has converged, count agents
           vs tasks per super-task. If one super-task has more
           agents than tasks (surplus) and another has more tasks
           than agents (deficit), move the highest-battery agent
           from surplus → deficit. Runs once per generation, then
           latched.

  Phase 2: ``AssignTask`` — within the assigned super-task, run
           the yaml-specified phase-2 algorithm (CBBA or Distributed
           Hungarian) on the scoped task list.

Movement / arrival / idle nodes are inherited from
``platforms/mona/bt_nodes_mona`` so behaviour matches ``mona/basic``
and the rotation-shim controller stays consistent.
"""
import importlib
import time

import pygame

# Re-export every control-flow node + the shared MONA action/condition
# nodes so the BT XML loader can resolve them via getattr() against this
# module.
from platforms.mona.bt_nodes_mona import *  # noqa: F401,F403
from platforms.mona.bt_nodes_mona import BTNodeList, Status, SyncAction, SyncCondition

from core.utils import config

# letter_show-local plugins
from scenarios.mona.letter_show.plugins.grape import GRAPE


# ─── Node-name registration (de-duplicated) ─────────────────────────────
CUSTOM_ACTION_NODES = ['AssignSuperTask', 'RebalanceGroups', 'AssignTask']
CUSTOM_CONDITION_NODES = []

# Remove base-registered duplicates first, then re-register so the order
# in BTNodeList stays predictable across imports.
BTNodeList.ACTION_NODES = [n for n in BTNodeList.ACTION_NODES if n not in CUSTOM_ACTION_NODES]
BTNodeList.CONDITION_NODES = [n for n in BTNodeList.CONDITION_NODES if n not in CUSTOM_CONDITION_NODES]
BTNodeList.ACTION_NODES.extend(CUSTOM_ACTION_NODES)
BTNodeList.CONDITION_NODES.extend(CUSTOM_CONDITION_NODES)


# ─── Phase-2 plugin class — resolved from yaml at import time ───────────
_dm_plugin_path = config.get('decision_making', {}).get('plugin')
if _dm_plugin_path and '.' in _dm_plugin_path:
    _module_path, _class_name = _dm_plugin_path.rsplit('.', 1)
    _phase2_class = getattr(importlib.import_module(_module_path), _class_name)
else:
    _phase2_class = None


# ─── Convergence dwell time (sec) — yaml-tunable ────────────────────────
_super_task_dwell_required = config.get('tasks', {}).get('super_task_dwell_seconds', 1.0)


# ─── Phase 1 — GRAPE on super-tasks ─────────────────────────────────────
class AssignSuperTask(SyncAction):
    """Allocate this agent to a super-task via GRAPE.

    Latches its result on the blackboard once *all* agents have stabilised
    for ``super_task_dwell_seconds``. On the next generation
    (``super_task_converged`` reset by the Sim), re-runs from scratch."""

    def __init__(self, name, agent):
        super().__init__(name, self._update)
        self.decision_maker = GRAPE(agent)
        self._converge_start = None
        self._was_converged = False

    def _update(self, agent, blackboard):
        # Already converged — short-circuit.
        if blackboard.get('super_task_converged', False):
            self._was_converged = True
            return Status.SUCCESS

        # New generation detected (Sim reset state) → re-init GRAPE.
        if self._was_converged:
            self._was_converged = False
            self._converge_start = None
            self.decision_maker.reset()
            agent.super_task_message_to_share = {}
            agent.super_task_messages_received = []

        # Hold position while converging.
        agent.velocity = pygame.Vector2(0, 0)
        agent.acceleration = pygame.Vector2(0, 0)

        super_tasks_info = blackboard.get('super_tasks_info', {})
        if not super_tasks_info:
            return Status.SUCCESS  # no super-tasks configured — phase-1 is a no-op

        # Swap to the GRAPE message channel for this tick.
        orig_msg = agent.message_to_share
        orig_rcv = agent.messages_received
        agent.message_to_share = getattr(agent, 'super_task_message_to_share', {})
        agent.messages_received = getattr(agent, 'super_task_messages_received', [])

        grape_bb = dict(blackboard)
        grape_bb['local_tasks_info'] = super_tasks_info
        assigned_id = self.decision_maker.decide(grape_bb)

        # Save GRAPE's outbound; restore the regular CBBA channel.
        agent.super_task_message_to_share = agent.message_to_share
        agent.message_to_share = orig_msg
        agent.messages_received = orig_rcv

        blackboard['assigned_super_task_id'] = assigned_id
        agent.assigned_super_task_id = assigned_id

        # Global convergence: every agent must be assigned for ``dwell`` seconds.
        all_agents = list(getattr(agent, 'agents_info', None) or [])
        all_assigned = all(getattr(a, 'assigned_super_task_id', None) is not None for a in all_agents)
        if not all_assigned:
            self._converge_start = None
            return Status.RUNNING

        now = time.time()
        if self._converge_start is None:
            self._converge_start = now
        if now - self._converge_start >= _super_task_dwell_required:
            blackboard['super_task_converged'] = True
            self._converge_start = None

            # Pretty diagnostic, fired once per generation by the agent
            # whose id sorts first.
            if agent.agent_id == all_agents[0].agent_id:
                try:
                    lowest = min(
                        all_agents,
                        key=lambda a: getattr(a, 'battery', None) if getattr(a, 'battery', None) is not None else 100.0,
                    )
                    closest_st_id = (
                        min(super_tasks_info.values(),
                            key=lambda st: (st.center - lowest.position).length()).task_id
                        if super_tasks_info else None
                    )
                    batt = getattr(lowest, 'battery', None)
                    batt_str = f"{batt:.1f}%" if batt is not None else "Unknown (100.0%)"
                    print(f"\n{'=' * 50}\n[GRAPE Debug] Allocation Result")
                    print(f"  1. Lowest battery agent: Agent {lowest.agent_id} (Battery: {batt_str})")
                    print(f"  2. Closest SuperTask to Agent {lowest.agent_id}: ST{closest_st_id}")
                    print(f"  3. Assigned SuperTask: ST{getattr(lowest, 'assigned_super_task_id', None)}")
                    print('=' * 50)
                except Exception as e:
                    print(f"[GRAPE Debug] Error: {e}")

            return Status.SUCCESS

        return Status.RUNNING

    def halt(self):
        # Preserve the convergence timer across reactive ticks.
        pass


# ─── RebalanceGroups — post-GRAPE one-shot rebalance ────────────────────
class RebalanceGroups(SyncAction):
    """After Phase-1 converges, move surplus agents (one super-task has
    more agents than tasks) to deficit super-tasks. The agent with the
    *highest* battery is moved (it can afford the longer route).

    Runs at most once per generation — latched via
    ``blackboard['rebalance_done']``."""

    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        if blackboard.get('rebalance_done', False):
            return Status.SUCCESS

        super_tasks = blackboard.get('super_tasks_info', {})
        if not super_tasks:
            blackboard['rebalance_done'] = True
            return Status.SUCCESS

        all_agents = list(getattr(agent, 'agents_info', None) or [])

        def agent_count(st_id):
            return sum(1 for a in all_agents if getattr(a, 'assigned_super_task_id', None) == st_id)

        def task_count(st):
            return sum(1 for t in st.tasks if not t.completed)

        # Iterate until no surplus remains.
        while True:
            surplus_st = next(
                (st for st in super_tasks.values() if agent_count(st.task_id) > task_count(st)),
                None,
            )
            if surplus_st is None:
                break

            deficit_st = max(
                (st for st in super_tasks.values() if st.task_id != surplus_st.task_id),
                key=lambda st: task_count(st) - agent_count(st.task_id),
                default=None,
            )
            if deficit_st is None:
                break

            surplus_agents = [
                a for a in all_agents
                if getattr(a, 'assigned_super_task_id', None) == surplus_st.task_id
            ]
            if not surplus_agents:
                break

            # Move the *highest*-battery agent — it has the spare energy.
            highest = max(
                surplus_agents,
                key=lambda a: getattr(a, 'battery', None) or 100.0,
            )
            highest.assigned_super_task_id = deficit_st.task_id

        # Reflect any change for this agent on the blackboard.
        blackboard['assigned_super_task_id'] = getattr(agent, 'assigned_super_task_id', None)
        blackboard['rebalance_done'] = True
        return Status.SUCCESS


# ─── Phase 2 — pixel-level allocation within the assigned super-task ────
class AssignTask(SyncAction):
    """Run the yaml-specified phase-2 algorithm (CBBA / Hungarian) on the
    tasks belonging to *this agent's* assigned super-task."""

    def __init__(self, name, agent):
        super().__init__(name, self._update)
        if _phase2_class is None:
            raise RuntimeError(
                "[AssignTask] decision_making.plugin not configured in yaml."
            )
        self.decision_maker = _phase2_class(agent)

    def _update(self, agent, blackboard):
        assigned_super_task_id = blackboard.get('assigned_super_task_id')
        if assigned_super_task_id is None:
            return Status.FAILURE

        super_task = blackboard.get('super_tasks_info', {}).get(assigned_super_task_id)
        if super_task is None:
            return Status.FAILURE

        tasks_list = {t.task_id: t for t in super_task.tasks if not t.completed}
        if not tasks_list:
            return Status.FAILURE

        scoped_bb = dict(blackboard)
        scoped_bb['local_tasks_info'] = tasks_list

        assigned_id = self.decision_maker.decide(scoped_bb)
        if assigned_id is None or assigned_id not in tasks_list:
            agent.set_planned_tasks([])
            return Status.FAILURE

        agent.set_assigned_task_id(assigned_id)
        blackboard['assigned_task_id'] = assigned_id
        agent.set_planned_tasks([tasks_list[assigned_id]])
        return Status.SUCCESS


# ─── GatherLocalInfo override — also gathers super-task channel ─────────
# The shared `GatherLocalInfo` from `platforms.pygame.bt_nodes_pygame`
# (re-exported via `bt_nodes_mona`) only sets `local_tasks_info` and
# `local_agents_info`. letter_show needs to also surface the GRAPE
# super-task message channel and the live super-task list.
class GatherLocalInfo(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard):
        blackboard['local_tasks_info'] = {
            t.task_id: t for t in agent.get_tasks_nearby(with_completed_task=False)
        }

        # Regular CBBA channel — populates self.agents_nearby.
        blackboard['local_agents_info'] = agent.local_message_receive()

        # GRAPE super-task channel — pull from each peer.
        super_msgs = []
        for other in agent.agents_nearby:
            if other.agent_id != agent.agent_id:
                msg = getattr(other, 'super_task_message_to_share', {})
                if msg:
                    super_msgs.append(msg)
        agent.super_task_messages_received = super_msgs

        # Expose live super-task list (only ones not yet completed).
        blackboard['super_tasks_info'] = {
            st.task_id: st
            for st in getattr(agent, 'super_tasks_info', [])
            if not st.completed
        }
        return Status.SUCCESS


# Re-register GatherLocalInfo (override the bt_nodes_mona / bt_nodes_pygame one).
if 'GatherLocalInfo' not in BTNodeList.ACTION_NODES:
    BTNodeList.ACTION_NODES.append('GatherLocalInfo')
