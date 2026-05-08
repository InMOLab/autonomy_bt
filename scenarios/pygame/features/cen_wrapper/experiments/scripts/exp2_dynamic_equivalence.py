"""Exp 2 — Dynamic Equivalence (Sec IV-A of the paper).

For each (algorithm, mode, seed) combination, runs the dynamic-global yaml
until mission_completed (or max_ticks safety cap), then captures:
  - mission completion time (sim seconds)
  - total distance moved (Σ over followers)
  - per-agent distance moved
  - per-agent task amount done

Goal: show that the static equivalence (Exp 1) carries over to dynamic
scenarios as *statistical* equivalence — wrapper / dec / baseline produce
mission- and agent-level metrics that pass equivalence tests (TOST).

Output: experiments/data/exp2_dynamic_results.csv with one row per
(seed, algo, mode, metric_name, value, agent_id) tuple. Mission-level
metrics use agent_id=-1.

Run from project root (autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp2_dynamic_equivalence.py

CLI:
    --seeds=N         number of seeds (default 3) — uses [1..N]
    --max-ticks=N     safety cap per run (default 50000)
"""
import argparse
import csv
import os
import subprocess
import sys
import time

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
EXP_DIR = os.path.join(SCEN_ROOT, 'experiments')
DATA_DIR = os.path.join(EXP_DIR, 'data')
OUTPUT_CSV = os.path.join(DATA_DIR, 'exp2_dynamic_results.csv')

# Utility constants — kept in sync with cen_grape / grape_deterministic /
# dec_hungarian / cbba / sga modules.
LAMBDA = 0.999
AGENT_SPEED = 0.5
ALPHA = 1  # GRAPE social_inhibition_factor (yaml). For CBBA/Hungarian
           # |C|=1 always so 1^alpha=1 regardless — α value only matters for GRAPE.


def compute_team_utility(events, algo):
    """Sum lambda^(d/v) / |C|^alpha across (agent, task) completion events.

    For CBBA / Hungarian: |C| = 1 always (single-agent assignments) so the
    coalition denominator collapses to 1 regardless of ALPHA.
    For GRAPE: |C| reflects coalition size at completion.
    """
    U = 0.0
    for ev in events:
        d = ev['distance_moved']
        c = max(ev.get('coalition_size', 1), 1)
        r = LAMBDA ** (d / AGENT_SPEED)
        U += r / (c ** ALPHA)
    return U

# (algo, mode) -> yaml path under SCEN_ROOT
YAMLS = {
    'cbba': {
        'dec':      'configs/dynamic/global/cbba/cbba.yaml',
        'wrapper':  'configs/dynamic/global/cbba/cenwrapper_cbba.yaml',
        'baseline': 'configs/dynamic/global/cbba/sga.yaml',
    },
    'grape': {
        'dec':      'configs/dynamic/global/grape/grape.yaml',
        'wrapper':  'configs/dynamic/global/grape/cenwrapper_grape.yaml',
        'baseline': 'configs/dynamic/global/grape/cen_grape.yaml',
    },
    'hungarian': {
        'dec':      'configs/dynamic/global/hungarian/dec_hungarian.yaml',
        'wrapper':  'configs/dynamic/global/hungarian/cenwrapper_hungarian.yaml',
        'baseline': 'configs/dynamic/global/hungarian/hungarian.yaml',
    },
}


