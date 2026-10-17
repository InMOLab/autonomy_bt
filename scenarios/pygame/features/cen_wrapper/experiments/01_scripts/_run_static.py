"""Single static (allocation-snapshot) run of the experiments (robots do not move).

Generalises `_run_static_conflicts.py`: every override is optional, a team without a leader is
accepted, messages can be delayed, and the run can be terminated on ticks instead of wall-clock
time. Run from the project root (autonomy_bt/); normally invoked by `_campaign.py`.

Prints `RESULT_JSON:{...}`.

Spec keys (argv[1], JSON; all optional except `yaml` and `seed`):
    yaml, seed
    leader_radius, follower_radius   communication radii (default: the yaml's; a leader radius of
                                     0 is replaced by 0.1 because pygame treats <= 0 as "global")
    leader_bt, follower_bt           BT xml files in the scenario folder (default: the yaml's)
    follower_qty, task_qty, max_tasks_per_agent
    leader_position                  [x, y] (default [700, 500], the arena centre)
    termination                      "wallclock" (default): the simulator's own static rule —
                                     allocation unchanged for 1 s of real time after a 1 s
                                     warm-up, 30 s cap — as in Exp 1 / Exp 3.
                                     "ticks": stop once the allocation has not changed for
                                     `stable_ticks` ticks (default 300), or after `max_ticks`
                                     (default 6000). Independent of machine load.
    delay_ticks                      extra message delay in BT ticks (default 0)
    cbba_bundle_reset                "none" (default, original CBBA) or "full" (CBBA with Full Bundle Reset)

Payload:
    cen_cen, cen_dec, dec_dec_same, dec_dec_split, overclaimed, unclaimed
                         tasks claimed by >= 2 followers, by who claims them (definitions in
                         `_run_static_conflicts.py`), their total, and tasks nobody claims
    allocation           "<follower>:<task>-<task>|..." in follower-id order (CBBA: path order)
    team_utility         sum over (follower, task) of lambda^(tau/v) / |C|^alpha, as in Exp 1
    path_length          sum over followers of the length of the path through their tasks
    ticks, last_change_tick, converged
                         ticks run, tick of the last change of `allocation`, and whether the
                         run ended because the allocation was stable (not on a cap)
    n_cen, n_dec, n_dec_components, follower_graph_connected
    team_graph_connected   every follower reaches every other one in the team's communication graph,
                           possibly through the leader (follower-follower links within R_f, leader-follower
                           links within R_L; the scenario's link rule)
    comm_to_convergence, comm_per_tick_to_convergence
                           summed outbox payload of all robots (as in `_run_single.py`) over ticks
                           1..last_change_tick, and per tick
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

TERMINATION = spec.get("termination", "wallclock")
STABLE_TICKS = int(spec.get("stable_ticks", 300))
MAX_TICKS = int(spec.get("max_ticks", 6000 if TERMINATION == "ticks" else 50000))
DELAY = int(spec.get("delay_ticks", 0))

config["simulation"]["random_seed"] = int(spec["seed"])
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {})
for k in ("save_gif", "save_timewise_result_csv", "save_agentwise_result_csv", "save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {})["enabled"] = False
config["simulation"]["mode"] = "static"
config["simulation"]["speed_up_factor"] = 1
if TERMINATION == "ticks":
    config["simulation"]["static_auto_terminate"] = False
else:
    config["simulation"]["static_timeout_sec"] = 30.0

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
leader = next((a for a in sim.agents if a.type == "Leader"), None)
if leader is not None:
    lx, ly = spec.get("leader_position", [700, 500])
    leader.position = _pg.math.Vector2(lx, ly)

bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)

followers = sorted((a for a in sim.agents if a.type == "Follower"), key=lambda f: f.agent_id)
R_L = float(types["Leader"]["communication_radius"])
R_F = float(types["Follower"]["communication_radius"])

# Utility constants, as in exp1_static_equivalence.py.
def _cfg(key, default):
    for section in ("CBBA", "GRAPE", "Hungarian"):
        v = config.get("decision_making", {}).get(section, {}).get(key)
        if v is not None:
            return v
    return default

LAMBDA = _cfg("task_reward_discount_factor", 0.999)
AGENT_SPEED = 0.5
ALPHA = config.get("decision_making", {}).get("GRAPE", {}).get("social_inhibition_factor", 0)

_history = deque(maxlen=DELAY + 1)


async def step_delayed():
    """BTRunner.step with the peer-message snapshot taken DELAY ticks ago (as in `_run_single.py`)."""
    agents = bt_runner.agents
    positions = np.array([[a.position.x, a.position.y] for a in agents])
    BaseAgent._tick_dist_sq = cdist(positions, positions, 'sqeuclidean')
    BaseAgent._tick_agents = agents
    BaseAgent._tick_agent_index = {a.agent_id: i for i, a in enumerate(agents)}
    _history.append({a.agent_id: snapshot_message(a.message_to_share) for a in agents})
    BaseAgent._tick_message_snapshot = _history[0]
    for agent in agents:
        await agent.run_tree()


def tasks_of(a):
    """The follower's tasks: its path if the plugin plans several (CBBA), else its single task."""
    planned = [t for t in (a.planned_tasks or []) if t.task_id is not None]
    if planned:
        return planned
    if a.assigned_task_id is None:
        return []
    return [t for t in sim.tasks if t.task_id == a.assigned_task_id]


def allocation_signature():
    return "|".join(f"{a.agent_id}:" + "-".join(str(t.task_id) for t in tasks_of(a)) for a in followers)


