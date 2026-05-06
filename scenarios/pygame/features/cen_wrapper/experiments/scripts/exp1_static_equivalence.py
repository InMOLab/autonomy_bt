"""Exp 1 — Static Equivalence (Sec III of the paper).

For each (algo, mode) ∈ {CBBA, GRAPE, Hungarian} × {pure-dec, cen-wrapper,
cen-baseline}, runs the *static* yaml and records each follower's final
`planned_tasks[0].task_id` (or `assigned_task_id`). The 3-mode signatures
must match within each algorithm group — that is the byte-equivalent
verification of Proposition 1 (allocation equivalence).

Comm radius is fully connected (= 2000) in every static yaml so
positional sampling cannot diverge between modes.

Usage (from project root, autonomy_bt/):
  python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py
  python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py --seeds=6
"""
import os, sys, asyncio, importlib, subprocess, json
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

YAMLS = {
    'cbba': [
        'configs/static/cbba/cbba.yaml',
        'configs/static/cbba/cenwrapper_cbba.yaml',
        'configs/static/cbba/sga.yaml',
    ],
    'grape': [
        'configs/static/grape/grape.yaml',
        'configs/static/grape/cenwrapper_grape.yaml',
        'configs/static/grape/cen_grape.yaml',
    ],
    'hungarian': [
        'configs/static/hungarian/dec_hungarian.yaml',
        'configs/static/hungarian/cenwrapper_hungarian.yaml',
        'configs/static/hungarian/hungarian.yaml',
    ],
}

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'

# Pick seed count from CLI (default: 1 seed; e.g. `--seeds=6` runs seeds 1..6)
def _parse_seeds():
    for a in sys.argv[1:]:
        if a.startswith('--seeds='):
            return list(range(1, int(a.split('=', 1)[1]) + 1))
    return [1]
SEEDS = _parse_seeds()


def run_one(yaml_rel, seed):
    code = '''
import os, sys, asyncio
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")
from core.utils import set_config
set_config("{path}")
from core.utils import config
config["simulation"]["random_seed"] = {seed}
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {})
for k in ("save_gif","save_timewise_result_csv","save_agentwise_result_csv","save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {})["enabled"] = False
config["simulation"]["mode"] = "static"
import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
sim = getattr(sim_module, "Sim")(config)
from platforms.pygame.bt_runner import BTRunner
bt = BTRunner(config)
bt.initialize(sim.agents)
async def run():
    n = 0
    while sim.running and n < 200000:
        await bt.step(); sim.update_simulation()
        n += 1
    def planned_bundle(a):
        # Full bundle (CBBA path) — Hungarian/GRAPE keep len <= 1.
        p = getattr(a, "planned_tasks", None)
        if p:
            return tuple(t.task_id for t in p)
        aid = getattr(a, "assigned_task_id", None)
        return (aid,) if aid is not None else ()
    sig = sorted([(a.agent_id, planned_bundle(a)) for a in sim.agents if a.type == "Follower"])
    print("RESULT_LINE:" + repr(sig) + ":TICKS:" + str(n) + ":RUNNING:" + str(sim.running))
asyncio.run(run())
'''.replace('{path}', SCEN_ROOT + '/' + yaml_rel).replace('{seed}', str(seed))
    out = subprocess.run([sys.executable, '-c', code],
                         capture_output=True, text=True, timeout=180,
                         encoding='utf-8', errors='replace')
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_LINE:'):
            return line
    return f'ERROR: {(out.stderr or "")[:300]}'


def parse_sig(line):
    if not line.startswith('RESULT_LINE:'):
        return '<error>'
    try:
        end_idx = line.index(':TICKS:')
        return line[len('RESULT_LINE:'):end_idx]
    except Exception:
        return '<parse error>'


# results[seed][yaml_path] = result_line
results = {seed: {} for seed in SEEDS}

for seed in SEEDS:
    print(f'\n\n###########  SEED = {seed}  ###########')
    for algo, paths in YAMLS.items():
        print(f'\n=== {algo} (seed={seed}) ===')
        for p in paths:
            print(f'  running {p} ...')
            r = run_one(p, seed)
            results[seed][p] = r
            print(f'    -> {r[:160]}')


# ─────────────────────  SUMMARY: per-algo across seeds  ─────────────────────
print('\n\n' + '=' * 70)
print(f'   SUMMARY - 3-way match per algorithm, across {len(SEEDS)} seed(s)')
print('=' * 70)

for algo, paths in YAMLS.items():
    print(f'\n[{algo}]')
    seed_status = []
    for seed in SEEDS:
        sigs = [parse_sig(results[seed][p]) for p in paths]
        match = len(set(sigs)) == 1 and not any(s.startswith('<') for s in sigs)
        seed_status.append((seed, match, sigs))
    overall = all(m for _, m, _ in seed_status)
    flag = '[OK ALL SEEDS MATCH]' if overall else '[X]'
    print(f'  {flag}')
    for seed, match, sigs in seed_status:
        seed_flag = '[OK]' if match else '[X]'
        print(f'    seed={seed} {seed_flag}')
        if not match:
            for p, s in zip(paths, sigs):
                print(f'      {os.path.basename(p):30s} -> {s[:110]}')
