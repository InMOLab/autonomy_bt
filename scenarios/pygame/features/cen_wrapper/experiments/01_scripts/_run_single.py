"""Single headless dynamic run of the experiments.

Runs one cen_wrapper simulation described by a JSON spec (argv[1]) and prints
`RESULT_JSON:{...}` on stdout. Shared by exp5_leader_relay_baseline.py,
exp6_message_delay.py and exp7_dynamic_ablation.py so that all three measure
the same quantities in the same way.

Run from the project root (autonomy_bt/); normally invoked by `_campaign.py`.

Spec keys (all optional except `yaml` and `seed`):
    yaml                 config path relative to the project root
    seed                 random seed
    max_ticks            safety cap (default 20000)
    leader_radius        Leader.communication_radius (0 is replaced by 0.1: pygame treats <= 0 as "global")
    follower_radius      Follower.communication_radius
    leader_bt            Leader BT xml (file name in the scenario folder)
    follower_bt          Follower BT xml
    follower_qty         number of followers
    task_qty             number of tasks
    max_tasks_per_agent  CBBA bundle size
    task_region          [x_min, x_max, y_min, y_max] of the task locations (default: the yaml's)
    leader_position      [x, y] (default [700, 500], the arena centre, as in Exp 3 / Exp 4)
    cbba_bundle_reset    "none" (default, original CBBA) or "full" (CBBA with Full Bundle Reset)

Activity metrics (fractions of follower-ticks; they sum to 1): executing_fraction (task amount went down),
moving_fraction (otherwise moved), still_converging_fraction (otherwise: has a task, or no task and its
allocation changed this tick — the MRTA is still deciding), still_no_task_fraction (no task, allocation
unchanged); still_with_task_fraction is the part of still_converging with a task; team_decision_ticks counts
ticks on which no follower moves or executes.
    delay_ticks          extra message delay in BT ticks (default 0 = the simulator's normal delivery)
    comm_every           sample communication payload every N ticks (default 10; 0 disables)
    trace_out            path of a per-tick trace (JSON lines; default none). One record per tick with, for every
                         follower: position, distance to the leader, whether the BT ran the centralised branch this
                         tick (a leader message in the inbox), the followers it heard, its primary task and bundle, the
                         task the plan it holds gives it, and the plugin's belief (GRAPE: coalitions of its partition;
                         CBBA: its winners list) — plus the tasks (position, remaining amount) and the leader's plan.
                         Boundary-behaviour analysis (2026-10-05); does not change the run.
"""
import os, sys, asyncio, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")

spec = json.loads(sys.argv[1])

from core.utils import set_config
set_config(spec["yaml"])
from core.utils import config

ZERO_SUBSTITUTE = 0.1
types = config["agents"]["types"]
if spec.get("leader_radius") is not None:
    r = float(spec["leader_radius"])
    types["Leader"]["communication_radius"] = ZERO_SUBSTITUTE if r == 0 else r
if spec.get("follower_radius") is not None:
    types["Follower"]["communication_radius"] = float(spec["follower_radius"])
if spec.get("leader_bt"):
    types["Leader"]["behavior_tree_xml"] = spec["leader_bt"]
if spec.get("follower_bt"):
    types["Follower"]["behavior_tree_xml"] = spec["follower_bt"]
if spec.get("follower_qty") is not None:
    types["Follower"]["quantity"] = int(spec["follower_qty"])
if spec.get("task_qty") is not None:
    config["tasks"]["quantity"] = int(spec["task_qty"])
if spec.get("max_tasks_per_agent") is not None:
    config["decision_making"]["CBBA"]["max_tasks_per_agent"] = int(spec["max_tasks_per_agent"])
if spec.get("cbba_bundle_reset"):
    config["decision_making"].setdefault("CBBA", {})["bundle_reset"] = spec["cbba_bundle_reset"]  # "none" | "full"
