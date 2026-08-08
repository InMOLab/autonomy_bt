"""All-follower connectivity check (cen + dec, leader excluded).

For each seed:
  1. Re-create initial spawn (Sim init only).
  2. Build graph on all followers with edges where pairwise distance
     <= FOLLOWER_RADIUS. Leader excluded.
  3. Count connected components.
     - 1 component  → full follower mesh connected
     - >1 component → fragmented (full mode mechanism cannot bridge isolated
                                  follower segments)

Run:
    # check the 3 CBBA full-mode failure seeds
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_check_follower_connectivity.py --algo cbba --seeds 13 47 81

    # full sweep
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_check_follower_connectivity.py --algo cbba --range 100
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_check_follower_connectivity.py --algo hungarian --range 100
"""
import argparse
import os
import subprocess
import sys

LEADER_RADIUS = 400
FOLLOWER_RADIUS = 800
SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
ALGO_YAML = {
    'cbba':      'configs/static/cbba/cenwrapper_cbba.yaml',
    'hungarian': 'configs/static/hungarian/cenwrapper_hungarian.yaml',
}

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
    parent = {n: n for n in node_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return len({find(n) for n in node_ids})


def classify(yaml_rel, seed):
    fol = _follower_positions(yaml_rel, seed)
    if len(fol) <= 1:
        return len(fol), len(fol)
    edges = []
    r_sq = FOLLOWER_RADIUS ** 2
    for i in range(len(fol)):
        for j in range(i + 1, len(fol)):
            dx = fol[i]['x'] - fol[j]['x']
            dy = fol[i]['y'] - fol[j]['y']
            if dx * dx + dy * dy <= r_sq:
                edges.append((fol[i]['id'], fol[j]['id']))
    ids = [f['id'] for f in fol]
    return len(fol), _connected_components(ids, edges)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--algo', default='cbba', choices=list(ALGO_YAML))
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument('--seeds', nargs='+', type=int, help='specific seeds to check')
    grp.add_argument('--range', type=int, help='check seeds 1..N')
    args = ap.parse_args()

    yaml_rel = ALGO_YAML[args.algo]
    seeds = args.seeds if args.seeds else list(range(1, args.range + 1))

    print(f'algo={args.algo}  follower_R={FOLLOWER_RADIUS}  (leader excluded, all followers union)')
    print(f'{"seed":>5} | {"n_fol":>5} | {"n_comp":>6} | {"connected":>9}')
    print('-' * 40)

    n_conn = 0
    n_frag = 0
    frag_seeds = []
    for s in seeds:
        n_fol, n_comp = classify(yaml_rel, s)
        connected = (n_comp == 1)
        if connected:
            n_conn += 1
        else:
            n_frag += 1
            frag_seeds.append(s)
        print(f'{s:>5} | {n_fol:>5} | {n_comp:>6} | {str(connected):>9}')

    print()
    print(f'Connected: {n_conn}/{len(seeds)}    Fragmented: {n_frag}/{len(seeds)}')
    if frag_seeds and len(frag_seeds) <= 20:
        print(f'Fragmented seeds: {frag_seeds}')


if __name__ == '__main__':
    main()
