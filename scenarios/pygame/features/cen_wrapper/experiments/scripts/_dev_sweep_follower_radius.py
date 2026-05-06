"""Dev tool — sweep FOLLOWER_RADIUS to find where forward_only alone fails.

Goal: discover a FOLLOWER_RADIUS value at which the dec mesh is fragmented
enough that the cen plan (forwarded by ForwardCenAllocation alone) cannot
reach all dec clusters — so the *full* mesh (Relay ON + Forward ON) is
required to drive conflicts to zero.

Iterates over (FOLLOWER_RADIUS, condition, algo, seed) and records
bundle_unclaimed + bundle_overclaimed at static convergence.

Usage (from project root, autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/_dev_sweep_follower_radius.py
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/_dev_sweep_follower_radius.py --seeds=5
"""
import argparse
import json
import os
import subprocess
import sys
import time

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Reuse exp3 setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp3_boundary_conflicts import (
    CHILD_TEMPLATE, ALGOS, CONDITIONS, LEADER_RADIUS, LEADER_POSITION,
    SCEN_ROOT, MAX_TICKS,
)


# Radii small enough to fragment the dec mesh into ≥2 components, but not so
# small that any-cluster also disconnects. Map ~1400×1000, 30 agents → mean
# nearest-neighbour distance ~150–250, so radii below ~300 risk full disconnect.
SWEEP_RADII = [800, 700, 600, 500, 450, 400, 350]


def run_one(yaml_rel, follower_bt, seed, follower_radius):
    code = CHILD_TEMPLATE.format(
        path=os.path.join(SCEN_ROOT, yaml_rel),
        leader_radius=LEADER_RADIUS,
        follower_radius=follower_radius,
        leader_x=LEADER_POSITION[0],
        leader_y=LEADER_POSITION[1],
        follower_bt=follower_bt,
        seed=seed,
        max_ticks=MAX_TICKS,
    )
    # 10s per run — fast static convergence is normal; anything slower means
    # the mesh is fragmenting badly enough to be uninteresting for this sweep.
    try:
        out = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
    except subprocess.TimeoutExpired:
        return {'error': 'subprocess timeout (10s) — likely non-convergent'}
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    return {'error': (out.stderr or '')[-500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=3)
    args = ap.parse_args()

    seeds = list(range(1, args.seeds + 1))
    total = len(SWEEP_RADII) * len(ALGOS) * len(CONDITIONS) * len(seeds)
    print(f'Sweep — {total} runs (radii={SWEEP_RADII}, algos={list(ALGOS)}, '
          f'conditions={list(CONDITIONS)}, seeds={seeds})\n')

    # results[radius][algo][cond] = list of (b_unclaimed, b_overclaimed)
    results = {r: {a: {c: [] for c in CONDITIONS} for a in ALGOS} for r in SWEEP_RADII}

    n_done = 0
    t0 = time.time()
    for radius in SWEEP_RADII:
        for algo, yaml_rel in ALGOS.items():
            for cond_name, follower_bt in CONDITIONS.items():
                for seed in seeds:
                    n_done += 1
                    res = run_one(yaml_rel, follower_bt, seed, radius)
                    if 'error' in res:
                        print(f'  [{n_done}/{total}] r={radius} {algo}/{cond_name} '
                              f'seed={seed} ERROR: {res["error"][:120]}', flush=True)
                        continue
                    bu = res['bundle_unclaimed']
                    bo = res['bundle_overclaimed']
                    results[radius][algo][cond_name].append((bu, bo))
                    print(f'  [{n_done}/{total}] r={radius} {algo}/{cond_name} '
                          f'seed={seed}: u={bu} o={bo}', flush=True)

    elapsed = time.time() - t0
    print(f'\n--- Summary ({elapsed:.0f}s) — mean (bundle_unclaimed + bundle_overclaimed) ---\n')
    cond_keys = list(CONDITIONS.keys())
    header = f'{"radius":>8} | {"algo":>10} | ' + ' | '.join(f'{c:>14}' for c in cond_keys)
    print(header)
    print('-' * len(header))
    for radius in SWEEP_RADII:
        for algo in ALGOS:
            row_cells = []
            for cond in cond_keys:
                vals = results[radius][algo][cond]
                if vals:
                    mean_total = sum(bu + bo for bu, bo in vals) / len(vals)
                    row_cells.append(f'{mean_total:>14.2f}')
                else:
                    row_cells.append(f'{"-":>14}')
            print(f'{radius:>8} | {algo:>10} | ' + ' | '.join(row_cells))

    print('\nGoal: pick a radius where `forward_only` mean > 0 but `full` mean ≈ 0.')


if __name__ == '__main__':
    main()
