"""Dev tool — visualise a single Exp 3 (boundary conflicts) case with pygame.

Use this to investigate WHY a particular (algo, condition, seed) combo
ends up with non-zero conflicts. Radii / leader position are CLI flags so
you can sweep parameter space interactively.

Usage (from project root, autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_viz_boundary.py \
        --algo=hungarian --condition=full --seed=9
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_viz_boundary.py \
        --algo=cbba --condition=forward_only --seed=3 \
        --leader-radius=400 --follower-radius=500

After run completes, prints conflict breakdown + per-agent assignment.
Press `Q` or `Esc` to quit early; `P` or Space to pause.
"""
import argparse
import asyncio
import os
import sys

# Defaults — match exp3_boundary_conflicts.py
DEFAULT_LEADER_RADIUS = 400
DEFAULT_FOLLOWER_RADIUS = 800
DEFAULT_LEADER_POSITION = (700, 500)

ALGO_YAMLS = {
    'cbba':      'scenarios/pygame/features/cen_wrapper/configs/static/cbba/cenwrapper_cbba.yaml',
    'hungarian': 'scenarios/pygame/features/cen_wrapper/configs/static/hungarian/cenwrapper_hungarian.yaml',
}
CONDITIONS = {
    'baseline':     'bt_follower_static.xml',
    'relay_only':   'bt_follower_static_relay_only.xml',
    'forward_only': 'bt_follower_static_forward_only.xml',
    'full':         'bt_follower_static_full.xml',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--algo', choices=list(ALGO_YAMLS.keys()), required=True)
    parser.add_argument('--condition', choices=list(CONDITIONS.keys()), required=True)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--leader-radius', type=float, default=DEFAULT_LEADER_RADIUS,
                        help=f'Leader.communication_radius (default {DEFAULT_LEADER_RADIUS})')
    parser.add_argument('--follower-radius', type=float, default=DEFAULT_FOLLOWER_RADIUS,
                        help=f'Follower.communication_radius (default {DEFAULT_FOLLOWER_RADIUS})')
    parser.add_argument('--leader-x', type=float, default=DEFAULT_LEADER_POSITION[0],
                        help=f'Leader x position (default {DEFAULT_LEADER_POSITION[0]})')
    parser.add_argument('--leader-y', type=float, default=DEFAULT_LEADER_POSITION[1],
                        help=f'Leader y position (default {DEFAULT_LEADER_POSITION[1]})')
    parser.add_argument('--speed', type=int, default=0,
                        help='speed_up_factor: 0=max (default, recommended), '
                             '10=10 FPS, 30=30 FPS, 1=real-time (very slow with sampling_freq=1)')
    args = parser.parse_args()

    leader_position = (args.leader_x, args.leader_y)

    sys.path.insert(0, '.')
    from core.utils import set_config
    set_config(ALGO_YAMLS[args.algo])
    from core.utils import config

    # CLI-overridable radii / leader position
    config["agents"]["types"]["Leader"]["communication_radius"] = args.leader_radius
    config["agents"]["types"]["Follower"]["communication_radius"] = args.follower_radius
    config["agents"]["types"]["Follower"]["behavior_tree_xml"] = CONDITIONS[args.condition]
    config["simulation"]["random_seed"] = args.seed
    config["simulation"]["mode"] = "static"
    config["simulation"]["rendering_mode"] = "Screen"   # show on screen
    config["simulation"]["static_timeout_sec"] = 30.0
    # Disable both stability auto-stop and timeout — let user watch as long
    # as they want; press Q/Esc to quit.
    config["simulation"]["static_auto_terminate"] = False
    config["simulation"]["speed_up_factor"] = args.speed
    config["simulation"].setdefault("saving_options", {})
    for k in ("save_gif", "save_timewise_result_csv", "save_agentwise_result_csv", "save_config_yaml"):
        config["simulation"]["saving_options"][k] = False
    config["simulation"].setdefault("bt_visualiser", {})["enabled"] = False
    # Enable communication visualization for debugging
    config["simulation"]["rendering_options"]["leader_communication_radius_circle"] = True
    config["simulation"]["rendering_options"]["agent_communication_topology"] = True
    config["simulation"]["rendering_options"]["leader_communication_topology"] = True

    import importlib
    sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
    from platforms.pygame.bt_runner import BTRunner

    sim = sim_module.Sim(config)

    import pygame as _pg
    for a in sim.agents:
        if a.type == "Leader":
            a.position = _pg.math.Vector2(*leader_position)

    bt_runner = BTRunner(config)
    bt_runner.initialize(sim.agents)

    print(f'\nRunning {args.algo}/{args.condition} seed={args.seed}')
    print(f'  Leader at {leader_position}, comm={args.leader_radius}, follower comm={args.follower_radius}')
    print(f'  Follower BT: {CONDITIONS[args.condition]}')
    print(f'  Press Q/Esc to quit, P/Space to pause.\n')

    async def loop():
        while sim.running:
            sim.handle_keyboard_events()
            if not sim.game_paused:
                await bt_runner.step()
                sim.update_simulation()
            sim.render()
            sim.update_display()

    asyncio.run(loop())

    # Final report after sim ends (mission_completed or quit)
    print('\n=== Final allocation snapshot ===')
    leader = next(a for a in sim.agents if a.type == "Leader")
    followers = [a for a in sim.agents if a.type == "Follower"]
    all_task_ids = sorted(set(t.task_id for t in sim.tasks))

    print(f'Leader pos: ({leader.position.x:.0f}, {leader.position.y:.0f}), comm={leader.communication_radius}')
    leader_plan = leader.message_to_share.get('central_plan', {}) if leader.message_to_share else {}
    leader_allocations = leader_plan.get('task_allocations', {}) if isinstance(leader_plan, dict) else {}
    cen_claimed = {
        task_id
        for aid, bundle in leader_allocations.items()
        if bundle
        for task_id in bundle
        if task_id is not None
    }
    print(f'Cen-allocated tasks (in leader broadcast): {sorted(cen_claimed)}')
    print()

    primary_to_agents = {}
    bundle_to_agents = {}
    for a in followers:
        d = a.position.distance_to(leader.position)
        in_lr = d <= leader.communication_radius
        msg = getattr(a, 'message_to_share', {}) or {}
        ta_in_outbox = msg.get('central_plan') is not None
        msgs_with_alloc = sum(1 for m in (a.messages_received or []) if isinstance(m, dict) and m.get('central_plan'))
        planned = [t.task_id for t in (a.planned_tasks or [])]
        tid = getattr(a, 'assigned_task_id', None)
        if tid is not None:
            primary_to_agents.setdefault(tid, []).append(a.agent_id)
            bundle_to_agents.setdefault(tid, []).append(a.agent_id)
        for ptid in planned:
            if ptid is not None and ptid != tid:
                bundle_to_agents.setdefault(ptid, []).append(a.agent_id)
        bundle_str = f' bundle={planned}' if planned else ''
        print(f'  agent {a.agent_id}: dist_to_leader={d:.0f} in_lr={in_lr} '
              f'has_received_alloc={msgs_with_alloc} forwards_alloc={ta_in_outbox} '
              f'assigned={tid}{bundle_str}')
    print()

    print('=== Conflict breakdown ===')
    print(f'  bundle_unclaimed: tasks with NO claimer:')
    unclaimed = [t for t in all_task_ids if t not in bundle_to_agents]
    print(f'    {unclaimed}')
    print(f'  bundle_overclaimed: tasks with 2+ claimers:')
    overclaimed = {t: ags for t, ags in bundle_to_agents.items() if len(ags) > 1}
    for t, ags in overclaimed.items():
        print(f'    task {t}: claimed by agents {ags}')
    print(f'  Summary: {len(unclaimed)} unclaimed, {len(overclaimed)} overclaimed')


if __name__ == '__main__':
    main()