if spec.get("task_region") is not None:
    x_min, x_max, y_min, y_max = spec["task_region"]
    config["tasks"]["locations"].update({"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max})

config["simulation"]["random_seed"] = int(spec["seed"])
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {})
for k in ("save_gif", "save_timewise_result_csv", "save_agentwise_result_csv", "save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {})["enabled"] = False
config["simulation"]["mode"] = "dynamic"
config["simulation"]["speed_up_factor"] = 1
config["simulation"]["max_simulation_time"] = 0

MAX_TICKS = int(spec.get("max_ticks", 20000))
DELAY = int(spec.get("delay_ticks", 0))
COMM_EVERY = int(spec.get("comm_every", 10))
TRACE_OUT = spec.get("trace_out")

# Utility constants — kept in sync with the plugins (same values as exp2 / exp4).
LAMBDA = 0.999
AGENT_SPEED = 0.5
ALPHA = 1

import importlib
import time as _time
from collections import deque

import numpy as np
import pygame as _pg
from scipy.spatial.distance import cdist

sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
from platforms.pygame.base_agent import BaseAgent
from platforms.pygame.bt_runner import BTRunner
from platforms.pygame.utils_pygame import snapshot_message

sim = sim_module.Sim(config)

lx, ly = spec.get("leader_position", [700, 500])
for _a in sim.agents:
    if _a.type == "Leader":
        _a.position = _pg.math.Vector2(lx, ly)

bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)

followers = [a for a in sim.agents if a.type == "Follower"]
leaders = [a for a in sim.agents if a.type == "Leader"]



def follower_graph_connected():
    """True iff the followers (leader excluded) form one connected component at the follower radius."""
    r = types["Follower"]["communication_radius"]
    if r <= 0 or len(followers) <= 1:
        return True
    pos = np.array([[a.position.x, a.position.y] for a in followers])
    adj = cdist(pos, pos) <= r
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for j in np.where(adj[i])[0]:
            if j not in seen:
                seen.add(int(j))
                stack.append(int(j))
    return len(seen) == len(followers)


INITIALLY_CONNECTED = follower_graph_connected()

_history = deque(maxlen=DELAY + 1)


async def step_delayed():
    """BTRunner.step with the peer-message snapshot taken DELAY ticks ago.

    Connectivity is still evaluated on current positions; only the content of the
    messages is old. DELAY = 0 never reaches this function (BTRunner.step is used).
    """
    agents = bt_runner.agents
    positions = np.array([[a.position.x, a.position.y] for a in agents])
    BaseAgent._tick_dist_sq = cdist(positions, positions, 'sqeuclidean')
    BaseAgent._tick_agents = agents
    BaseAgent._tick_agent_index = {a.agent_id: i for i, a in enumerate(agents)}
    _history.append({a.agent_id: snapshot_message(a.message_to_share) for a in agents})
    BaseAgent._tick_message_snapshot = _history[0]
    for agent in agents:
        await agent.run_tree()


def _belief_of(agent):
    """What the follower's plugin believes: GRAPE coalitions / CBBA winners (None for the others)."""
    dm = getattr(agent, "decision_maker", None)
    part = getattr(dm, "partition", None)
    if isinstance(part, dict):
        return {str(tid): sorted(str(m) for m in members) for tid, members in part.items() if members}
    winners = getattr(dm, "z", None)   # CBBA: winning agent per task
    if isinstance(winners, dict):
        return {str(tid): str(w) for tid, w in winners.items() if w is not None}
    return None


def trace_record(n):
    """One per-tick record for the trace (see the module docstring)."""
    leader_pos = leaders[0].position if leaders else None
    rec = {"tick": n, "followers": {}, "tasks": {}, "plan": None}
    for a in followers:
        plan = (a.blackboard.get("_latest_central_plan") or {})
        alloc = (plan.get("task_allocations") or {}).get(a.agent_id, [])
        rec["followers"][str(a.agent_id)] = {
            "x": round(a.position.x, 2), "y": round(a.position.y, 2),
            "d": round(a.position.distance_to(leader_pos), 2) if leader_pos is not None else None,
            "cen": any(m.get("type") == "Leader" for m in a.messages_received),
            "hears": sorted(str(o.agent_id) for o in a.agents_nearby if o.type != "Leader"),
            "task": None if a.assigned_task_id is None else str(a.assigned_task_id),
            "bundle": [str(getattr(t, "task_id", t)) for t in (a.planned_tasks or [])],
            "plan_task": None if not alloc else str(alloc[0]),
            "belief": _belief_of(a),
        }
    for t in sim.tasks:
        if not t.completed:
            rec["tasks"][str(t.task_id)] = [round(t.position.x, 1), round(t.position.y, 1), round(float(t.amount), 2)]
    if leaders:
        plan = leaders[0].blackboard.get("central_plan") or {}
        rec["plan"] = {str(k): [str(x) for x in v] for k, v in (plan.get("task_allocations") or {}).items()}
    return rec


def payload_size(obj):
    """Size of an outbox in scalar fields (numbers / strings / ids).

    Agent and Task objects embedded in a message count as three fields (id, x, y),
    which is what a real message would have to carry for them.
    """
    if isinstance(obj, dict):
        return sum(payload_size(v) for v in obj.values())
    if isinstance(obj, (list, tuple, set)):
        return sum(payload_size(v) for v in obj)
    if hasattr(obj, 'task_id') or hasattr(obj, 'agent_id'):
        return 3
    return 1


async def run():
    n = 0
    decision_phase_end = None
    wall_start = _time.perf_counter()

    seen_completed = set()
    prev_assigned = {a.agent_id: None for a in followers}
    completion_events = []

    dup_ticks = 0          # ticks on which some task is the primary of >= 2 followers
    range_crossings = 0    # followers entering or leaving the leader's range (regime switches)
    # chattering (2026-10-05): a follower's crossings less than CHAT_GAP ticks apart form a chain; a chain of
    # CHAT_MIN or more crossings is one episode. Reported: crossings inside episodes and the ticks they span.
    CHAT_GAP, CHAT_MIN = 10, 4
    cross_ticks = {a.agent_id: [] for a in followers}
    leader_pos = leaders[0].position if leaders else None
    r_leader = float(types["Leader"]["communication_radius"])
    inside = {a.agent_id: (leader_pos is not None and a.position.distance_to(leader_pos) <= r_leader) for a in followers}
    dup_task_ticks = 0     # sum over ticks of the number of such tasks
    idle_ticks = 0         # sum over ticks of followers without a primary task
    comm_samples = 0
    comm_follower = 0.0    # summed payload of all follower outboxes
    comm_leader = 0.0      # payload of the leader outbox
    # What every follower does on every tick (one category each; see the module docstring).
    def allocation_of(a):
        return (tuple(getattr(t, 'task_id', t) for t in (a.planned_tasks or [])), a.assigned_task_id)
    prev_distance = {a.agent_id: float(a.distance_moved) for a in followers}
    prev_work = {a.agent_id: float(a.task_amount_done) for a in followers}
    prev_allocation = {a.agent_id: allocation_of(a) for a in followers}
    executing_ticks = moving_ticks = still_converging_ticks = still_with_task_ticks = still_no_task_ticks = 0
    team_decision_ticks = 0

    step = step_delayed if DELAY > 0 else bt_runner.step
    trace_f = open(TRACE_OUT, "w") if TRACE_OUT else None

    while sim.running and not sim.mission_completed and n < MAX_TICKS:
        await step()
        sim.update_simulation()
        n += 1
        if trace_f is not None:
            trace_f.write(json.dumps(trace_record(n)) + "\n")
        if decision_phase_end is None:
            if any(getattr(a, "distance_moved", 0) > 1e-9 for a in followers):
                decision_phase_end = n

        claims = {}
        for a in followers:
            if leader_pos is not None:
                now_inside = a.position.distance_to(leader_pos) <= r_leader
                if now_inside != inside[a.agent_id]:
                    range_crossings += 1
                    inside[a.agent_id] = now_inside
                    cross_ticks[a.agent_id].append(n)
            tid = a.assigned_task_id
            if tid is None:
                idle_ticks += 1
            else:
                claims[tid] = claims.get(tid, 0) + 1
        active = False
        for a in followers:
            work, dist, alloc = float(a.task_amount_done), float(a.distance_moved), allocation_of(a)
            if work > prev_work[a.agent_id] + 1e-12:
                executing_ticks += 1
                active = True
            elif dist > prev_distance[a.agent_id] + 1e-9:
                moving_ticks += 1
                active = True
            elif a.assigned_task_id is not None:
                still_converging_ticks += 1
                still_with_task_ticks += 1
            elif alloc != prev_allocation[a.agent_id]:
                still_converging_ticks += 1
            else:
                still_no_task_ticks += 1
            prev_work[a.agent_id], prev_distance[a.agent_id], prev_allocation[a.agent_id] = work, dist, alloc
        if not active:
            team_decision_ticks += 1
        dups = sum(1 for c in claims.values() if c > 1)
        if dups:
            dup_ticks += 1
            dup_task_ticks += dups

        if COMM_EVERY and n % COMM_EVERY == 0:
            comm_samples += 1
            comm_follower += sum(payload_size(a.message_to_share) for a in followers)
            comm_leader += sum(payload_size(a.message_to_share) for a in leaders)

        for task in sim.tasks:
            if task.completed and task.task_id not in seen_completed:
                contributors = [a for a in followers
                                if a.assigned_task_id == task.task_id
                                or prev_assigned.get(a.agent_id) == task.task_id]
                coalition_size = max(len(contributors), 1)
                for a in contributors:
                    completion_events.append((float(a.distance_moved), coalition_size))
                seen_completed.add(task.task_id)
        for a in followers:
            prev_assigned[a.agent_id] = a.assigned_task_id

    if trace_f is not None:
        trace_f.close()
    chat_crossings = chat_ticks = chat_episodes = 0
    for ticks_of_a in cross_ticks.values():
        chain = []
        for t in ticks_of_a + [None]:
            if t is not None and chain and t - chain[-1] < CHAT_GAP:
                chain.append(t)
                continue
            if len(chain) >= CHAT_MIN:
                chat_episodes += 1
                chat_crossings += len(chain)
                chat_ticks += chain[-1] - chain[0] + 1
            chain = [t] if t is not None else []
    team_utility = sum((LAMBDA ** (d / AGENT_SPEED)) / (c ** ALPHA) for d, c in completion_events)
    payload = {
        "ticks": n,
        "mission_completed": bool(sim.mission_completed),
        "mission_completion_time": float(sim.simulation_time),
        "decision_phase_ticks": decision_phase_end,
        "total_distance_moved": float(sum(a.distance_moved for a in followers)),
        "team_utility": float(team_utility),
        "tasks_completed": len(seen_completed),
        "n_followers": len(followers),
        "n_tasks": len(sim.tasks),
        "follower_graph_connected": int(INITIALLY_CONNECTED),
        "dup_tick_fraction": dup_ticks / n if n else 0.0,
        "dup_tasks_per_tick": dup_task_ticks / n if n else 0.0,
        "idle_fraction": idle_ticks / (n * len(followers)) if n and followers else 0.0,
        "executing_fraction": executing_ticks / (n * len(followers)) if n and followers else 0.0,
        "moving_fraction": moving_ticks / (n * len(followers)) if n and followers else 0.0,
        "still_converging_fraction": still_converging_ticks / (n * len(followers)) if n and followers else 0.0,
        "still_with_task_fraction": still_with_task_ticks / (n * len(followers)) if n and followers else 0.0,
        "still_no_task_fraction": still_no_task_ticks / (n * len(followers)) if n and followers else 0.0,
        "team_decision_ticks": team_decision_ticks,
        "range_crossings": range_crossings,
        "chattering_crossings": chat_crossings,
        "chattering_episodes": chat_episodes,
        "chattering_fraction": chat_ticks / (n * len(followers)) if n and followers else 0.0,
        "comm_follower_per_tick": comm_follower / comm_samples if comm_samples else None,
        "comm_leader_per_tick": comm_leader / comm_samples if comm_samples else None,
        "wall_clock_seconds": float(_time.perf_counter() - wall_start),
    }
    print("RESULT_JSON:" + json.dumps(payload))


asyncio.run(run())
