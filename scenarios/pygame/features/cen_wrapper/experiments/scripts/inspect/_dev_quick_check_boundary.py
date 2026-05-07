"""Dev tool — fail-fast sanity check for Exp 3 (boundary conflicts).

Iterates seeds and breaks on the first run that finishes with
unassigned or overassigned tasks. Each run capped at MAX_TICKS so a
broken setup doesn't hang.

Usage (from project root, autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/_dev_quick_check_boundary.py \
        --algo=hungarian --condition=full
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/_dev_quick_check_boundary.py \
        --algo=cbba --condition=full --seeds=20

Exit code 0 if all seeds clean, 1 on first failing seed (with detail printed).
"""
import argparse
import asyncio
import os
import sys

# Cap so a broken filter design doesn't hang for 30s wall per seed.
MAX_TICKS = 5000
LEADER_RADIUS = 400  # match exp3_boundary_conflicts.py default
FOLLOWER_RADIUS = 300
LEADER_POSITION = (700, 500)
N_AGENTS = 30
N_TASKS_HUNGARIAN = 30
N_TASKS_CBBA = 120
CBBA_MAX_TASKS_PER_AGENT = 4

ALGO_YAMLS = {
    'cbba':      'scenarios/pygame/features/cen_wrapper/configs/static/cbba/cenwrapper_cbba.yaml',
    'hungarian': 'scenarios/pygame/features/cen_wrapper/configs/static/hungarian/cenwrapper_hungarian.yaml',
}
CONDITIONS = {
    'baseline':     'bt_follower_static.xml',
    'relay_only':   'bt_follower_static_relay_only.xml',
    'forward_only': 'bt_follower_static_forward_only.xml',
    'full':         'bt_follower_static_relay.xml',
}


def run_one(algo, condition, seed):
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    sys.path.insert(0, '.')
    from core.utils import set_config
    set_config(ALGO_YAMLS[algo])
    from core.utils import config

    config['agents']['types']['Leader']['communication_radius'] = LEADER_RADIUS
    config['agents']['types']['Follower']['communication_radius'] = FOLLOWER_RADIUS
    config['agents']['types']['Follower']['behavior_tree_xml'] = CONDITIONS[condition]
    config['simulation']['random_seed'] = seed
    config['simulation']['rendering_mode'] = 'None'
    config['simulation'].setdefault('saving_options', {})
    for k in ('save_gif', 'save_timewise_result_csv', 'save_agentwise_result_csv', 'save_config_yaml'):
        config['simulation']['saving_options'][k] = False
    config['simulation'].setdefault('bt_visualiser', {})['enabled'] = False
    config['simulation']['mode'] = 'static'
    config['simulation']['speed_up_factor'] = 0
    # Termination: stable assignments AND tick cap (latter prevents hang).
    config['simulation']['static_timeout_sec'] = 30.0

    import importlib
    import pygame as _pg
    sim_module = importlib.import_module(config['scenario']['environment'] + '.sim.sim')
    from platforms.pygame.bt_runner import BTRunner

    sim = sim_module.Sim(config)
    for a in sim.agents:
        if a.type == 'Leader':
            a.position = _pg.math.Vector2(*LEADER_POSITION)
    bt_runner = BTRunner(config)
    bt_runner.initialize(sim.agents)

    async def loop():
        n = 0
        while sim.running and n < MAX_TICKS:
            await bt_runner.step()
            sim.update_simulation()
            n += 1
        return n
    n = asyncio.run(loop())

    leader = next(a for a in sim.agents if a.type == 'Leader')
    followers = [a for a in sim.agents if a.type == 'Follower']
    all_task_ids = sorted({t.task_id for t in sim.tasks})

    bundle_to_agents = {}
    for a in followers:
        tid = getattr(a, 'assigned_task_id', None)
        if tid is not None:
            bundle_to_agents.setdefault(tid, []).append(a.agent_id)
        for t in (a.planned_tasks or []):
            ptid = t.task_id
            if ptid is not None and ptid != tid:
                bundle_to_agents.setdefault(ptid, []).append(a.agent_id)
    bu = [t for t in all_task_ids if t not in bundle_to_agents]
    bo = {t: ags for t, ags in bundle_to_agents.items() if len(ags) > 1}
    return n, bu, bo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--algo', choices=list(ALGO_YAMLS), required=True)
    ap.add_argument('--condition', choices=list(CONDITIONS), required=True)
    ap.add_argument('--seeds', type=int, default=10)
    args = ap.parse_args()

    print(f'fail-fast Exp 4 — algo={args.algo} cond={args.condition} seeds=1..{args.seeds}')
    for seed in range(1, args.seeds + 1):
        n, bu, bo = run_one(args.algo, args.condition, seed)
        ok = (not bu and not bo)
        marker = 'OK' if ok else 'FAIL'
        print(f'  seed={seed}: {marker}  ticks={n}  unclaimed={bu} overclaimed={bo}', flush=True)
        if not ok:
            print(f'\n→ first failing seed = {seed}. stopping.', flush=True)
            sys.exit(1)
    print('\nall seeds clean ✓')


if __name__ == '__main__':
    main()
