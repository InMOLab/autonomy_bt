"""Section 5.2, first paragraph: full-coverage equivalence.

Static, every communication radius 2000 (every robot reaches every other one), seeds 1-50, CBBA / GRAPE / Hungarian
(150 instances). A run ends when the allocation has not changed for 300 ticks (cap 6000). Per instance, three runs
whose final allocations are compared:
    wrapper   Leader-as-proxy: bt_static/bt_leader_proxy.xml, bt_static/bt_follower_proxy.xml, R_L = R_f = 2000
    dec       fully connected decentralised execution: no leader, bt_static/bt_follower_dec.xml, R_f = 2000
    baseline  Leader-as-solver (SGA / Hungarian / centralised GRAPE): bt_static/bt_leader_solver.xml,
              bt_static/bt_follower_solver.xml (GRAPE: bt_static/bt_follower_dec.xml), R_L = R_f = 2000

Run from autonomy_bt/ (resumable):
    python scenarios/pygame/features/cen_wrapper/experiments/01_scripts/run_sec52_full_coverage.py [workers] [first-last seed]
Output: 02_data/sec52_full_coverage.csv
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

R = 2000
SOLVER_FOLLOWER_BT = {'cbba': 'bt_static/bt_follower_solver.xml', 'hungarian': 'bt_static/bt_follower_solver.xml',
                      'grape': 'bt_static/bt_follower_dec.xml'}


def runs(seeds):
    out = []
    for seed in seeds:
        for algo in C.ALGOS:
            base = {**C.team_of(algo), 'seed': seed, 'follower_radius': R, 'termination': 'ticks'}
            modes = {
                'wrapper':  {'yaml': C.yaml_path('static', C.WRAPPER[algo]), **C.STATIC_SYSTEMS['hybrid'],
                             'leader_radius': R},
                'dec':      {'yaml': C.yaml_path('static', C.DEC[algo])},
                'baseline': {'yaml': C.yaml_path('static', C.CEN[algo]), 'leader_bt': 'bt_static/bt_leader_solver.xml',
                             'follower_bt': SOLVER_FOLLOWER_BT[algo], 'leader_radius': R},
            }
            for mode, spec in modes.items():
                out.append(({'seed': seed, 'algo': algo, 'mode': mode}, {**base, **spec}))
    return out


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    first, last = (int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else '1-50').split('-'))
    C.run_campaign(runs(range(first, last + 1)), ['seed', 'algo', 'mode'], 'sec52_full_coverage.csv',
                   workers=workers, runner=C.RUN_STATIC, metrics=C.STATIC_METRICS)


if __name__ == '__main__':
    main()
