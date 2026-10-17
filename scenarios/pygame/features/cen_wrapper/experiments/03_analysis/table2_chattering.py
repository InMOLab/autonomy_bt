"""Table 2: boundary chattering (dynamic, R_f = 150, R_L = 500, seeds 1-50) with the main teams
(CBBA 15/60 in the static CBBA task region, Hungarian 15/15, GRAPE 40/10) and the Leader-as-solver ablation (each of
grace, reset, commit switched off).
A chattering episode: at least four range crossings by one follower with consecutive gaps below ten ticks.
Data: 02_data/table2_chattering.csv.
Output: the screen and 04_results/table2_chattering.md. Run from anywhere: python table2_chattering.py
"""
import pandas as pd
import _report as R

R.start(__file__)
D = R.DATA
NUM = ['chattering_episodes', 'chattering_crossings', 'mission_completed', 'mission_completion_time', 'ticks',
       'total_distance_moved', 'dup_tick_fraction', 'range_crossings', 'tasks_completed']
ROWS = [('Leader-as-proxy', 'none', 'hybrid'), ('Leader-as-proxy', 'iso', 'hybrid_iso'),
        ('Leader-as-proxy', 'adopt', 'hybrid_adopt'), ('Leader-as-proxy', 'both ◆', 'hybrid_rules'),
        ('Leader-as-relay', 'none', 'relay'), ('Leader-as-relay', '+iso ◆', 'relay_hold'),
        ('Leader-as-solver', 'none', 'solver'), ('Leader-as-solver', 'no grace (reset+commit)', 'solver_nograce'),
        ('Leader-as-solver', 'no reset (grace+commit)', 'solver_noreset'),
        ('Leader-as-solver', 'no commit (grace+reset+iso)', 'solver_nocommit'), ('Leader-as-solver', 'all ◆ (grace+reset+commit+iso)', 'solver_commit')]
ALGOS = ('cbba', 'grape', 'hungarian')


def wide(path, keys, label=None):
    df = pd.read_csv(D + path, dtype=str)
    w = df.pivot_table(index=keys, columns='metric_name', values='value', aggfunc='first').reset_index()
    for c in NUM:
        if c in w:
            w[c] = pd.to_numeric(w[c].replace({'True': '1', 'False': '0'}), errors='coerce')
    if label:
        w = w.rename(columns={label: 'system'})
    return w


data = wide('table2_chattering.csv', ['seed', 'algo', 'system', 'leader_radius', 'follower_radius'])


def cell(algo, system):
    x = data[(data.algo == algo) & (data.system == system)]
    if x.empty:
        return None
    return {'n': x.seed.nunique(), 'chat_runs': int((x.chattering_episodes > 0).sum()),
            'chat_cross': int(x.chattering_crossings.sum()), 'done': int(x.mission_completed.sum()),
            'dup': x.dup_tick_fraction.mean(), 'time': x.mission_completion_time.mean(), 'dist': x.total_distance_moved.mean()}


# ── the paper's table ─────────────────────────────────────────────────────────
print('## Table 2: Boundary chattering under mechanism ablation.\n')
print('R_f = 150, R_L = 500. Runs with at least one chattering episode among 50 seeds; parentheses give the total '
      'boundary crossings during those episodes. Solver All = grace + reset + commit + iso; All - commit disables commit.\n')
PAPER_COLS = [('Proxy None', 'hybrid'), ('Proxy iso', 'hybrid_iso'), ('Proxy adopt', 'hybrid_adopt'), ('Proxy Both', 'hybrid_rules'),
              ('Relay None', 'relay'), ('Relay iso', 'relay_hold'), ('Solver None', 'solver'),
              ('Solver All - commit', 'solver_nocommit'), ('Solver All', 'solver_commit')]


def paper_cell(algo, system):
    c = cell(algo, system)
    return '–' if c is None else (f"{c['chat_runs']} ({c['chat_cross']})" if c['chat_runs'] else '0')


R.table(['Algorithm'] + [c for c, _ in PAPER_COLS],
        [[name] + [paper_cell(a, s) for _, s in PAPER_COLS] for a, name in (('hungarian', 'Hungarian'), ('cbba', 'CBBA'), ('grape', 'GRAPE'))])
print('\nCompleted missions (of 50) in the same configurations:\n')
R.table(['Algorithm'] + [c for c, _ in PAPER_COLS],
        [[name] + [cell(a, s)['done'] for _, s in PAPER_COLS] for a, name in (('hungarian', 'Hungarian'), ('cbba', 'CBBA'), ('grape', 'GRAPE'))])

# ── supporting numbers ────────────────────────────────────────────────────────
print('\n## Supporting numbers\n')
print('All eleven configurations: runs with chattering (crossings inside episodes) and completed missions.\n')
R.table(['Design', 'Rules'] + list(ALGOS),
        [[design, rule] + ['–' if cell(a, system) is None else
                           f"{cell(a, system)['chat_runs']}" + (f" ({cell(a, system)['chat_cross']})" if cell(a, system)['chat_runs'] else '')
                           + f" · done {cell(a, system)['done']}/{cell(a, system)['n']}" for a in ALGOS]
         for design, rule, system in ROWS])

print('\nLeader-as-solver rows: duplicate-claim tick share (mean), completion time and travel relative to all three rules.\n')
print('```')
for a in ALGOS:
    ref = data[(data.algo == a) & (data.system == 'solver_commit')].set_index('seed')
    for design, rule, system in ROWS:
        if design != 'Leader-as-solver':
            continue
        x = data[(data.algo == a) & (data.system == system)].set_index('seed')
        if x.empty:
            continue
        both = x.index.intersection(ref.index)
        both_done = [s for s in both if x.loc[s, 'mission_completed'] == 1 and ref.loc[s, 'mission_completed'] == 1]
        rt = (x.loc[both_done, 'mission_completion_time'] / ref.loc[both_done, 'mission_completion_time']).mean() - 1 if both_done else float('nan')
        rd = (x.loc[both, 'total_distance_moved'] / ref.loc[both, 'total_distance_moved']).mean() - 1
        print(f"{a:9s} {rule:26s} dup {x.dup_tick_fraction.mean():.3f}  done {int(x.mission_completed.sum())}/{len(x)}  "
              f"time vs ◆ {100*rt:+.1f}% (n={len(both_done)})  travel vs ◆ {100*rd:+.1f}%")

print('```')
print('\nLeader-as-proxy rows: completion time and travel relative to no rule (mean per-seed ratio - 1).\n')
print('```')
for a in ALGOS:
    ref = data[(data.algo == a) & (data.system == 'hybrid')].set_index('seed')
    for system in ('hybrid_iso', 'hybrid_adopt', 'hybrid_rules'):
        x = data[(data.algo == a) & (data.system == system)].set_index('seed')
        if x.empty:
            continue
        idx = x.index.intersection(ref.index)
        print(f"{a:9s} {system:13s} time {100*((x.loc[idx,'mission_completion_time']/ref.loc[idx,'mission_completion_time']).mean()-1):+.1f}%  "
              f"travel {100*((x.loc[idx,'total_distance_moved']/ref.loc[idx,'total_distance_moved']).mean()-1):+.1f}%")
print('```')
