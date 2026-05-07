"""Visual reproduction of Exp 3 Hungarian relay_only seed=64. Same setup as
the baseline inspect script, but with the relay_only BT (Relay ON / Forward OFF)
to compare side-by-side why baseline zero-conflict breaks when relay turns on.

    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_inspect_hungarian_relay_only_seed64.py
"""
# === MUST run before any pygame import ====================================
import os, sys
os.environ.pop('SDL_VIDEODRIVER', None)
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..', '..')))
# ==========================================================================

import asyncio
import importlib
import pygame

from core.utils import set_config

YAML = 'scenarios/pygame/features/cen_wrapper/configs/static/hungarian/cenwrapper_hungarian.yaml'
LEADER_RADIUS = 400
FOLLOWER_RADIUS = 800
LEADER_POS = (700, 500)
SEED = 64

set_config(YAML)
from core.utils import config

config['agents']['types']['Leader']['communication_radius'] = LEADER_RADIUS
config['agents']['types']['Follower']['communication_radius'] = FOLLOWER_RADIUS
# Only difference vs baseline inspect: this BT (Relay ON / Forward OFF)
config['agents']['types']['Follower']['behavior_tree_xml'] = 'bt_follower_static_relay_only.xml'

config['simulation']['mode'] = 'static'
config['simulation']['random_seed'] = SEED
config['simulation']['rendering_mode'] = 'Screen'
config['simulation']['speed_up_factor'] = 1
config['simulation']['static_auto_terminate'] = False

config['simulation'].setdefault('saving_options', {})
for k in ('save_gif', 'save_timewise_result_csv', 'save_agentwise_result_csv', 'save_config_yaml'):
    config['simulation']['saving_options'][k] = False
config['simulation'].setdefault('bt_visualiser', {})['enabled'] = False
config['simulation'].setdefault('rendering_options', {}).update({
    'leader_communication_radius_circle': True,
    'leader_communication_topology': True,
    'agent_communication_radius_circle': True,
    'agent_communication_topology': True,
    'agent_id': True,
    'agent_assigned_task_id': True,
    'task_id': True,
})

sim_module = importlib.import_module(config['scenario']['environment'] + '.sim.sim')
from platforms.pygame.bt_runner import BTRunner

sim = sim_module.Sim(config)
for a in sim.agents:
    if a.type == 'Leader':
        a.position = pygame.math.Vector2(*LEADER_POS)

bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)

from platforms.pygame.base_sim import BaseSim
has_own_step = type(sim).step is not BaseSim.step


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
