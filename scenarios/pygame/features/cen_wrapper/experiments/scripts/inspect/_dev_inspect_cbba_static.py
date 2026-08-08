"""Visual reproduction of any Exp 1 CBBA static-mode seed for any of the
three modes (dec / wrapper / baseline). Useful when CBBA dec ≠ SGA baseline
on a particular seed — open two terminals, run with --mode dec in one and
--mode baseline in the other, compare the path arrows agent-by-agent.

Usage (from project root, autonomy_bt/):
    # Run two terminals side-by-side for a CBBA-vs-SGA mismatch seed:
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_inspect_cbba_static.py --seed 1 --mode dec
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_inspect_cbba_static.py --seed 1 --mode baseline

    # Wrapper version uses the same yaml chain as dec but routes through
    # CentralisationWrapper — should match dec exactly.
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_inspect_cbba_static.py --seed 1 --mode wrapper

Known mismatch seeds (CBBA dec/wrapper vs SGA baseline) from the 100-seed
post-fix run: 1, 4, 11, 14, 28, 32, 39, 41, 73, 94 (task-set differs).
seed=44 used to be a path-order-only mismatch under the older SGA formula.

Close the pygame window to exit.
"""
# === MUST run before any pygame import ====================================
import os, sys
os.environ.pop('SDL_VIDEODRIVER', None)
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..', '..')))
# ==========================================================================

import argparse
import asyncio
import importlib
import pygame

ap = argparse.ArgumentParser()
ap.add_argument('--mode', choices=['dec', 'wrapper', 'baseline'], default='dec')
ap.add_argument('--seed', type=int, default=44)
args = ap.parse_args()

YAML_BY_MODE = {
    'dec':      'scenarios/pygame/features/cen_wrapper/configs/static/cbba/cbba.yaml',
    'wrapper':  'scenarios/pygame/features/cen_wrapper/configs/static/cbba/cenwrapper_cbba.yaml',
    'baseline': 'scenarios/pygame/features/cen_wrapper/configs/static/cbba/sga.yaml',
}

from core.utils import set_config
set_config(YAML_BY_MODE[args.mode])
from core.utils import config

# Match Exp 1 setup (static, comm=2000 fully-connected)
config['simulation']['mode'] = 'static'
config['simulation']['random_seed'] = args.seed
config['simulation']['rendering_mode'] = 'Screen'
config['simulation']['speed_up_factor'] = 0   # max speed
config['simulation']['static_auto_terminate'] = False  # keep window open
config['simulation'].setdefault('saving_options', {})
for k in ('save_gif', 'save_timewise_result_csv', 'save_agentwise_result_csv', 'save_config_yaml'):
    config['simulation']['saving_options'][k] = False
config['simulation'].setdefault('bt_visualiser', {})['enabled'] = False
config['simulation'].setdefault('rendering_options', {}).update({
    'agent_id': True,
    'agent_assigned_task_id': True,
    'agent_path_to_assigned_tasks': True,
    'task_id': True,
})

sim_module = importlib.import_module(config['scenario']['environment'] + '.sim.sim')
from platforms.pygame.bt_runner import BTRunner

sim = sim_module.Sim(config)
bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)

from platforms.pygame.base_sim import BaseSim
has_own_step = type(sim).step is not BaseSim.step

print(f'CBBA static seed={args.seed} mode={args.mode}  yaml={YAML_BY_MODE[args.mode]}')


async def game_loop():
    while sim.running:
        sim.handle_keyboard_events()
        if not sim.game_paused and not sim.mission_completed:
            if has_own_step:
                await sim.step()
            else:
                await bt_runner.step()
                sim.update_simulation()
        sim.render()
        sim.update_display()
    sim.close()


asyncio.run(game_loop())
