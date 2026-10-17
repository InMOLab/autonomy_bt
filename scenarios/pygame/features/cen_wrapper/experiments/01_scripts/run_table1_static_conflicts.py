"""Table 1: static boundary conflicts under mechanism ablation (CBBA and Hungarian, R_L = R_f = 500).

Seeds: 02_data/table1_seeds.json. With 15 followers at R_f = R_L = 500, the first 45 seeds whose follower graph is
connected without the leader and the first 5 whose team graph is connected only through the leader. Robot and task
positions depend only on the seed and the team size. Teams: CBBA 15 / 60 (bundle 4, full bundle reset), Hungarian 15 / 15.

Steps (run from autonomy_bt/, resumable):
  python .../run_table1_static_conflicts.py proxy [workers]
        Leader-as-proxy with inbound relay (In) and outbound emission (Out) switched on or off
        (conditions none / inbound_only / outbound_only / both) -> 02_data/table1_proxy_ablation.csv
        Ends by the simulator's own static rule: allocation unchanged for 1 s of real time (after 1 s, cap 30 s).
  python .../run_table1_static_conflicts.py relay_dec [workers]
        Leader-as-relay (R_L 500) and Dec-only (proxy trees, R_L 0) -> 02_data/table1_relay_deconly.csv
  python .../run_table1_static_conflicts.py solver [workers]
        Leader-as-solver with both boundary slots (relay and plan forwarding) -> 02_data/table1_solver.csv
  python .../run_table1_static_conflicts.py solver_slots [workers]
        Leader-as-solver with its slots switched off (none / relay_only / forward_only) -> 02_data/table1_solver_slots.csv
The last three steps end when the allocation has not changed for 300 ticks (cap 6000).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SEEDS = json.load(open(os.path.join(C.EXP_DIR, '02_data', 'table1_seeds.json')))['seeds']
ALGOS = ('cbba', 'hungarian')
KEYS = ['seed', 'algo', 'system', 'leader_radius', 'follower_radius']
SOLVER_TREES = {'solver': {'both': 'bt_static/bt_follower_solver.xml'},
                'solver_slots': {'none': 'bt_static/bt_follower_solver_no_relay_no_plan.xml',
                                 'relay_only': 'bt_static/bt_follower_solver_no_plan.xml',
                                 'forward_only': 'bt_static/bt_follower_solver_no_relay.xml'}}


def reset(algo):
    return {'cbba_bundle_reset': 'full'} if algo == 'cbba' else {}


def proxy_runs():
    runs = []
    for seed in SEEDS:
        for algo in ALGOS:
            for condition, leader_bt in C.ABLATION_LEADER_BT.items():
                spec = {'seed': seed, 'leader_radius': 500, 'follower_radius': 500, **C.DENSE_TEAM[algo],
                        'yaml': C.yaml_path('static', C.WRAPPER[algo]), 'leader_bt': leader_bt,
                        'follower_bt': 'bt_static/bt_follower_proxy.xml', **reset(algo)}
                runs.append(({'seed': seed, 'algo': algo, 'condition': condition}, spec))
    return runs


def relay_dec_runs():
    runs = []
    for seed in SEEDS:
        for algo in ALGOS:
            base = {**C.DENSE_TEAM[algo], 'seed': seed, 'follower_radius': 500, 'termination': 'ticks', **reset(algo)}
            systems = {
                'relay': {'yaml': C.yaml_path('static', C.WRAPPER[algo]), **C.STATIC_SYSTEMS['relay'], 'leader_radius': 500},
                'dec':   {'yaml': C.yaml_path('static', C.WRAPPER[algo]), **C.STATIC_SYSTEMS['hybrid'], 'leader_radius': 0},
            }
            for system, spec in systems.items():
                runs.append(({'seed': seed, 'algo': algo, 'system': system, 'leader_radius': spec['leader_radius'],
                              'follower_radius': 500}, {**base, **spec}))
    return runs


def solver_runs(step):
    runs = []
    for seed in SEEDS:
        for algo in ALGOS:
            for condition, follower_bt in SOLVER_TREES[step].items():
                spec = {**C.DENSE_TEAM[algo], 'seed': seed, 'follower_radius': 500, 'leader_radius': 500,
                        'termination': 'ticks', 'yaml': C.yaml_path('static', C.CEN[algo]),
                        'leader_bt': 'bt_static/bt_leader_solver.xml', 'follower_bt': follower_bt, **reset(algo)}
                key = {'seed': seed, 'algo': algo, 'system': 'solver', 'leader_radius': 500, 'follower_radius': 500}
                if step == 'solver_slots':
                    key['condition'] = condition
                runs.append((key, spec))
    return runs


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else ''
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    if step == 'proxy':
        C.run_campaign(proxy_runs(), ['seed', 'algo', 'condition'], 'table1_proxy_ablation.csv', workers=workers,
                       runner=C.RUN_STATIC, metrics=C.STATIC_METRICS)
    elif step == 'relay_dec':
        C.run_campaign(relay_dec_runs(), KEYS, 'table1_relay_deconly.csv', workers=workers,
                       runner=C.RUN_STATIC, metrics=C.STATIC_METRICS)
    elif step in SOLVER_TREES:
        C.run_campaign(solver_runs(step), KEYS + (['condition'] if step == 'solver_slots' else []), f'table1_{step}.csv',
                       workers=workers, runner=C.RUN_STATIC, metrics=C.STATIC_METRICS)
    else:
        sys.exit('step: proxy | relay_dec | solver | solver_slots')


if __name__ == '__main__':
    main()