CHILD_TEMPLATE = r'''
import os, sys, asyncio, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")

from core.utils import set_config
set_config(r"{path}")
from core.utils import config

config["simulation"]["random_seed"] = {seed}
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {{}})
for k in ("save_gif", "save_timewise_result_csv", "save_agentwise_result_csv", "save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {{}})["enabled"] = False
config["simulation"]["mode"] = "dynamic"
config["simulation"]["speed_up_factor"] = 1
config["simulation"]["max_simulation_time"] = 0  # let mission_completed terminate

import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
from platforms.pygame.bt_runner import BTRunner

sim = sim_module.Sim(config)
bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)


import time as _time
async def run():
    n = 0
    decision_phase_end = None
    decision_wall_end = None  # NEW: wall-clock at decision-phase boundary
    wall_start = _time.perf_counter()

    # Per-task-completion logging for utility-based performance metric.
    seen_completed = set()
    prev_assigned = {{a.agent_id: None for a in sim.agents if a.type == "Follower"}}
    completion_events = []

    while sim.running and not sim.mission_completed and n < {max_ticks}:
        await bt_runner.step()
        sim.update_simulation()
        n += 1
        if decision_phase_end is None:
            if any(getattr(a, "distance_moved", 0) > 1e-9
                   for a in sim.agents if a.type == "Follower"):
                decision_phase_end = n
                decision_wall_end = _time.perf_counter()

        # Detect newly-completed tasks; coalition = followers currently OR previously assigned to it.
        for task in sim.tasks:
            if task.completed and task.task_id not in seen_completed:
                contributors = [a for a in sim.agents
                                if a.type == "Follower"
                                and (a.assigned_task_id == task.task_id
                                     or prev_assigned.get(a.agent_id) == task.task_id)]
                coalition_size = max(len(contributors), 1)
                for a in contributors:
                    completion_events.append({{
                        "task_id": int(task.task_id),
                        "agent_id": int(a.agent_id),
                        "distance_moved": float(a.distance_moved),
                        "coalition_size": coalition_size,
                        "tick": n,
                    }})
                seen_completed.add(task.task_id)

        for a in sim.agents:
            if a.type == "Follower":
                prev_assigned[a.agent_id] = a.assigned_task_id

    wall_elapsed = _time.perf_counter() - wall_start
    movement_phase = (n - decision_phase_end) if decision_phase_end is not None else None
    decision_phase_wall = (decision_wall_end - wall_start) if decision_wall_end is not None else None
    movement_phase_wall = (wall_elapsed - decision_phase_wall) if decision_phase_wall is not None else None
    payload = {{
        "ticks": n,
        "mission_completed": bool(sim.mission_completed),
        "simulation_time": float(sim.simulation_time),
        "decision_phase_ticks": decision_phase_end,
        "movement_phase_ticks": movement_phase,
        "wall_clock_seconds": float(wall_elapsed),
        "decision_phase_wall_seconds": decision_phase_wall,
        "movement_phase_wall_seconds": movement_phase_wall,
        "per_agent": [
            {{
                "agent_id": int(a.agent_id),
                "distance_moved": float(a.distance_moved),
                "task_amount_done": float(a.task_amount_done),
            }}
            for a in sim.agents if a.type == "Follower"
        ],
        "completion_events": completion_events,
    }}
    print("RESULT_JSON:" + json.dumps(payload))


asyncio.run(run())
'''


def run_one(yaml_rel: str, seed: int, max_ticks: int) -> dict:
    code = CHILD_TEMPLATE.format(
        path=os.path.join(SCEN_ROOT, yaml_rel),
        seed=seed,
        max_ticks=max_ticks,
    )
    out = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, text=True, timeout=600,
        encoding='utf-8', errors='replace',
    )
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            import json
            return json.loads(line[len('RESULT_JSON:'):])
    return {'error': (out.stderr or '')[-1500:]}


FIELDNAMES = ['seed', 'algo', 'mode', 'metric_name', 'value', 'agent_id']


def load_done_keys(csv_path):
    """Returns set of (seed, algo, mode) tuples already present in CSV."""
    if not os.path.exists(csv_path):
        return set()
    done = set()
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add((int(row['seed']), row['algo'], row['mode']))
    return done


