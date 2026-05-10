"""Exp 3 — Boundary Conflict 4-case ablation (Sec IV-C of the paper).

Static-mode snapshot experiment that ablates the two proposed mesh
mechanisms (RelayDecMessages × ForwardCenAllocation) independently:

  baseline     — Relay OFF, Forward OFF  (bt_follower_static.xml)
  relay_only   — Relay ON,  Forward OFF  (bt_follower_static_relay_only.xml)
  forward_only — Relay OFF, Forward ON   (bt_follower_static_forward_only.xml)
  full         — Relay ON,  Forward ON   (bt_follower_static_full.xml)

Demonstrates that:
  1. With a small Leader.communication_radius (boundary exists), in-range
     followers apply the leader's broadcast while out-of-range followers
     run dec MRTA. Without the proposed mesh mechanisms, the two groups
     can claim overlapping tasks → conflicts.
  2. Adding RelayDecMessages bridges fragmented dec clusters via cen.
  3. Adding ForwardCenAllocation propagates the leader's central plan
     through dec→dec chains so out-of-range followers can also avoid
     cen-claimed tasks.

We measure conflict counts at static-convergence:
  - `primary_unclaimed`: tasks no follower's primary `assigned_task_id` matches
  - `primary_overclaimed`: tasks claimed by ≥2 followers' primary
  - `bundle_overclaimed`: tasks appearing in ≥2 followers' bundles (CBBA only)

Run from project root (autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp3_boundary_conflicts.py

CLI:
    --seeds=N    number of seeds (default 10)
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

# === Experiment parameters (edit before re-run) ============================
LEADER_RADIUS = 500            # override Leader.communication_radius
FOLLOWER_RADIUS = 500          # follower mesh radius — paired with a per-seed
                               # connectivity precondition: seeds where the
                               # all-followers (cen + dec, leader excluded)
                               # union mesh fragments at this radius are
                               # SKIPPED. This isolates the algorithm/mesh
                               # mechanism contribution from topology luck.
LEADER_POSITION = (700, 500)   # force leader to map center (boundary visibility)

# Per-algo agent/task density overrides (Exp 3-only — yaml files unchanged).
# Increasing follower count densifies the mesh so more seeds pass the
# connectivity precondition while keeping the boundary effect informative.
ALGO_OVERRIDES = {
    'cbba':      {'follower_qty': 15, 'task_qty': 60, 'max_tasks_per_agent': 4},
    'hungarian': {'follower_qty': 15, 'task_qty': 15},
}
ALGOS = {
    'cbba':      'configs/static/cbba/cenwrapper_cbba.yaml',
    'hungarian': 'configs/static/hungarian/cenwrapper_hungarian.yaml',
    # GRAPE excluded — coalition formation legitimately allows multi-allocation
}
CONDITIONS = {
    # 4-case ablation (Relay × Forward)
    # Relay   = RelayDecMessages (cen) + UnpackRelayedMessages (dec)
    # Forward = ForwardCenAllocation (both branches)
    'baseline':     'bt_follower_static.xml',              # Relay OFF, Forward OFF
    'relay_only':   'bt_follower_static_relay_only.xml',   # Relay ON,  Forward OFF
    'forward_only': 'bt_follower_static_forward_only.xml', # Relay OFF, Forward ON
    'full':         'bt_follower_static_full.xml',         # Relay ON,  Forward ON
}
DEFAULT_SEEDS = 10
MAX_TICKS = 50000
# ============================================================================

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
EXP_DIR = os.path.join(SCEN_ROOT, 'experiments')
DATA_DIR = os.path.join(EXP_DIR, 'data')
OUTPUT_CSV = os.path.join(DATA_DIR, 'exp3_boundary_results.csv')


CHILD_TEMPLATE = r'''
import os, sys, asyncio, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")

from core.utils import set_config
set_config(r"{path}")
from core.utils import config

# Override radii + follower BT XML + agent/task counts (Exp 3 density overrides).
config["agents"]["types"]["Leader"]["communication_radius"] = {leader_radius}
config["agents"]["types"]["Follower"]["communication_radius"] = {follower_radius}
config["agents"]["types"]["Follower"]["behavior_tree_xml"] = "{follower_bt}"
config["agents"]["types"]["Follower"]["quantity"] = {follower_qty}
config["tasks"]["quantity"] = {task_qty}
{max_tasks_override}

config["simulation"]["random_seed"] = {seed}
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {{}})
for k in ("save_gif", "save_timewise_result_csv", "save_agentwise_result_csv", "save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {{}})["enabled"] = False
config["simulation"]["mode"] = "static"
config["simulation"]["speed_up_factor"] = 1
config["simulation"]["static_timeout_sec"] = 30.0

import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
from platforms.pygame.bt_runner import BTRunner

sim = sim_module.Sim(config)

# Force leader to map center so leader.communication_radius creates a visible
# in/out boundary. Without this override, leader is randomly placed and may
# spawn at a corner where no follower is within radius.
import pygame as _pg
for _a in sim.agents:
    if _a.type == "Leader":
        _a.position = _pg.math.Vector2({leader_x}, {leader_y})

bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)


def count_conflicts(sim):
    followers = [a for a in sim.agents if a.type == "Follower"]
    all_task_ids = set(t.task_id for t in sim.tasks)

    # primary: agent.assigned_task_id (1 per agent)
    # bundle: union of primary + planned_tasks_id (CBBA bundle), so for Hungarian
    #         primary == bundle (agent has only the single assignment).
    primary_to_agents = {{}}
    bundle_to_agents = {{}}

    for a in followers:
        tid = getattr(a, "assigned_task_id", None)
        if tid is not None:
            primary_to_agents.setdefault(tid, []).append(a.agent_id)
            bundle_to_agents.setdefault(tid, []).append(a.agent_id)

        for t in (a.planned_tasks or []):
            ptid = t.task_id
            if ptid is not None and ptid != tid:
                bundle_to_agents.setdefault(ptid, []).append(a.agent_id)

    # primary_unclaimed for CBBA includes "queued in some bundle but not primary"
    # → not a conflict, just the bundle structure. Use bundle_unclaimed as the
    # meaningful "missed task" metric.
    primary_unclaimed = sum(1 for t in all_task_ids if t not in primary_to_agents)
    primary_overclaimed = sum(1 for t, ags in primary_to_agents.items() if len(ags) > 1)
    bundle_unclaimed = sum(1 for t in all_task_ids if t not in bundle_to_agents)
    bundle_overclaimed = sum(1 for t, ags in bundle_to_agents.items() if len(ags) > 1)

    return {{
        "n_followers": len(followers),
        "n_tasks": len(all_task_ids),
        "primary_unclaimed": primary_unclaimed,
        "primary_overclaimed": primary_overclaimed,
        "bundle_unclaimed": bundle_unclaimed,
        "bundle_overclaimed": bundle_overclaimed,
        "primary_total_conflicts": primary_unclaimed + primary_overclaimed,
        "bundle_total_conflicts": bundle_unclaimed + bundle_overclaimed,
    }}


async def run():
    n = 0
    while sim.running and n < {max_ticks}:
        await bt_runner.step()
        sim.update_simulation()
        n += 1
    payload = count_conflicts(sim)
    payload["ticks"] = n
    payload["mission_completed"] = bool(sim.mission_completed)
    print("RESULT_JSON:" + json.dumps(payload))


asyncio.run(run())
'''


def _algo_overrides(algo):
    ov = ALGO_OVERRIDES[algo]
    max_tasks = ov.get('max_tasks_per_agent')
    max_tasks_line = (
        f'config["decision_making"]["CBBA"]["max_tasks_per_agent"] = {max_tasks}'
        if max_tasks is not None else ''
    )
    return ov['follower_qty'], ov['task_qty'], max_tasks_line


def run_one(algo, yaml_rel, follower_bt, seed):
    follower_qty, task_qty, max_tasks_override = _algo_overrides(algo)
    code = CHILD_TEMPLATE.format(
        path=os.path.join(SCEN_ROOT, yaml_rel),
        leader_radius=LEADER_RADIUS,
        follower_radius=FOLLOWER_RADIUS,
        leader_x=LEADER_POSITION[0],
        leader_y=LEADER_POSITION[1],
        follower_bt=follower_bt,
        follower_qty=follower_qty,
        task_qty=task_qty,
        max_tasks_override=max_tasks_override,
        seed=seed,
        max_ticks=MAX_TICKS,
    )
    out = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, text=True, timeout=300,
        encoding='utf-8', errors='replace',
    )
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    return {'error': (out.stderr or '')[-1500:]}


# === Per-seed connectivity precondition ===================================
# Build the all-followers union mesh (cen + dec, leader excluded) using
# pairwise distance <= FOLLOWER_RADIUS, and check it forms a single
# connected component. Seeds where the mesh fragments are SKIPPED so the
# 4-case ablation isolates the algorithm/mechanism contribution from
# topology luck.

POSITIONS_TEMPLATE = r'''
import os, sys, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")
from core.utils import set_config
set_config(r"{path}")
from core.utils import config
config["agents"]["types"]["Leader"]["communication_radius"] = {leader_radius}
config["agents"]["types"]["Follower"]["communication_radius"] = {follower_radius}
config["agents"]["types"]["Follower"]["quantity"] = {follower_qty}
config["tasks"]["quantity"] = {task_qty}
config["simulation"]["random_seed"] = {seed}
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {{}})
for k in ("save_gif","save_timewise_result_csv","save_agentwise_result_csv","save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {{}})["enabled"] = False
config["simulation"]["mode"] = "static"
import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
sim = sim_module.Sim(config)
followers = [a for a in sim.agents if a.type == "Follower"]
print("RESULT_JSON:" + json.dumps([
    {{"id": a.agent_id, "x": a.position.x, "y": a.position.y}} for a in followers
]))
'''


def _follower_positions(algo, yaml_rel, seed):
    follower_qty, task_qty, _ = _algo_overrides(algo)
    code = POSITIONS_TEMPLATE.format(
        path=os.path.join(SCEN_ROOT, yaml_rel),
        leader_radius=LEADER_RADIUS,
        follower_radius=FOLLOWER_RADIUS,
        follower_qty=follower_qty,
        task_qty=task_qty,
        seed=seed,
    )
    out = subprocess.run([sys.executable, '-c', code],
                         capture_output=True, text=True, timeout=60,
                         encoding='utf-8', errors='replace')
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    return None


def _is_follower_mesh_connected(algo, yaml_rel, seed):
    """True iff all followers form one connected component at FOLLOWER_RADIUS."""
    fol = _follower_positions(algo, yaml_rel, seed)
    if fol is None or len(fol) <= 1:
        return True  # trivially connected (or treat as not informative)
    # Union-find over pairwise distance <= FOLLOWER_RADIUS
    parent = {f['id']: f['id'] for f in fol}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    r_sq = FOLLOWER_RADIUS ** 2
    for i in range(len(fol)):
        for j in range(i + 1, len(fol)):
            dx = fol[i]['x'] - fol[j]['x']
            dy = fol[i]['y'] - fol[j]['y']
            if dx * dx + dy * dy <= r_sq:
                ra, rb = find(fol[i]['id']), find(fol[j]['id'])
                if ra != rb:
                    parent[ra] = rb
    return len({find(f['id']) for f in fol}) == 1


FIELDNAMES = ['seed', 'algo', 'condition',
              'primary_unclaimed', 'primary_overclaimed',
              'bundle_unclaimed', 'bundle_overclaimed',
              'primary_total_conflicts', 'bundle_total_conflicts',
              'n_followers', 'n_tasks', 'ticks', 'mission_completed']


def append_rows(csv_path, rows):
    new_file = not os.path.exists(csv_path)
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def load_done_keys(csv_path):
    """Returns set of (seed, algo, condition) already present in CSV — for resume."""
    if not os.path.exists(csv_path):
        return set()
    done = set()
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add((int(row['seed']), row['algo'], row['condition']))
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=DEFAULT_SEEDS)
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    seeds = list(range(1, args.seeds + 1))

    done_keys = load_done_keys(OUTPUT_CSV)
    n_total = len(seeds) * len(ALGOS) * len(CONDITIONS)
    n_done = 0
    n_failed = 0
    n_skipped_topology = 0
    n_skipped_done = 0
    skipped_seeds = {algo: [] for algo in ALGOS}
    t0 = time.time()

    print(f'Exp 3 — up to {n_total} runs ({len(seeds)} seeds × {len(ALGOS)} algos × {len(CONDITIONS)} conditions)')
    print(f'        leader_radius={LEADER_RADIUS}, follower_radius={FOLLOWER_RADIUS}')
    print(f'        per-(seed, algo) precondition: all followers form one connected component')
    if done_keys:
        print(f'        {len(done_keys)} (seed, algo, condition) entries already in {OUTPUT_CSV} — will skip')
    print()

    # Outer loop = seed × algo (connectivity check applies to all 4 conditions
    # of that (seed, algo) pair). Skip the whole pair if mesh is fragmented.
    for seed in seeds:
        for algo, yaml_rel in ALGOS.items():
            # Resume short-circuit: if all 4 conditions are already done for this
            # (seed, algo), skip the topology check too — it would redundantly
            # discover an already-classified seed.
            all_conds_done = all(
                (seed, algo, cond_name) in done_keys for cond_name in CONDITIONS
            )
            if all_conds_done:
                n_skipped_done += len(CONDITIONS)
                continue

            if not _is_follower_mesh_connected(algo, yaml_rel, seed):
                n_skipped_topology += 1
                skipped_seeds[algo].append(seed)
                print(f'  [SKIP-TOPOLOGY] seed={seed} algo={algo}: '
                      f'follower mesh fragmented at R={FOLLOWER_RADIUS}', flush=True)
                continue

            for cond_name, follower_bt in CONDITIONS.items():
                if (seed, algo, cond_name) in done_keys:
                    n_skipped_done += 1
                    continue
                n_done += 1
                tag = f'[{n_done}/{n_total}] {algo}/{cond_name} seed={seed}'
                print(f'  {tag} ...', flush=True)
                t_start = time.time()
                result = run_one(algo, yaml_rel, follower_bt, seed)
                elapsed = time.time() - t_start

                if 'error' in result:
                    n_failed += 1
                    print(f'    ERROR ({elapsed:.1f}s): {result["error"][:200]}')
                    continue

                pu = result['primary_unclaimed']
                po = result['primary_overclaimed']
                bu = result['bundle_unclaimed']
                bo = result['bundle_overclaimed']
                ticks = result['ticks']
                mc = result['mission_completed']
                print(f'    OK ({elapsed:.1f}s) ticks={ticks} mc={mc} '
                      f'bundle_unclaimed={bu} bundle_overclaimed={bo}  '
                      f'(primary: u={pu} o={po})')

                row = {
                    'seed': seed, 'algo': algo, 'condition': cond_name,
                    'primary_unclaimed': pu,
                    'primary_overclaimed': po,
                    'bundle_unclaimed': bu,
                    'bundle_overclaimed': bo,
                    'primary_total_conflicts': pu + po,
                    'bundle_total_conflicts': bu + bo,
                    'n_followers': result['n_followers'],
                    'n_tasks': result['n_tasks'],
                    'ticks': ticks,
                    'mission_completed': mc,
                }
                append_rows(OUTPUT_CSV, [row])

    elapsed = time.time() - t0
    print(f'\nDone — {n_done - n_failed} ok, {n_failed} failed, '
          f'{n_skipped_done} skipped (already done), '
          f'{n_skipped_topology} (seed,algo) skipped (mesh fragmented) '
          f'({elapsed:.0f}s) → {OUTPUT_CSV}')
    for algo, sd in skipped_seeds.items():
        if sd:
            print(f'  skipped seeds [{algo}]: {sd}')


if __name__ == '__main__':
    main()
