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
import os, sys, asyncio, json
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
import importlib, math
import pygame
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
sim = getattr(sim_module, "Sim")(config)
from platforms.pygame.bt_runner import BTRunner
bt = BTRunner(config)
bt.initialize(sim.agents)

# Pull utility constants from config.
def _cfg(key, default):
    for sect in ("CBBA","GRAPE","Hungarian"):
        v = config.get("decision_making",{}).get(sect,{}).get(key)
        if v is not None: return v
    return default
LAMBDA = _cfg("task_reward_discount_factor", 0.999)
AGENT_SPEED = 0.5
ALPHA = config.get("decision_making",{}).get("GRAPE",{}).get("social_inhibition_factor", 0)

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
    followers = [a for a in sim.agents if a.type == "Follower"]
    sig = sorted([(a.agent_id, planned_bundle(a)) for a in followers])
    # ── Team utility: Σ λ^(τ/v) / |C|^α across (agent, task) assignments ──
    # Each agent's "effective path" = planned_tasks if set (CBBA), else
    # singleton [assigned_task] (Hungarian, GRAPE — neither uses bundles).
    # Per (agent, task) contribution: lambda^(tau/v) / |C|^alpha
    def _eff_path(a):
        p = getattr(a, "planned_tasks", None) or []
        if p:
            return list(p)
        aid = getattr(a, "assigned_task_id", None)
        if aid is None:
            return []
        # Resolve task object from agent.tasks_info or sim.tasks
        task_lookup = getattr(a, "tasks_info", None)
        if task_lookup and aid in task_lookup:
            return [task_lookup[aid]]
        for t in sim.tasks:
            if t.task_id == aid:
                return [t]
        return []

    coalition_size = {}
    for a in followers:
        for t in _eff_path(a):
            coalition_size[t.task_id] = coalition_size.get(t.task_id, 0) + 1
    team_utility = 0.0
    for a in followers:
        path = _eff_path(a)
        if not path:
            continue
        pos = pygame.Vector2(a.position)
        tau = 0.0
        for t in path:
            tpos = pygame.Vector2(t.position)
            tau += pos.distance_to(tpos)
            r = LAMBDA ** (tau / AGENT_SPEED)
            c = max(coalition_size.get(t.task_id, 1), 1)
            team_utility += r / (c ** ALPHA)
            pos = tpos
    payload = {
        "sig": sig,
        "ticks": n,
        "running": bool(sim.running),
        "team_utility": float(team_utility),
    }
    print("RESULT_JSON:" + json.dumps(payload, default=str))

asyncio.run(run())
'''.replace('{path}', SCEN_ROOT + '/' + yaml_rel).replace('{seed}', str(seed))
    out = subprocess.run([sys.executable, '-c', code],
                         capture_output=True, text=True, timeout=180,
                         encoding='utf-8', errors='replace')
    for line in (out.stdout or '').splitlines():
        if line.startswith('RESULT_JSON:'):
            return line
    return f'ERROR: {(out.stderr or "")[:300]}'


def parse_sig_and_ticks(line):
    """Returns (sig_str, sig_list_of_tuples, ticks, running, utility) or (None, None, None, None, None) on error."""
    if not line.startswith('RESULT_JSON:'):
        return None, None, None, None, None
    try:
        payload = json.loads(line[len('RESULT_JSON:'):])
        sig_list = [tuple([entry[0], tuple(entry[1])]) for entry in payload['sig']]
        sig_str = repr(sig_list)
        return sig_str, sig_list, int(payload['ticks']), bool(payload['running']), float(payload.get('team_utility', 0.0))
    except Exception:
        return None, None, None, None, None


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
            sig_str, sig_list, ticks, running, utility = parse_sig_and_ticks(line)
            if sig_list is None:
                csv_rows.append({
                    'seed': seed, 'algo': algo, 'mode': mode,
                    'agent_id': -1, 'bundle': '<error>',
                    'ticks': '', 'running': '', 'team_utility': '',
                    'error': line[:200],
                })
                continue
            for agent_id, bundle in sig_list:
                csv_rows.append({
                    'seed': seed, 'algo': algo, 'mode': mode,
                    'agent_id': agent_id,
                    'bundle': '|'.join(str(t) for t in bundle),  # e.g. "1|15|45|10|6"
                    'ticks': ticks, 'running': running,
                    'team_utility': f'{utility:.6f}',
                    'error': '',
                })

with open(OUTPUT_CSV, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['seed', 'algo', 'mode', 'agent_id', 'bundle', 'ticks', 'running', 'team_utility', 'error'])
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
        utils = []
        for mode, _ in mode_paths:
            sig_str, _, _, _, util = parse_sig_and_ticks(results[seed][(algo, mode)])
            sigs.append(sig_str if sig_str is not None else '<error>')
            utils.append(util)
        match = len(set(sigs)) == 1 and not any(s.startswith('<') for s in sigs)
        seed_status.append((seed, match, sigs, utils))
    overall = all(m for _, m, _, _ in seed_status)
    flag = '[OK ALL SEEDS MATCH]' if overall else '[X]'
    print(f'  {flag}')
    for seed, match, sigs, utils in seed_status:
        seed_flag = '[OK]' if match else '[X]'
        u_str = ' / '.join(f'{u:.4f}' if u is not None else 'NA' for u in utils)
        print(f'    seed={seed} {seed_flag}  utility(dec/wrap/base): {u_str}')
        if not match:
            for (mode, p), s in zip(mode_paths, sigs):
                print(f'      [{mode:8s}] {os.path.basename(p):30s} -> {s[:110]}')
