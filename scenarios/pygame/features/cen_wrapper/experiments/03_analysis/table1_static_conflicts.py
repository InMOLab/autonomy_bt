"""Table 1: static boundary conflicts (R_f = R_L = 500, the 50 seeds of table1_seeds.json), CBBA and Hungarian.
Leader-as-proxy with each boundary flow switched off (table1_proxy_ablation.csv); Leader-as-solver with its two boundary
slots switched off ([RelayIn] = RelayMessages, [EmitOut]/[EmitDec] = ForwardCenAllocation; table1_solver_slots.csv) and
both on (table1_solver.csv); Leader-as-relay and Dec-only (R_L = 0) (table1_relay_deconly.csv).
A conflict is a task claimed by two or more followers in the final allocation (`overclaimed`).
Output: the screen and 04_results/table1_static_conflicts.md. Run from anywhere: python table1_static_conflicts.py
"""
import json
import pandas as pd
import _report as R

R.start(__file__)
D = R.DATA
SEL = json.load(open(D + 'table1_seeds.json'))
SEEDS, FOLL, LONLY = set(SEL['seeds']), set(SEL['follower_connected']), set(SEL['leader_only'])
NUM = ['overclaimed', 'unclaimed', 'converged', 'cen_cen', 'cen_dec', 'dec_dec_same', 'dec_dec_split', 'last_change_tick']


def wide(path, keys):
    df = pd.read_csv(D + path, dtype={'value': str})
    w = df.pivot_table(index=keys, columns='metric_name', values='value', aggfunc='first').reset_index()
    for c in NUM:
        if c in w:
            w[c] = pd.to_numeric(w[c].replace({'True': '1', 'False': '0'}), errors='coerce')
    w['seed'] = w['seed'].astype(int)
    return w[w.seed.isin(SEEDS)]


rows = []   # (design, condition label, frame filtered to one algorithm later)
b1 = wide('table1_proxy_ablation.csv', ['seed', 'algo', 'condition'])
for cond, label in (('none', 'neither'), ('inbound_only', 'inbound relay only'), ('outbound_only', 'outbound emission only'),
                    ('both', 'both')):
    rows.append(('Leader-as-proxy', label, b1[b1.condition == cond]))
slots = wide('table1_solver_slots.csv', ['seed', 'algo', 'system', 'leader_radius', 'follower_radius', 'condition'])
fix = wide('table1_solver.csv', ['seed', 'algo', 'system', 'leader_radius', 'follower_radius'])
for cond, label in (('none', 'neither'), ('relay_only', 'relay only'), ('forward_only', 'plan forwarding only')):
    rows.append(('Leader-as-solver', label, slots[slots.condition == cond]))
rows.append(('Leader-as-solver', 'both', fix))
cmpd = wide('table1_relay_deconly.csv', ['seed', 'algo', 'system', 'leader_radius', 'follower_radius'])
rows.append(('Leader-as-relay', '-', cmpd[cmpd.system == 'relay']))
rows.append(('Dec-only', '-', cmpd[cmpd.system == 'dec']))

# ── the paper's table ─────────────────────────────────────────────────────────
print('## Table 1: Static boundary conflicts under mechanism ablation.\n')
print('R_L = R_f = 500. Mean final conflicts over the n seeds of the group, with the number of seeds having at least one '
      'conflict in parentheses. Proxy: In = inbound relay, Out = outbound emission. Solver: In = relay, '
      'Plan = plan forwarding.\n')
paper_cols = [('Proxy Neither', 0), ('Proxy In', 1), ('Proxy Out', 2), ('Proxy Both', 3), ('Solver Neither', 4),
              ('Solver In', 5), ('Solver Plan', 6), ('Solver Both', 7), ('Relay Full', 8), ('Dec-only Full', 9)]


def mean_cell(x, group):
    x = x[x.seed.isin(group)]
    if x.empty:
        return '–'
    mean, k = x.overclaimed.sum() / x.seed.nunique(), int((x.overclaimed > 0).sum())
    return '0 (0)' if mean == 0 else f'{mean:.2f} ({k})'


out = []
for algo, name in (('hungarian', 'Hungarian'), ('cbba', 'CBBA')):
    for group, gname in ((FOLL, f'Follower-connected ({len(FOLL)})'), (LONLY, f'Leader-dependent ({len(LONLY)})')):
        out.append([name, gname] + [mean_cell(rows[i][2][rows[i][2].algo == algo], group) for _, i in paper_cols])
R.table(['Algorithm', 'Connectivity (n)'] + [c for c, _ in paper_cols], out)


# ── supporting numbers ────────────────────────────────────────────────────────
def cell(x, group):
    x = x[x.seed.isin(group)]
    if x.empty:
        return '–'
    return f"{int(x.overclaimed.sum())} ({int((x.overclaimed > 0).sum())}/{x.seed.nunique()})"


print('\n## Supporting numbers\n')
print('Total conflicts (seeds with at least one conflict / seeds), for all 50 seeds and per group.\n')
R.table(['Design', 'Condition', 'CBBA all 50', 'CBBA 45', 'CBBA 5', 'Hungarian all 50', 'Hungarian 45', 'Hungarian 5'],
        [[design, label] + [cell(frame[frame.algo == a], g) for a in ('cbba', 'hungarian') for g in (SEEDS, FOLL, LONLY)]
         for design, label, frame in rows])

print('\nLeader-as-solver: conflict types, unassigned tasks and convergence (all 50 seeds).\n')
sup = []
for design, label, frame in rows:
    if design != 'Leader-as-solver':
        continue
    for a in ('cbba', 'hungarian'):
        x = frame[frame.algo == a]
        if x.empty:
            continue
        sup.append([a, label, int(x.cen_dec.sum()), int(x.dec_dec_same.sum()), int(x.dec_dec_split.sum()), int(x.cen_cen.sum()),
                    int(x.unclaimed.sum()), f'{int(x.converged.sum())}/{len(x)}', f'{x.last_change_tick.median():.0f}'])
R.table(['Algorithm', 'Slots', 'cen_dec', 'dec_dec_same', 'dec_dec_split', 'cen_cen', 'Unassigned', 'Converged',
         'Median convergence tick'], sup)