def append_rows(csv_path, rows):
    """Append rows to CSV, writing header if file is new."""
    new_file = not os.path.exists(csv_path)
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=3)
    parser.add_argument('--max-ticks', type=int, default=50000)
    args = parser.parse_args()

    seeds = list(range(1, args.seeds + 1))
    os.makedirs(DATA_DIR, exist_ok=True)

    done_keys = load_done_keys(OUTPUT_CSV)
    n_total = sum(1 for _ in YAMLS) * 3 * len(seeds)
    n_done_existing = len(done_keys)
    n_processed = 0
    n_skipped = 0
    n_failed = 0
    t0 = time.time()

    print(f'Exp 2 — target {n_total} runs ({len(seeds)} seeds × 3 modes × 3 algos)')
    if n_done_existing:
        print(f'        {n_done_existing} runs already in {OUTPUT_CSV} — will skip')
    print()

    for algo, modes in YAMLS.items():
        for mode, yaml_rel in modes.items():
            for seed in seeds:
                key = (seed, algo, mode)
                if key in done_keys:
                    n_skipped += 1
                    continue
                n_processed += 1
                tag = f'[{n_processed}] {algo}/{mode} seed={seed}'
                print(f'  {tag} ...', flush=True)
                t_start = time.time()
                result = run_one(yaml_rel, seed, args.max_ticks)
                elapsed = time.time() - t_start

                if 'error' in result:
                    n_failed += 1
                    print(f'    ERROR ({elapsed:.1f}s): {result["error"][:200]}')
                    continue

                ticks = result['ticks']
                mc = result['mission_completed']
                sim_time = result['simulation_time']
                dph = result.get('decision_phase_ticks')
                mph = result.get('movement_phase_ticks')
                wall = result.get('wall_clock_seconds', 0.0)
                dphw = result.get('decision_phase_wall_seconds')
                mphw = result.get('movement_phase_wall_seconds')
                per_agent = result['per_agent']
                completion_events = result.get('completion_events', [])
                total_dist = sum(a['distance_moved'] for a in per_agent)
                total_work = sum(a['task_amount_done'] for a in per_agent)

                # ── Team utility: Σ lambda^(d/v) / |C|^alpha across completions
                # ── (per (agent, task): distance at completion).
                team_utility = compute_team_utility(completion_events, algo)

                print(f'    OK ({elapsed:.1f}s) ticks={ticks} mc={mc} '
                      f'dph={dph} mph={mph} wall={wall:.1f}s '
                      f'dist={total_dist:.0f} work={total_work:.0f} '
                      f'U={team_utility:.3f}')

                rows = [
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'mission_completion_time',
                     'value': sim_time, 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'total_distance_moved',
                     'value': total_dist, 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'mission_completed',
                     'value': float(mc), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'decision_phase_ticks',
                     'value': float(dph) if dph is not None else float('nan'), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'movement_phase_ticks',
                     'value': float(mph) if mph is not None else float('nan'), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'wall_clock_seconds',
                     'value': float(wall), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'decision_phase_wall_seconds',
                     'value': float(dphw) if dphw is not None else float('nan'), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'movement_phase_wall_seconds',
                     'value': float(mphw) if mphw is not None else float('nan'), 'agent_id': -1},
                    {'seed': seed, 'algo': algo, 'mode': mode,
                     'metric_name': 'team_utility',
                     'value': float(team_utility), 'agent_id': -1},
                ]
                for a in per_agent:
                    rows.append({'seed': seed, 'algo': algo, 'mode': mode,
                                 'metric_name': 'per_agent_distance_moved',
                                 'value': a['distance_moved'], 'agent_id': a['agent_id']})
                    rows.append({'seed': seed, 'algo': algo, 'mode': mode,
                                 'metric_name': 'per_agent_task_amount_done',
                                 'value': a['task_amount_done'], 'agent_id': a['agent_id']})
                # Per-agent utility (sum of contributions for that agent)
                per_agent_util = {}
                for ev in completion_events:
                    contrib = (LAMBDA ** (ev['distance_moved'] / AGENT_SPEED)) / (ev['coalition_size'] ** ALPHA)
                    per_agent_util[ev['agent_id']] = per_agent_util.get(ev['agent_id'], 0.0) + contrib
                for aid, u in per_agent_util.items():
                    rows.append({'seed': seed, 'algo': algo, 'mode': mode,
                                 'metric_name': 'per_agent_utility',
                                 'value': float(u), 'agent_id': aid})

                # Append immediately — robust to crashes mid-run
                append_rows(OUTPUT_CSV, rows)

    elapsed = time.time() - t0
    print(f'\nDone — processed {n_processed}, skipped {n_skipped} (already done), failed {n_failed} '
          f'({elapsed:.0f}s)')


if __name__ == '__main__':
    main()
