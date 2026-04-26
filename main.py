import asyncio
import argparse
import cProfile
import importlib
import signal

from core.utils import set_config

# Parse command line arguments
parser = argparse.ArgumentParser(description='autonomy_bt')
parser.add_argument('--config', type=str, default='scenarios/pygame/simple/configs/grape.yaml', help='Path to the configuration file')
parser.add_argument('--ns', type=str, default=None, help='Override agent namespace, e.g. --ns /Fire_UGV_2')
args = parser.parse_args()

# Load configuration and initialize the environment
set_config(args.config)
from core.utils import config

platform = config.get('platform', 'pygame')


# ============================================================
# Pygame platform
# ============================================================
if platform == 'pygame':
    from threading import Thread
    from platforms.pygame.bt_runner import BTRunner

    # Dynamically import the Sim class
    env_pkg = config.get('scenario').get('environment')
    sim_module = importlib.import_module(env_pkg + ".sim.sim")
    sim = getattr(sim_module, "Sim")(config)

    # Scenarios that override step() (e.g. with PPA expand) use sim.step()
    # Otherwise bt_runner.step() + sim.update_simulation()
    from platforms.pygame.base_sim import BaseSim
    has_own_step = type(sim).step is not BaseSim.step

    bt_runner = BTRunner(config)
    bt_runner.initialize(sim.agents)

    async def game_loop():
        while sim.running:
            sim.handle_keyboard_events()

            if not sim.game_paused and not sim.mission_completed:
                if has_own_step:
                    await sim.step()  # Sim has its own step() with BT + PPA
                else:
                    await bt_runner.step()
                    sim.update_simulation()
                if sim.save_timewise_result_csv:
                    sim.record_timewise_result()

            sim.render()
            sim.update_display()
            if sim.recording:
                sim.record_screen_frame()

        sim.close()

    def main():
        _bt_runner_cfg = config.get('bt_runner', {})
        bt_viz_cfg = _bt_runner_cfg.get('bt_visualiser', config.get('simulation', {}).get('bt_visualiser', {}))
        if bt_viz_cfg.get('enabled', False):
            agent_id = bt_viz_cfg.get('agent_id', 0)
            if agent_id < len(sim.agents):
                from platforms.pygame.bt_visualiser import visualise_bt
                agent = sim.agents[agent_id]
                Thread(
                    target=visualise_bt,
                    args=(agent.agent_id, agent.tree),
                    daemon=True
                ).start()

        asyncio.run(game_loop())

    if __name__ == "__main__":
        _bt_runner_cfg = config.get('bt_runner', {})
        _profiling = _bt_runner_cfg.get('profiling_mode', config.get('simulation', {}).get('profiling_mode', False))
        if _profiling:
            cProfile.run('main()', sort='cumulative')
        else:
            main()


# ============================================================
# ROS2 platform
# ============================================================
elif platform == 'ros2':
    if args.ns is not None:
        config['agent']['namespaces'] = args.ns

    from platforms.ros2.bt_runner import BTRunner
    bt_runner = BTRunner(config)

    async def loop():
        asyncio.get_event_loop().add_signal_handler(
            signal.SIGTERM, lambda: setattr(bt_runner, 'running', False)
        )
        try:
            while bt_runner.running:
                bt_runner.handle_keyboard_events()
                if not bt_runner.paused:
                    await bt_runner.step()
                bt_runner.render()
        finally:
            bt_runner.close()

    if __name__ == "__main__":
        if config.get('bt_runner', {}).get('profiling_mode', False):
            cProfile.run('asyncio.run(loop())', sort='cumulative')
        else:
            try:
                asyncio.run(loop())
            except KeyboardInterrupt:
                pass

else:
    raise ValueError(f"Unknown platform: {platform}. Use 'pygame' or 'ros2'.")
