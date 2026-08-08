"""Visual reproduction of Exp 3 Hungarian baseline seed=64. Forces leader to
(700, 500) post-spawn (yaml alone can't express that) and disables the static
auto-termination so the window stays open for inspection.

    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_inspect_hungarian_baseline_seed64.py

Close the pygame window to exit.
"""
# === MUST run before any pygame import ====================================
import os, sys
os.environ.pop('SDL_VIDEODRIVER', None)          # clear stale "dummy" if any
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

# Match Exp 3 baseline condition exactly
config['agents']['types']['Leader']['communication_radius'] = LEADER_RADIUS
config['agents']['types']['Follower']['communication_radius'] = FOLLOWER_RADIUS
config['agents']['types']['Follower']['behavior_tree_xml'] = 'bt_follower_static.xml'  # Relay OFF / Forward OFF

config['simulation']['mode'] = 'static'
config['simulation']['random_seed'] = SEED
config['simulation']['rendering_mode'] = 'Screen'
config['simulation']['speed_up_factor'] = 1
# Disable the experiment's wall-clock auto-terminate so the window stays open
config['simulation']['static_auto_terminate'] = False

# Disable file outputs (visual inspection only)
config['simulation'].setdefault('saving_options', {})
for k in ('save_gif', 'save_timewise_result_csv', 'save_agentwise_result_csv', 'save_config_yaml'):
    config['simulation']['saving_options'][k] = False
config['simulation'].setdefault('bt_visualiser', {})['enabled'] = False
# Show comm-range circles so cen-cluster vs dec is visually obvious
config['simulation'].setdefault('rendering_options', {}).update({
    'leader_communication_radius_circle': True,
    'leader_communication_topology': True,
    'agent_communication_radius_circle': True,
    'agent_communication_topology': True,
    'agent_id': True,
    'agent_assigned_task_id': True,
    'task_id': True,
})

# === Build sim, override leader position BEFORE any BT tick ===============
sim_module = importlib.import_module(config['scenario']['environment'] + '.sim.sim')
from platforms.pygame.bt_runner import BTRunner

sim = sim_module.Sim(config)
for a in sim.agents:
    if a.type == 'Leader':
        a.position = pygame.math.Vector2(*LEADER_POS)

bt_runner = BTRunner(config)
bt_runner.initialize(sim.agents)

# === Game loop (mirrors main.py) ==========================================
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