def payload_size(obj):
    """Size of an outbox in scalar fields (numbers / strings / ids); robot and task objects count as three
    fields (id, x, y). Same as `_run_single.py`."""
    if isinstance(obj, dict):
        return sum(payload_size(v) for v in obj.values())
    if isinstance(obj, (list, tuple, set)):
        return sum(payload_size(v) for v in obj)
    if hasattr(obj, 'task_id') or hasattr(obj, 'agent_id'):
        return 3
    return 1


def team_graph_connected():
    """True iff all followers are in one component of the graph followers + leader (follower-follower
    links within R_F, leader-follower links within R_L; a leader radius of 0 means no leader)."""
    nodes = list(followers) + ([leader] if leader is not None and R_L > ZERO_SUBSTITUTE else [])
    if not followers:
        return True
    def linked(a, b):
        r = R_L if (a is leader or b is leader) else R_F
        return a.position.distance_to(b.position) <= r
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for j in range(len(nodes)):
            if j not in seen and linked(nodes[i], nodes[j]):
                seen.add(j)
                stack.append(j)
    return all(k in seen for k in range(len(followers)))


def components(agents):
    """Map agent_id -> component index in the communication graph restricted to `agents`."""
    if not agents:
        return {}
    pos = np.array([[a.position.x, a.position.y] for a in agents])
    adj = cdist(pos, pos) <= R_F
    comp = [-1] * len(agents)
    c = 0
    for s in range(len(agents)):
        if comp[s] != -1:
            continue
        comp[s], stack = c, [s]
        while stack:
            i = stack.pop()
            for j in np.where(adj[i])[0]:
                if comp[j] == -1:
                    comp[j] = c
                    stack.append(int(j))
        c += 1
    return {a.agent_id: comp[k] for k, a in enumerate(agents)}


def summarise():
    is_cen = {a.agent_id: leader is not None and a.position.distance_to(leader.position) <= R_L
              for a in followers}
    dec_comp = components([a for a in followers if not is_cen[a.agent_id]])
    union_comp = components(followers)

    claims = {}
    for a in followers:
        tids = {t.task_id for t in tasks_of(a)}
        if a.assigned_task_id is not None:
            tids.add(a.assigned_task_id)
        for tid in tids:
            claims.setdefault(tid, []).append(a.agent_id)

    counts = {"cen_cen": 0, "cen_dec": 0, "dec_dec_same": 0, "dec_dec_split": 0}
    for tid, ags in claims.items():
        if len(ags) < 2:
            continue
        cen = [g for g in ags if is_cen[g]]
        dec = [g for g in ags if not is_cen[g]]
        if cen and dec:
            counts["cen_dec"] += 1
        elif cen:
            counts["cen_cen"] += 1
        elif len({dec_comp[g] for g in dec}) == 1:
            counts["dec_dec_same"] += 1
        else:
            counts["dec_dec_split"] += 1

    coalition_size = {}
    for a in followers:
        for t in tasks_of(a):
            coalition_size[t.task_id] = coalition_size.get(t.task_id, 0) + 1
    team_utility = 0.0
    path_length = 0.0
    for a in followers:
        pos = _pg.Vector2(a.position)
        tau = 0.0
        for t in tasks_of(a):
            tpos = _pg.Vector2(t.position)
            tau += pos.distance_to(tpos)
            team_utility += (LAMBDA ** (tau / AGENT_SPEED)) / (max(coalition_size.get(t.task_id, 1), 1) ** ALPHA)
            pos = tpos
        path_length += tau

    all_task_ids = {t.task_id for t in sim.tasks}
    return {
        **counts,
        "overclaimed": sum(counts.values()),
        "unclaimed": sum(1 for t in all_task_ids if t not in claims),
        "allocation": allocation_signature(),
        "team_utility": float(team_utility),
        "path_length": float(path_length),
        "n_cen": sum(is_cen.values()),
        "n_dec": len(followers) - sum(is_cen.values()),
        "n_dec_components": len(set(dec_comp.values())),
        "follower_graph_connected": int(len(set(union_comp.values())) == 1),
        "team_graph_connected": int(team_graph_connected()),
    }


async def run():
    step = step_delayed if DELAY > 0 else bt_runner.step
    n = 0
    last_change_tick = 0
    previous = None
    converged = False
    wall_start = _time.perf_counter()
    comm_cumulative = [0.0]   # comm_cumulative[t] = summed payload of all outboxes over ticks 1..t
    while sim.running and n < MAX_TICKS:
        await step()
        sim.update_simulation()
        n += 1
        comm_cumulative.append(comm_cumulative[-1] + sum(payload_size(a.message_to_share) for a in sim.agents))
        current = allocation_signature()
        if current != previous:
            previous = current
            last_change_tick = n
        elif TERMINATION == "ticks" and n - last_change_tick >= STABLE_TICKS:
            converged = True
            break
    if TERMINATION != "ticks":
        # The simulator stops the run itself, either on a stable allocation or on its 30 s cap.
        converged = (not sim.running) and (_time.perf_counter() - wall_start) < 29.0
    payload = summarise()
    payload.update({"ticks": n, "last_change_tick": last_change_tick, "converged": int(converged),
                    "comm_to_convergence": float(comm_cumulative[last_change_tick]),
                    "comm_per_tick_to_convergence": float(comm_cumulative[last_change_tick] / last_change_tick) if last_change_tick else 0.0})
    print("RESULT_JSON:" + json.dumps(payload))


asyncio.run(run())
