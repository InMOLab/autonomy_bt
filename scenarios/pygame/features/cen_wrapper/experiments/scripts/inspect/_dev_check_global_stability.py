"""Per-tick check whether ALL 40 agents' outbox `assigned_task_id` are
stable across consecutive ticks (the actual IsAllocationConverged criterion).

Loads `configs/dynamic/global/grape/grape.yaml` (dec, leader=0), runs N
ticks, and after each tick prints:
  - which agents changed their `assigned_task_id` since previous tick
  - whether the GLOBAL 40-entry snapshot is stable for 2 consecutive ticks
    (= IsAllocationConverged would return SUCCESS)

Usage:
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_check_global_stability.py --ticks=20 --seed=1
"""
import argparse
import asyncio
import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

YAML_PATH = 'scenarios/pygame/features/cen_wrapper/configs/dynamic/global/grape/grape.yaml'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticks', type=int, default=20)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args()

    sys.path.insert(0, '.')
    from core.utils import set_config
    set_config(YAML_PATH)
    from core.utils import config

    config['simulation']['random_seed'] = args.seed
    config['simulation']['rendering_mode'] = 'None'
    config['simulation'].setdefault('saving_options', {})
    for k in ('save_gif', 'save_timewise_result_csv',
              'save_agentwise_result_csv', 'save_config_yaml'):
        config['simulation']['saving_options'][k] = False
    config['simulation'].setdefault('bt_visualiser', {})['enabled'] = False
    config['simulation']['mode'] = 'dynamic'

    import importlib
    sim_module = importlib.import_module(config['scenario']['environment'] + '.sim.sim')
    from platforms.pygame.bt_runner import BTRunner

    sim = sim_module.Sim(config)
    bt_runner = BTRunner(config)
    bt_runner.initialize(sim.agents)

    followers = sorted(
        [a for a in sim.agents if a.type == 'Follower'],
        key=lambda a: a.agent_id,
    )
    print(f'\n=== Global stability check — seed={args.seed}, {len(followers)} followers ===\n')

    def snapshot_now():
        """Map agent_id -> outbox.assigned_task_id (or None)."""
        return {
            a.agent_id: (a.message_to_share or {}).get('assigned_task_id')
            for a in followers
        }

    def satisfied_count():
        """How many followers' decide() returned task_id (vs None) this tick.
        Reads agent.assigned_task_id which AssignTask sets to decide return."""
        return sum(1 for a in followers
                   if getattr(a, 'assigned_task_id', None) is not None)

    def msgs_received_count():
        """How many peer messages each follower currently sees (= peers_seen size in IsAllocationConverged)."""
        counts = {}
        for a in followers:
            inbox = getattr(a, 'messages_received', []) or []
            peers_with_id = {m.get('agent_id') for m in inbox
                             if isinstance(m, dict)
                             and m.get('agent_id') is not None
                             and m.get('type') != 'Leader'}
            counts[a.agent_id] = len(peers_with_id)
        return counts

    def find_iac_node(agent):
        """Walk the agent's BT to find its IsAllocationConverged node instance."""
        from core.bt_nodes import BTNodeList
        # Use a BFS/DFS over agent.tree to find by class name.
        node = getattr(agent, 'tree', None)
        if node is None:
            return None
        stack = [node.root if hasattr(node, 'root') else node]
        while stack:
            n = stack.pop()
            if type(n).__name__ == 'IsAllocationConverged':
                return n
            for child in getattr(n, 'children', []):
                stack.append(child)
        return None

    iac_nodes = {a.agent_id: find_iac_node(a) for a in followers}

    # Monkey-patch each IsAllocationConverged node's `condition` attribute
    # (stored at __init__ time inside SyncCondition; patching `_check` alone
    # is ineffective because `run()` calls `self.condition`).
    iac_results_this_tick = {}  # agent_id -> "SUCCESS" / "FAILURE"
    from core.bt_nodes import Status as _Status
    for aid, node in iac_nodes.items():
        if node is None:
            continue
        original_condition = node.condition
        captured_aid = aid

        def make_wrapper(orig, cap_aid):
            def wrapper(agent, blackboard):
                result = orig(agent, blackboard)
                iac_results_this_tick[cap_aid] = (
                    'SUCCESS' if result == _Status.SUCCESS else 'FAILURE'
                )
                return result
            return wrapper
        node.condition = make_wrapper(original_condition, captured_aid)

    prev_snap = None
    first_2tick_stable = None
    first_distance_moved = None

    async def loop():
        nonlocal prev_snap, first_2tick_stable, first_distance_moved
        for tick in range(args.ticks):
            await bt_runner.step()
            sim.update_simulation()
            cur_snap = snapshot_now()
            changed = []
            if prev_snap is not None:
                changed = [aid for aid in sorted(cur_snap)
                           if cur_snap[aid] != prev_snap.get(aid)]
            stable_2tick = (prev_snap is not None and cur_snap == prev_snap)
            # First moved tick
            if first_distance_moved is None:
                if any(getattr(a, 'distance_moved', 0) > 1e-9 for a in followers):
                    first_distance_moved = tick

            counts = msgs_received_count()
            min_peers = min(counts.values()) if counts else 0
            max_peers = max(counts.values()) if counts else 0

            # Per-agent IsAllocationConverged result captured by patched wrapper
            iac_pass = sorted(
                aid for aid, res in iac_results_this_tick.items() if res == 'SUCCESS'
            )
            sat = satisfied_count()
            print(f'tick {tick:3d}: {len(changed):2d} task changed | '
                  f'satisfied={sat}/40 (decide returned task_id) | '
                  f'IAC.SUCCESS({len(iac_pass)}/40)'
                  f'{"  [FIRST MOVE]" if first_distance_moved == tick else ""}')
            iac_results_this_tick.clear()
            if changed:
                # show id + (prev → new)
                hint = ', '.join(
                    f'{aid}:{prev_snap.get(aid)}->{cur_snap[aid]}'
                    for aid in changed[:8]
                )
                if len(changed) > 8:
                    hint += f', ... ({len(changed) - 8} more)'
                print(f'         {hint}')

            if stable_2tick and first_2tick_stable is None:
                first_2tick_stable = tick

            prev_snap = cur_snap

        print(f'\n--- Summary ---')
        print(f'  First 2-tick global stability detected at: tick {first_2tick_stable}')
        print(f'  First follower moved (distance > 0):       tick {first_distance_moved}')
        print(f'  Total followers: {len(followers)}')

    asyncio.run(loop())


if __name__ == '__main__':
    main()
