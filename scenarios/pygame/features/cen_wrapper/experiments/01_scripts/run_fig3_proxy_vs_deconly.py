"""Figure 3: Leader-as-proxy relative to decentralised-only against the leader radius.

Dynamic, Leader-as-proxy with both rules (hybrid_rules), R_L in {0, 150, 325, 500, 750} x R_f in {150, 500}, seeds 1-50,
CBBA / GRAPE / Hungarian with the teams of common.team_of. R_L = 0 is Dec-only: the same trees with no follower in the
leader's range (the runner uses radius 0.1).

Run from autonomy_bt/ (resumable):
  python scenarios/pygame/features/cen_wrapper/experiments/01_scripts/run_fig3_proxy_vs_deconly.py [workers]
Output: 02_data/fig3_proxy_vs_deconly.csv (also the Leader-as-proxy cells at R_f 150 and 500 of Tables 3 and 4)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SEEDS = range(1, 51)
RL = [0, 150, 325, 500, 750]
RF = [150, 500]
SYSTEM = 'hybrid_rules'
KEYS = ['seed', 'algo', 'system', 'leader_radius', 'follower_radius']
C.long_timeout()


def runs():
    out = []
    for seed in SEEDS:
        for algo in ('cbba', 'hungarian', 'grape'):
            for rf in RF:
                for rl in RL:
                    spec = {'yaml': C.dynamic_yaml(SYSTEM, algo), 'seed': seed,
                            'max_ticks': C.MAX_TICKS[algo], 'leader_radius': rl, 'follower_radius': rf,
                            **C.team_of(algo), **C.dynamic_bts(SYSTEM, algo)}
                    out.append(({'seed': seed, 'algo': algo, 'system': SYSTEM, 'leader_radius': rl,
                                 'follower_radius': rf}, spec))
    return out


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    C.run_campaign(runs(), KEYS, 'fig3_proxy_vs_deconly.csv', workers=workers)


if __name__ == '__main__':
    main()
