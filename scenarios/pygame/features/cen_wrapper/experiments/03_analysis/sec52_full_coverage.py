"""Section 5.2, first paragraph: full-coverage equivalence (static, every radius 2000, seeds 1-50, main teams).
Leader-as-proxy (`wrapper`) is compared with decentralised-only execution (`dec`) and with Leader-as-solver
(`baseline`); an instance counts when the final allocations are identical.
Data: 02_data/sec52_full_coverage.csv (01_scripts/run_sec52_full_coverage.py).
Output: the screen and 04_results/sec52_full_coverage.md. Run from anywhere: python sec52_full_coverage.py
"""
import pandas as pd
import _report as R

R.start(__file__)
df = pd.read_csv(R.DATA + 'sec52_full_coverage.csv', dtype={'value': str})
data = df.pivot_table(index=['seed', 'algo', 'mode'], columns='metric_name', values='value', aggfunc='first').reset_index()
for c in ('converged', 'last_change_tick'):
    data[c] = pd.to_numeric(data[c].replace({'True': '1', 'False': '0'}), errors='coerce')

paper, support = [], []
for algo, name in (('cbba', 'CBBA'), ('grape', 'GRAPE'), ('hungarian', 'Hungarian')):
    g = data[data.algo == algo]
    m = {mode: g[g['mode'] == mode].set_index('seed') for mode in ('dec', 'wrapper', 'baseline')}
    common = m['dec'].index.intersection(m['wrapper'].index).intersection(m['baseline'].index)
    a = {k: v.loc[common] for k, v in m.items()}
    same_dec = int((a['wrapper'].allocation.fillna('') == a['dec'].allocation.fillna('')).sum())
    same_cen = int((a['wrapper'].allocation.fillna('') == a['baseline'].allocation.fillna('')).sum())
    paper.append((name, len(common), same_dec, same_cen))
    support.append((name, f"{int(sum((a[k].converged == 1).sum() for k in a))} / {3 * len(common)}",
                    f"{a['wrapper'].last_change_tick.mean():.1f}", f"{a['dec'].last_change_tick.mean():.1f}",
                    f"{a['baseline'].last_change_tick.mean():.1f}"))

print('## Section 5.2: full-coverage equivalence (R_L = R_f = 2000, static)\n')
print('Instances where the final allocation of Leader-as-proxy equals that of the reference.\n')
R.table(['Algorithm', 'Instances', 'Proxy = Dec-only', 'Proxy = Leader-as-solver'], paper)
print(f'\nTotal: {sum(r[2] for r in paper)} / {sum(r[1] for r in paper)} and {sum(r[3] for r in paper)} / {sum(r[1] for r in paper)}.')

print('\n## Supporting numbers\n')
print('Converged runs, and the mean tick of the last allocation change.\n')
R.table(['Algorithm', 'Converged runs', 'Last change: proxy', 'Dec-only', 'Leader-as-solver'], support)
