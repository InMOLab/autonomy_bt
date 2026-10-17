"""Figure 3: Leader-as-proxy (both rules) relative to Dec-only (R_L = 0) against the leader radius,
dynamic, R_f in {150, 500}, R_L in {0, 150, 325, 500, 750}, seeds 1-50, main teams. Data: 02_data/fig3_proxy_vs_deconly.csv.
Value: mean per-seed ratio proxy / Dec-only (travel over all seeds; completion time over seeds completed by both), with
the paired 95% t-interval of the ratio. The figure's error bars are +(upper - mean) / -(mean - lower) of the rounded values.
Output: the screen and 04_results/fig3_proxy_vs_deconly.md. Run from anywhere: python fig3_proxy_vs_deconly.py
"""
import math
import pandas as pd
from scipy import stats
import _report as R

R.start(__file__)
df = pd.read_csv(R.DATA + 'fig3_proxy_vs_deconly.csv', dtype=str)
w = df.pivot_table(index=['seed', 'algo', 'system', 'leader_radius', 'follower_radius'], columns='metric_name',
                   values='value', aggfunc='first').reset_index()
for c in ('mission_completion_time', 'total_distance_moved', 'mission_completed', 'chattering_episodes'):
    w[c] = pd.to_numeric(w[c].replace({'True': '1', 'False': '0'}), errors='coerce')
for c in ('leader_radius', 'follower_radius', 'seed'):
    w[c] = w[c].astype(int)
ALGOS = (('cbba', 'CBBA'), ('grape', 'GRAPE'), ('hungarian', 'Hungarian'))
RL = (150, 325, 500, 750)


def ratio(x, base, col, both_done):
    idx = x.index.intersection(base.index)
    if both_done:
        idx = [s for s in idx if x.loc[s, 'mission_completed'] == 1 and base.loc[s, 'mission_completed'] == 1]
    r = (x.loc[idx, col] / base.loc[idx, col]).astype(float)
    if len(r) < 2:
        return float('nan'), float('nan'), float('nan'), len(r)
    m = r.mean(); h = stats.t.ppf(0.975, len(r) - 1) * r.std(ddof=1) / math.sqrt(len(r))
    return m, m - h, m + h, len(r)


res = {}   # (panel, algo, rf, rl) -> (mean, lower, upper, n)
for col, panel, both in (('total_distance_moved', 'a', False), ('mission_completion_time', 'b', True)):
    for algo, _ in ALGOS:
        for rf in (150, 500):
            base = w[(w.algo == algo) & (w.follower_radius == rf) & (w.leader_radius == 0)].set_index('seed')
            for rl in RL:
                x = w[(w.algo == algo) & (w.follower_radius == rf) & (w.leader_radius == rl)].set_index('seed')
                res[(panel, algo, rf, rl)] = ratio(x, base, col, both)

# ── the paper's figure ────────────────────────────────────────────────────────
print('## Figure 3: Leader-as-proxy travel distance and mission completion time relative to decentralised-only.\n')
print('Mean per-seed ratio Proxy / Dec-only with the 95% error bar as +upper / -lower. R_L = 0 is Dec-only (ratio 1). '
      'Solid lines in the figure: R_f = 150; dashed: R_f = 500.')
for panel, title in (('a', '(a) Travel distance (all seeds)'), ('b', '(b) Mission completion time (seeds completed by both)')):
    print(f'\n### {title}\n')
    out = []
    for algo, name in ALGOS:
        for rf in (150, 500):
            cells = ['1.000']
            for rl in RL:
                m, lo, hi, n = res[(panel, algo, rf, rl)]
                mr, lr, hr = round(m, 3), round(lo, 3), round(hi, 3)
                cells.append(f'{mr:.3f} (+{hr - mr:.3f} / -{mr - lr:.3f})')
            out.append([name, rf] + cells)
    R.table(['Algorithm', 'R_f', 'R_L=0', 'R_L=150', 'R_L=325', 'R_L=500', 'R_L=750'], out)

# ── supporting numbers ────────────────────────────────────────────────────────
print('\n## Supporting numbers\n')
for panel, title in (('a', 'Travel'), ('b', 'Completion time')):
    print(f'{title}: mean per-seed ratio [95% CI] (number of seed pairs).\n')
    R.table(['Algorithm', 'R_f'] + [f'R_L={rl}' for rl in RL],
            [[name, rf] + ['{:.3f} [{:.3f}, {:.3f}] ({})'.format(*res[(panel, algo, rf, rl)]) for rl in RL]
             for algo, name in ALGOS for rf in (150, 500)])
    print()
print('Leader-as-proxy runs (all R_L > 0 and R_L = 0): completed missions and runs with chattering.\n')
R.table(['Algorithm', 'Completed', 'Runs with chattering'],
        [[name, f"{int(x.mission_completed.sum())}/{len(x)}", int((x.chattering_episodes > 0).sum())]
         for algo, name in ALGOS for x in [w[(w.algo == algo) & (w.system == 'hybrid_rules')]]])
