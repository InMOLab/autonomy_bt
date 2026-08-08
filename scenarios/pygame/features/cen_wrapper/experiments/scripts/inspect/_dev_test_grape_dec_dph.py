"""Quick test — run dec GRAPE for N seeds and report dph (= first-mover tick).

After the IsAllocationConverged fix (`as_bundle` now includes `updated_at`),
dph for dec GRAPE should jump from ~8 (current) to ~55-60 (matching wrapper),
indicating the gate now correctly waits for true algorithm convergence.

Usage:
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_test_grape_dec_dph.py
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_test_grape_dec_dph.py --seeds=10
"""
import argparse
import os
import subprocess
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

YAML_PATHS = {
    'grape':     'scenarios/pygame/features/cen_wrapper/configs/dynamic/global/grape/grape.yaml',
    'cbba':      'scenarios/pygame/features/cen_wrapper/configs/dynamic/global/cbba/cbba.yaml',
    'hungarian': 'scenarios/pygame/features/cen_wrapper/configs/dynamic/global/hungarian/dec_hungarian.yaml',
}
YAML_PATH = YAML_PATHS['grape']  # default for back-compat

CHILD = r'''
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
for k in ("save_gif","save_timewise_result_csv","save_agentwise_result_csv","save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {{}})["enabled"] = False
import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
from platforms.pygame.bt_runner import BTRunner
sim = sim_module.Sim(config)
bt = BTRunner(config)
bt.initialize(sim.agents)

async def run():
    n = 0
    dph = None
    while sim.running and not sim.mission_completed and n < 50000:
        await bt.step()
        sim.update_simulation()
        n += 1
        if dph is None and any(getattr(a, "distance_moved", 0) > 1e-9
                                for a in sim.agents if a.type == "Follower"):
            dph = n
    print("RESULT_JSON:" + json.dumps({{
        "seed": {seed},
        "dph": dph,
        "ticks": n,
        "mission_completed": bool(sim.mission_completed),
    }}))

asyncio.run(run())
'''


def run_one(yaml_path, seed):
    code = CHILD.format(path=yaml_path, seed=seed)
    out = subprocess.run([sys.executable, '-c', code],
                         capture_output=True, text=True, timeout=300,
                         encoding='utf-8', errors='replace')
    import json
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return json.loads(line[len('RESULT_JSON:'):])
    return {'error': (out.stderr or '')[-300:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=5)
    ap.add_argument('--algos', nargs='+', default=list(YAML_PATHS),
                    help=f'subset of {list(YAML_PATHS)}')
    args = ap.parse_args()

    import time as _t
    t0 = _t.time()
    for algo in args.algos:
        if algo not in YAML_PATHS:
            print(f'Unknown algo {algo}; skipping')
            continue
        print(f'\n=== dec {algo.upper()} dph test ({args.seeds} seeds) ===\n')
        print(f'{"seed":>5} | {"dph":>6} | {"ticks":>6} | mc')
        print('-' * 40)
        dphs = []
        for seed in range(1, args.seeds + 1):
            r = run_one(YAML_PATHS[algo], seed)
            if 'error' in r:
                print(f'{seed:>5} | ERROR: {r["error"][:100]}')
                continue
            dphs.append(r['dph'] if r['dph'] is not None else r['ticks'])
            print(f'{seed:>5} | {r["dph"]!s:>6} | {r["ticks"]:>6} | {r["mission_completed"]}')

        if dphs:
            import statistics
            print(f'\n  mean dph = {statistics.mean(dphs):.1f}')
            print(f'  range = [{min(dphs)}, {max(dphs)}]')
    print(f'\n  total elapsed: {_t.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
