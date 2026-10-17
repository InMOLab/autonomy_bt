"""Parallel, resumable campaign driver of the experiments.

Each run is one `_run_single.py` subprocess. Results are appended to a long-format CSV
(one row per metric) as runs finish, so an interrupted campaign can be resumed: runs
whose key is already in the CSV are skipped.
"""
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
EXP_DIR = os.path.join(SCEN_ROOT, 'experiments')
DATA_DIR = os.path.join(EXP_DIR, '02_data')
RUN_SINGLE = os.path.join(EXP_DIR, '01_scripts', '_run_single.py')

# Mission-level metrics written to the CSV (keys of the `_run_single.py` payload).
METRICS = [
    'mission_completed', 'mission_completion_time', 'ticks', 'decision_phase_ticks',
    'total_distance_moved', 'team_utility', 'tasks_completed', 'follower_graph_connected',
    'dup_tick_fraction', 'dup_tasks_per_tick', 'idle_fraction', 'range_crossings',
    'chattering_crossings', 'chattering_episodes', 'chattering_fraction',   # boundary chattering (2026-10-05)
    'comm_follower_per_tick', 'comm_leader_per_tick', 'wall_clock_seconds',
    # what every follower does on every tick (see _run_single.py): fractions of robot-ticks, team decision-only ticks
    'executing_fraction', 'moving_fraction', 'still_converging_fraction', 'still_with_task_fraction',
    'still_no_task_fraction', 'team_decision_ticks',
]


def run_single(spec, timeout=900, runner=None):
    # One BLAS/OpenMP thread per run: the runs are parallelised at process level, and
    # multi-threaded numpy in every child oversubscribes the CPU.
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', PYTHONIOENCODING='utf-8',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    out = subprocess.run([sys.executable, runner or RUN_SINGLE, json.dumps(spec)],
                         capture_output=True, text=True, timeout=timeout,
                         encoding='utf-8', errors='replace', env=env)
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    return {'error': (out.stderr or '')[-1500:]}


def _load_done(csv_path, key_fields):
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        return {tuple(row[k] for k in key_fields) for row in csv.DictReader(f)}


def run_campaign(runs, key_fields, csv_name, workers=None, runner=None, metrics=None):
    """`runs`: list of (key_dict, spec). `key_fields`: CSV key columns, in order.
    `runner` / `metrics` default to `_run_single.py` and its mission-level METRICS.

    CSV columns: key_fields + ['metric_name', 'value'].
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    csv_path = os.path.join(DATA_DIR, csv_name)
    fieldnames = list(key_fields) + ['metric_name', 'value']
    done = _load_done(csv_path, key_fields)
    todo = [(k, s) for k, s in runs if tuple(str(k[f]) for f in key_fields) not in done]
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    print(f'{len(runs)} runs requested, {len(runs) - len(todo)} already in {csv_path}, '
          f'{len(todo)} to run with {workers} workers')

    new_file = not os.path.exists(csv_path)
    n_ok = n_fail = 0
    t0 = time.time()
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_single, s, 900, runner): k for k, s in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                key = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:  # timeout etc.
                    res = {'error': repr(e)}
                if 'error' in res:
                    n_fail += 1
                    print(f'  [FAIL] {key}: {res["error"][-300:]}')
                    continue
                n_ok += 1
                for m in (metrics or METRICS):
                    writer.writerow({**key, 'metric_name': m, 'value': res.get(m)})
                f.flush()
                if i % 50 == 0 or i == len(todo):
                    print(f'  {i}/{len(todo)} done ({time.time() - t0:.0f}s)')
    print(f'Done — {n_ok} ok, {n_fail} failed, {time.time() - t0:.0f}s → {csv_path}')
    return csv_path
