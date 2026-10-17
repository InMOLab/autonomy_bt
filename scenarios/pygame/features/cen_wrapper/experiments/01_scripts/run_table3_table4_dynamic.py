"""Tables 3 and 4: Leader-as-proxy against Leader-as-solver and Leader-as-relay (travel, completion time, communication).

Dynamic, R_f in {150, 325, 500} x R_L in {150, 325, 500, 750}, seeds 1-50, CBBA / GRAPE / Hungarian with the teams of
common.team_of. Designs: hybrid_rules (Leader-as-proxy, adopt + iso), relay_hold (Leader-as-relay + iso), solver_commit
(Leader-as-solver, grace + reset + commit + iso). Leader-as-proxy at R_f 150 and 500 comes from Figure 3's runs
(run_fig3_proxy_vs_deconly.py), so only its R_f 325 cells are run here.

Run from autonomy_bt/ (resumable; run run_fig3_proxy_vs_deconly.py too):
  python scenarios/pygame/features/cen_wrapper/experiments/01_scripts/run_table3_table4_dynamic.py [workers]
Output: 02_data/table3_table4_dynamic.csv
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SEEDS = range(1, 51)
RF = [150, 325, 500]
RL = [150, 325, 500, 750]
KEYS = ['seed', 'algo', 'system', 'leader_radius', 'follower_radius']
C.long_timeout()


def runs():
    out = []
    for system, rfs in (('hybrid_rules', [325]), ('relay_hold', RF), ('solver_commit', RF)):
        for seed in SEEDS:
            for algo in ('cbba', 'hungarian', 'grape'):
                for rf in rfs:
                    for rl in RL:
                        spec = {'yaml': C.dynamic_yaml(system, algo), 'seed': seed, 'max_ticks': C.MAX_TICKS[algo],
                                'leader_radius': rl, 'follower_radius': rf, **C.team_of(algo), **C.dynamic_bts(system, algo)}
                        out.append(({'seed': seed, 'algo': algo, 'system': system, 'leader_radius': rl,
                                     'follower_radius': rf}, spec))
    return out


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    C.run_campaign(runs(), KEYS, 'table3_table4_dynamic.csv', workers=workers)


if __name__ == '__main__':
    main()
