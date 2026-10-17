"""Tables 3 and 4: dynamic comparison on the 12-cell grid R_f {150, 325, 500} x R_L {150, 325, 500, 750},
seeds 1-50, main teams. Leader-as-proxy (both rules) from fig3_proxy_vs_deconly.csv (R_f 150, 500) and
table3_table4_dynamic.csv (R_f 325); Leader-as-relay (+iso) and Leader-as-solver (grace+reset+commit+iso) from the grid file.
Cells: proxy / baseline - 1 for travel and completion time (mean per-seed ratio; time over seeds completed by both),
with the paired 95% t-interval; proxy / relay for communication (ratio of means of fields per tick); completed runs.
Output: the screen and 04_results/table3_table4_dynamic.md. Run from anywhere: python table3_table4_dynamic.py
"""
import math
import pandas as pd
from scipy import stats
import _report as R

R.start(__file__)
D = R.DATA
NUM = ['mission_completion_time', 'total_distance_moved', 'mission_completed', 'chattering_episodes',
       'comm_follower_per_tick', 'comm_leader_per_tick', 'dup_tick_fraction', 'team_utility']


def wide(path):
    df = pd.read_csv(D + path, dtype=str)
    w = df.pivot_table(index=['seed', 'algo', 'system', 'leader_radius', 'follower_radius'], columns='metric_name',
                       values='value', aggfunc='first').reset_index()
    for c in NUM:
        w[c] = pd.to_numeric(w[c].replace({'True': '1', 'False': '0'}), errors='coerce')
    for c in ('leader_radius', 'follower_radius', 'seed'):
        w[c] = w[c].astype(int)
    return w


fig3 = wide('fig3_proxy_vs_deconly.csv'); grid = wide('table3_table4_dynamic.csv')
data = pd.concat([fig3[fig3.leader_radius > 0], grid])
# Dec-only (proxy tree at R_L = 0): R_f 150 / 500 from Fig. 3; R_f 325 is not in the paper
dec = [fig3[fig3.leader_radius == 0]]
dec = pd.concat(dec)
RF, RL = (150, 325, 500), (150, 325, 500, 750)
ALGOS = ('cbba', 'grape', 'hungarian')


def cell(algo, rf, rl, system):
    return data[(data.algo == algo) & (data.follower_radius == rf) & (data.leader_radius == rl) & (data.system == system)].set_index('seed')


def rel(x, b, col, both_done):
    idx = x.index.intersection(b.index)
    if both_done:
        idx = [s for s in idx if x.loc[s, 'mission_completed'] == 1 and b.loc[s, 'mission_completed'] == 1]
    r = (x.loc[idx, col] / b.loc[idx, col]).astype(float)
    if len(r) < 2:
        return float('nan'), False, len(r)
    m = r.mean() - 1; h = stats.t.ppf(0.975, len(r) - 1) * r.std(ddof=1) / math.sqrt(len(r))
    return m, (m - h > 0) or (m + h < 0), len(r)


def fmt(m, sig, n=None):
    s = f'{100*m:+.1f}%'
    if sig:
        s = f'**{s}**'
    return s + (f' ({n})' if n is not None and n < 50 else '')


# ── the paper's tables ────────────────────────────────────────────────────────
PAPER_ALGOS = (('hungarian', 'Hungarian'), ('cbba', 'CBBA'), ('grape', 'GRAPE'))
print('## Table 3: Travel distance and completion time of Leader-as-proxy relative to Solver and Relay.\n')
print('Mean per-seed Proxy / baseline ratios. Travel uses all 50 seeds; time uses seeds completed by both designs.\n')
hdr, out = ['Algorithm', 'R_f'], []
for bname in ('Proxy/Solver', 'Proxy/Relay'):
    for label in ('travel', 'time'):
        hdr += [f'{bname} {label} R_L={rl}' for rl in RL]
for algo, name in PAPER_ALGOS:
    for rf in RF:
        row = [name, rf]
        for base in ('solver_commit', 'relay_hold'):
            for col, both in (('total_distance_moved', False), ('mission_completion_time', True)):
                row += [f'{1 + rel(cell(algo, rf, rl, "hybrid_rules"), cell(algo, rf, rl, base), col, both)[0]:.3f}' for rl in RL]
        out.append(row)
R.table(hdr, out)

