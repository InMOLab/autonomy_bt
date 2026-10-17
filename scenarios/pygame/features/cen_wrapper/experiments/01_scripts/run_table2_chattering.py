"""Table 2: boundary chattering under mechanism ablation.

Dynamic, R_f = 150, R_L = 500, seeds 1-50, CBBA / GRAPE / Hungarian with the teams of common.team_of. Eleven designs
(system labels of common.DYNAMIC_SYSTEMS):
  Leader-as-proxy   hybrid (no rule), hybrid_iso, hybrid_adopt, hybrid_rules (both rules)
  Leader-as-relay   relay (no rule), relay_hold (+ iso)
  Leader-as-solver  solver (no rule), solver_nograce, solver_noreset, solver_nocommit, solver_commit (all rules)

Run from autonomy_bt/ (resumable):
  python scenarios/pygame/features/cen_wrapper/experiments/01_scripts/run_table2_chattering.py [workers]
Output: 02_data/table2_chattering.csv
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SYSTEMS = ['hybrid', 'hybrid_iso', 'hybrid_adopt', 'hybrid_rules', 'relay', 'relay_hold', 'solver', 'solver_commit',
           'solver_nograce', 'solver_noreset', 'solver_nocommit']
SEEDS = range(1, 51)
RF, RL = 150, 500
KEYS = ['seed', 'algo', 'system', 'leader_radius', 'follower_radius']
C.long_timeout()


def runs():
    out = []
    for seed in SEEDS:
        for algo in ('cbba', 'hungarian', 'grape'):
            for system in SYSTEMS:
                spec = {'yaml': C.dynamic_yaml(system, algo), 'seed': seed, 'max_ticks': C.MAX_TICKS[algo],
                        'leader_radius': RL, 'follower_radius': RF, **C.team_of(algo), **C.dynamic_bts(system, algo)}
                out.append(({'seed': seed, 'algo': algo, 'system': system,
                             'leader_radius': RL, 'follower_radius': RF}, spec))
    return out


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    C.run_campaign(runs(), KEYS, 'table2_chattering.csv', workers=workers)


if __name__ == '__main__':
    main()
