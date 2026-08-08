"""Per-tick GRAPE state tracer for dec mode (Exp 2 follow-up).

Purpose: investigate why dec mode converges in ~10 ticks for 40 agents
when intuition says ≥40 ticks (one agent updates per tick).

Loads `configs/dynamic/global/grape/grape.yaml` (dec, leader=0), runs
for N ticks, and after each tick prints the (evolution_number, partition,
satisfied) of agents 1-5 from their `decision_maker` (live) and
`message_to_share` (outbox).

Usage (from project root, autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_trace_grape_dec.py
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/inspect/_dev_trace_grape_dec.py --ticks=15 --seed=1
"""
import argparse
import asyncio
import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

YAML_PATH = 'scenarios/pygame/features/cen_wrapper/configs/dynamic/global/grape/grape.yaml'
TRACE_AGENT_IDS = [1, 2, 3, 4, 5]


def fmt_partition(partition, max_width=70):
    """Compact partition repr — only non-empty coalitions."""
    items = [(k, sorted(v)) for k, v in partition.items() if v]
    items.sort()
    s = '{' + ', '.join(f'{k}:{v}' for k, v in items) + '}'
    if len(s) > max_width:
        return s[:max_width - 3] + '...'
    return s


def fmt_agent_line(agent, traced_ids):
    """One-line state of an agent's GRAPE: evo, ts, satisfied, partition, outbox-task."""
    dm = getattr(agent, 'decision_maker', None)
    if dm is None:
        return f'  agent {agent.agent_id}: <no decision_maker yet>'
    msg = agent.message_to_share or {}
    outbox_task = msg.get('assigned_task_id', '<no_key>')
    outbox_evo = msg.get('evolution_number', '?')
    return (f'  agent {agent.agent_id}: '
            f'evo={dm.evolution_number} ts={dm.time_stamp} sat={dm.satisfied} '
            f'assigned={dm.assigned_task.task_id if dm.assigned_task else None} '
            f'outbox_task={outbox_task} outbox_evo={outbox_evo}\n'
            f'    partition={fmt_partition(dm.partition)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticks', type=int, default=15)
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

    followers = [a for a in sim.agents if a.type == 'Follower']
    print(f'\n=== GRAPE dec trace — seed={args.seed}, {len(followers)} followers, '
          f'tracing agents {TRACE_AGENT_IDS} ===\n')

    traced = {a.agent_id: a for a in followers if a.agent_id in TRACE_AGENT_IDS}
    if len(traced) < len(TRACE_AGENT_IDS):
        print(f'  (only {len(traced)} of {len(TRACE_AGENT_IDS)} traced agents found)\n')

    async def loop():
        for tick in range(args.ticks):
            await bt_runner.step()
            sim.update_simulation()
            print(f'--- after tick {tick} ---')
            for aid in TRACE_AGENT_IDS:
                a = traced.get(aid)
                if a is not None:
                    print(fmt_agent_line(a, TRACE_AGENT_IDS))
            print()

    asyncio.run(loop())


if __name__ == '__main__':
    main()
