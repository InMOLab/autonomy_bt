"""Cross-tabulate dec-internal connectivity vs forward_only zero-conflict.

For each Exp 3 seed:
  1. Re-create initial spawn (Sim init only, no BT step) so positions match
     what the actual experiment used.
  2. Classify followers: cen-cluster (within LEADER_RADIUS of forced
     leader position) vs dec (outside).
  3. Build a graph on dec followers with edges where pairwise distance
     <= FOLLOWER_RADIUS. Count connected components.
     - 1 component  → dec-internally-connected (relay arguably unnecessary)
     - >1 component → fragmented (relay needed to bridge dec segments via cen)
  4. Read exp3_boundary_results.csv → per (seed, algo) forward_only's
     bundle_total_conflicts.
  5. Print cross-tab to test the hypothesis: forward_only zero-conflict
     seeds == dec-internally-connected seeds.

Run:
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_check_dec_connectivity.py
"""
import argparse
import csv
import os
import subprocess
import sys

# Same setup as exp3_boundary_conflicts.py
LEADER_RADIUS = 400
FOLLOWER_RADIUS = 800
LEADER_POS = (700, 500)
SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
ALGO_YAML = {
    'cbba':      'configs/static/cbba/cenwrapper_cbba.yaml',
    'hungarian': 'configs/static/hungarian/cenwrapper_hungarian.yaml',
}
RESULTS_CSV = os.path.join(SCEN_ROOT, 'experiments/data/exp3_boundary_results.csv')

# Subprocess template to spawn Sim and dump follower positions for a single seed.
CHILD = r'''
import os, sys, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")
from core.utils import set_config
set_config(r"{path}")
from core.utils import config
config["agents"]["types"]["Leader"]["communication_radius"] = {leader_radius}
config["agents"]["types"]["Follower"]["communication_radius"] = {follower_radius}
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


def _follower_positions(yaml_rel, seed):
    code = CHILD.format(
        path=os.path.join(SCEN_ROOT, yaml_rel),
        leader_radius=LEADER_RADIUS,
        follower_radius=FOLLOWER_RADIUS,
        seed=seed,
    )
    out = subprocess.run([sys.executable, '-c', code],
                         capture_output=True, text=True, timeout=60,
                         encoding='utf-8', errors='replace')
    import json
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    raise RuntimeError(f'No positions for seed {seed}: {out.stderr[-300:]}')


def _connected_components(node_ids, edges):
    """Union-find."""
    parent = {n: n for n in node_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for a, b in edges:
        union(a, b)
    roots = {find(n) for n in node_ids}
    return len(roots)


def classify_seed(yaml_rel, seed):
    """Returns (n_dec, n_components, is_dec_connected)."""
    fol = _follower_positions(yaml_rel, seed)
    lx, ly = LEADER_POS
    dec = [
        f for f in fol
        if (f['x'] - lx) ** 2 + (f['y'] - ly) ** 2 > LEADER_RADIUS ** 2
    ]
    if len(dec) <= 1:
        return len(dec), len(dec), True  # 0 or 1 dec → trivially "connected"
    edges = []
    r_sq = FOLLOWER_RADIUS ** 2
    for i in range(len(dec)):
        for j in range(i + 1, len(dec)):
            dx = dec[i]['x'] - dec[j]['x']
            dy = dec[i]['y'] - dec[j]['y']
            if dx * dx + dy * dy <= r_sq:
                edges.append((dec[i]['id'], dec[j]['id']))
    ids = [d['id'] for d in dec]
    n_comp = _connected_components(ids, edges)
    return len(dec), n_comp, n_comp == 1


def load_forward_only(algo):
    """seed → bundle_total_conflicts for forward_only condition."""
    out = {}
    with open(RESULTS_CSV, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['algo'] != algo or row['condition'] != 'forward_only':
                continue
            out[int(row['seed'])] = int(row['bundle_total_conflicts'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=100)
    ap.add_argument('--algo', default='cbba', choices=list(ALGO_YAML))
    args = ap.parse_args()

    yaml_rel = ALGO_YAML[args.algo]
    forward_conflicts = load_forward_only(args.algo)

    print(f'algo={args.algo}  leader_R={LEADER_RADIUS}  follower_R={FOLLOWER_RADIUS}')
    print(f'{"seed":>4} | {"n_dec":>5} | {"n_comp":>6} | {"connected":>9} | '
          f'{"fwd_conflict":>12} | {"fwd_zero":>8}')
    print('-' * 70)

    # Counters for cross-tab
    cells = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
    rows = []

    for seed in range(1, args.seeds + 1):
        n_dec, n_comp, connected = classify_seed(yaml_rel, seed)
        c = forward_conflicts.get(seed)
        if c is None:
            continue
        fwd_zero = (c == 0)
        cells[(connected, fwd_zero)] += 1
        rows.append((seed, n_dec, n_comp, connected, c, fwd_zero))
        print(f'{seed:>4} | {n_dec:>5} | {n_comp:>6} | {str(connected):>9} | '
              f'{c:>12} | {str(fwd_zero):>8}')

    print()
    print('Cross-tab (rows = dec-internally-connected, cols = forward_only zero-conflict)')
    print(f'{"":>10} | {"fwd_zero=T":>11} | {"fwd_zero=F":>11}')
    print(f'{"connected=T":>10} | {cells[(True, True)]:>11} | {cells[(True, False)]:>11}')
    print(f'{"connected=F":>10} | {cells[(False, True)]:>11} | {cells[(False, False)]:>11}')

    # Strong hypothesis match: diagonal heavy, off-diagonal sparse
    diag = cells[(True, True)] + cells[(False, False)]
    off  = cells[(True, False)] + cells[(False, True)]
    total = diag + off
    if total:
        print(f'\nDiagonal agreement: {diag}/{total} = {100*diag/total:.0f}%')

    # Show off-diagonal seeds for closer inspection
    fp = [r for r in rows if r[3] and not r[5]]   # connected but conflict
    fn = [r for r in rows if not r[3] and r[5]]   # fragmented but zero-conflict
    if fp:
        print(f'\nOff-diagonal A (connected but forward_only had conflict): {[r[0] for r in fp]}')
    if fn:
        print(f'Off-diagonal B (fragmented but forward_only zero-conflict): {[r[0] for r in fn]}')


if __name__ == '__main__':
    main()