print('\n## Table 4: Communication of Leader-as-proxy relative to Leader-as-relay.\n')
print('Proxy / Relay ratios of mean fields broadcast per tick, summed over the leader and followers.\n')
out = []
for algo, name in PAPER_ALGOS:
    for rf in RF:
        row = [name, rf]
        for rl in RL:
            p, r = cell(algo, rf, rl, 'hybrid_rules'), cell(algo, rf, rl, 'relay_hold')
            row.append(f'{(p.comm_follower_per_tick + p.comm_leader_per_tick).mean() / (r.comm_follower_per_tick + r.comm_leader_per_tick).mean():.2f}')
        out.append(row)
R.table(['Algorithm', 'R_f'] + [f'R_L={rl}' for rl in RL], out)

# ── supporting numbers ────────────────────────────────────────────────────────
print('\n## Supporting numbers\n')
print('Completed runs (of 50): proxy / relay / solver.\n')
print('```')
for algo in ALGOS:
    rows = []
    for rf in RF:
        rows.append(f'R_f {rf}: ' + ', '.join(f"R_L {rl}: {int(cell(algo, rf, rl, 'hybrid_rules').mission_completed.sum())}/{int(cell(algo, rf, rl, 'relay_hold').mission_completed.sum())}/{int(cell(algo, rf, rl, 'solver_commit').mission_completed.sum())}" for rl in RL))
    print(algo, '|', ' | '.join(rows))
print('```')

for col, label, both in (('total_distance_moved', 'travel', False), ('mission_completion_time', 'completion time', True)):
    for base, bname in (('solver_commit', 'Leader-as-solver'), ('relay_hold', 'Leader-as-relay')):
        print(f'\n{label.capitalize()}: proxy / {bname} - 1 (bold: 95% CI excludes 0; (n) if fewer than 50 pairs).\n')
        print('| algo | R_f | ' + ' | '.join(f'R_L={rl}' for rl in RL) + ' |')
        print('|' + '---|' * (2 + len(RL)))
        for algo in ALGOS:
            for rf in RF:
                cells = []
                for rl in RL:
                    m, sig, n = rel(cell(algo, rf, rl, 'hybrid_rules'), cell(algo, rf, rl, base), col, both)
                    cells.append(fmt(m, sig, n))
                print(f'| {algo} | {rf} | ' + ' | '.join(cells) + ' |')
    print(f'\n{label.capitalize()}: proxy / Dec-only - 1 (Dec-only = proxy tree at R_L = 0; R_f 325 not run).\n')
    print('| algo | R_f | ' + ' | '.join(f'R_L={rl}' for rl in RL) + ' |')
    print('|' + '---|' * (2 + len(RL)))
    for algo in ALGOS:
        for rf in RF:
            base = dec[(dec.algo == algo) & (dec.follower_radius == rf)].set_index('seed')
            if base.empty:
                print(f'| {algo} | {rf} | ' + ' | '.join(['–'] * len(RL)) + ' |')
                continue
            cells = [fmt(*rel(cell(algo, rf, rl, 'hybrid_rules'), base, col, both)) for rl in RL]
            print(f'| {algo} | {rf} | ' + ' | '.join(cells) + ' |')

print('\nChattering runs (of 50): proxy / relay / solver, and solver duplicate-claim tick share / proxy.\n')
print('```')
for algo in ALGOS:
    rows = []
    for rf in RF:
        rows.append(f'R_f {rf}: ' + ', '.join(f"R_L {rl}: {int((cell(algo, rf, rl, 'hybrid_rules').chattering_episodes>0).sum())}/{int((cell(algo, rf, rl, 'relay_hold').chattering_episodes>0).sum())}/{int((cell(algo, rf, rl, 'solver_commit').chattering_episodes>0).sum())} dup x{cell(algo, rf, rl, 'solver_commit').dup_tick_fraction.mean()/max(cell(algo, rf, rl, 'hybrid_rules').dup_tick_fraction.mean(),1e-9):.1f}" for rl in RL))
    print(algo, '|', ' | '.join(rows))

print('```')
print('\nTeam utility (as recorded at run time): solver / proxy - 1, relay / proxy - 1.\n')
print('```')
for algo in ALGOS:
    rows = []
    for rf in RF:
        rows.append(f'R_f {rf}: ' + ', '.join(f"R_L {rl}: {100*(rel(cell(algo, rf, rl, 'solver_commit'), cell(algo, rf, rl, 'hybrid_rules'), 'team_utility', False)[0]):+.1f}% / {100*(rel(cell(algo, rf, rl, 'relay_hold'), cell(algo, rf, rl, 'hybrid_rules'), 'team_utility', False)[0]):+.1f}%" for rl in RL))
    print(algo, '|', ' | '.join(rows))
print('```')
