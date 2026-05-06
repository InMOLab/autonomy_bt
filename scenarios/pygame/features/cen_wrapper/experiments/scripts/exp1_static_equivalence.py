"""Exp 1 — Static Equivalence (Sec III of the paper).

For each (algo, mode) ∈ {CBBA, GRAPE, Hungarian} × {pure-dec, cen-wrapper,
cen-baseline}, runs the *static* yaml and records each follower's final
`planned_tasks` bundle (full path for CBBA, single task for GRAPE/Hungarian).
The 3-mode signatures must match within each algorithm group — that is the
byte-equivalent verification of Proposition 1 (allocation equivalence).

Comm radius is fully connected (= 2000) in every static yaml so
positional sampling cannot diverge between modes.

Usage (from project root, autonomy_bt/):
  python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py
  python scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py --seeds=6

Outputs:
  - console: per-seed match/mismatch summary
  - data/exp1_static_results.csv: raw per-(seed, algo, mode, agent_id) bundle
    so 3-way comparison can be redone offline / cross-checked.
"""
import os, sys, asyncio, importlib, subprocess, json, csv
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

YAMLS = {
    'cbba': [
        ('dec',      'configs/static/cbba/cbba.yaml'),
        ('wrapper',  'configs/static/cbba/cenwrapper_cbba.yaml'),
        ('baseline', 'configs/static/cbba/sga.yaml'),
    ],
    'grape': [
        ('dec',      'configs/static/grape/grape.yaml'),
        ('wrapper',  'configs/static/grape/cenwrapper_grape.yaml'),
        ('baseline', 'configs/static/grape/cen_grape.yaml'),
    ],
    'hungarian': [
        ('dec',      'configs/static/hungarian/dec_hungarian.yaml'),
        ('wrapper',  'configs/static/hungarian/cenwrapper_hungarian.yaml'),
        ('baseline', 'configs/static/hungarian/hungarian.yaml'),
    ],
}

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
DATA_DIR = os.path.join(SCEN_ROOT, 'experiments', 'data')
OUTPUT_CSV = os.path.join(DATA_DIR, 'exp1_static_results.csv')


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


def parse_sig_and_ticks(line):
    """Returns (sig_str, sig_list_of_tuples, ticks, running) or (None, None, None, None) on error."""
    if not line.startswith('RESULT_LINE:'):
        return None, None, None, None
    try:
        end_idx = line.index(':TICKS:')
        sig_str = line[len('RESULT_LINE:'):end_idx]
        rest = line[end_idx + len(':TICKS:'):]
        ticks_str, _, running_str = rest.partition(':RUNNING:')
        sig_list = eval(sig_str)  # safe: produced by our own subprocess via repr()
        return sig_str, sig_list, int(ticks_str), running_str.strip() == 'True'
    except Exception:
        return None, None, None, None


# results[seed][(algo, mode)] = result_line
results = {seed: {} for seed in SEEDS}

for seed in SEEDS:
    print(f'\n\n###########  SEED = {seed}  ###########')
    for algo, mode_paths in YAMLS.items():
        print(f'\n=== {algo} (seed={seed}) ===')
        for mode, p in mode_paths:
            print(f'  running [{mode}] {p} ...')
            r = run_one(p, seed)
            results[seed][(algo, mode)] = r
            print(f'    -> {r[:160]}')


# ─────────────────────  Write raw CSV  ─────────────────────
os.makedirs(DATA_DIR, exist_ok=True)
csv_rows = []
for seed in SEEDS:
    for algo, mode_paths in YAMLS.items():
        for mode, _ in mode_paths:
            line = results[seed][(algo, mode)]
            sig_str, sig_list, ticks, running = parse_sig_and_ticks(line)
            if sig_list is None:
                csv_rows.append({
                    'seed': seed, 'algo': algo, 'mode': mode,
                    'agent_id': -1, 'bundle': '<error>',
                    'ticks': '', 'running': '', 'error': line[:200],
                })
                continue
            for agent_id, bundle in sig_list:
                csv_rows.append({
                    'seed': seed, 'algo': algo, 'mode': mode,
                    'agent_id': agent_id,
                    'bundle': '|'.join(str(t) for t in bundle),  # e.g. "1|15|45|10|6"
                    'ticks': ticks, 'running': running, 'error': '',
                })

with open(OUTPUT_CSV, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['seed', 'algo', 'mode', 'agent_id', 'bundle', 'ticks', 'running', 'error'])
    writer.writeheader()
    writer.writerows(csv_rows)
print(f'\nRaw assignments written → {OUTPUT_CSV} ({len(csv_rows)} rows)')


# ─────────────────────  SUMMARY: per-algo across seeds  ─────────────────────
print('\n\n' + '=' * 70)
print(f'   SUMMARY - 3-way match per algorithm, across {len(SEEDS)} seed(s)')
print('=' * 70)

for algo, mode_paths in YAMLS.items():
    print(f'\n[{algo}]')
    seed_status = []
    for seed in SEEDS:
        sigs = []
        for mode, _ in mode_paths:
            sig_str, _, _, _ = parse_sig_and_ticks(results[seed][(algo, mode)])
            sigs.append(sig_str if sig_str is not None else '<error>')
        match = len(set(sigs)) == 1 and not any(s.startswith('<') for s in sigs)
        seed_status.append((seed, match, sigs))
    overall = all(m for _, m, _ in seed_status)
    flag = '[OK ALL SEEDS MATCH]' if overall else '[X]'
    print(f'  {flag}')
    for seed, match, sigs in seed_status:
        seed_flag = '[OK]' if match else '[X]'
        print(f'    seed={seed} {seed_flag}')
        if not match:
            for (mode, p), s in zip(mode_paths, sigs):
                print(f'      [{mode:8s}] {os.path.basename(p):30s} -> {s[:110]}')
