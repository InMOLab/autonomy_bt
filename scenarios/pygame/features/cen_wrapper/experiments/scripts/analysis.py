"""Analysis for Exp 2 (Dynamic Equivalence) and Exp 4 (Leader Radius Sweep).

Loads CSV results, produces:
  - per-metric box plots (PNG, one per metric, with 3 algorithm subplots)
  - descriptive statistics table (printed; can be redirected to result.md)
  - statistical tests (Exp 2 only):
      * TOST (Two One-Sided Tests) for mission-level equivalence
      * Paired Wilcoxon signed-rank for agent-level paired comparison

Run from project root (autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/analysis.py
"""
import itertools
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as ss

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
EXP_DIR = os.path.join(SCEN_ROOT, 'experiments')
DATA_DIR = os.path.join(EXP_DIR, 'data')
FIG_DIR = os.path.join(EXP_DIR, 'figures')

ALGO_ORDER = ['cbba', 'grape', 'hungarian']
MODE_ORDER = ['dec', 'wrapper', 'baseline']
MODE_COLOR = {'dec': '#4C72B0', 'wrapper': '#DD8452', 'baseline': '#55A868'}

EXP1_METRICS = [
    ('mission_completion_time',   'Mission completion time (sim ticks)', 'mission'),
    ('total_distance_moved',      'Total distance moved (Σ followers)',  'mission'),
    ('per_agent_distance_moved',  'Per-agent distance moved',            'agent'),
    ('per_agent_task_amount_done','Per-agent task amount done',          'agent'),
    ('decision_phase_ticks',      'Decision phase ticks (until first motion)', 'mission'),
    ('movement_phase_ticks',      'Movement phase ticks (until mission complete)', 'mission'),
    ('wall_clock_seconds',        'Wall-clock (s)',                       'mission'),
]


def boxplot_per_metric(df: pd.DataFrame, metric: str, ylabel: str,
                       out_path: str, title_prefix: str = 'Exp 2') -> None:
    """One PNG with 3 subplots (one per algorithm), each a box plot
    of the metric by mode.
    """
    sub = df[df['metric_name'] == metric]
    fig, axes = plt.subplots(1, len(ALGO_ORDER), figsize=(13, 4), sharey=False)
    for ax, algo in zip(axes, ALGO_ORDER):
        algo_sub = sub[sub['algo'] == algo]
        data_per_mode = [algo_sub[algo_sub['mode'] == m]['value'].values for m in MODE_ORDER]
        bp = ax.boxplot(data_per_mode, tick_labels=MODE_ORDER, patch_artist=True, widths=0.55)
        for patch, mode in zip(bp['boxes'], MODE_ORDER):
            patch.set_facecolor(MODE_COLOR[mode])
            patch.set_alpha(0.65)
        for median in bp['medians']:
            median.set_color('black')
            median.set_linewidth(1.6)
        ax.set_title(f'{algo.upper()}', fontsize=11)
        ax.grid(axis='y', linestyle=':', alpha=0.5)
        if ax is axes[0]:
            ax.set_ylabel(ylabel)
    fig.suptitle(f'{title_prefix} — {metric}', fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def descriptive_table(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Mean ± std per (algo, mode), plus n samples."""
    sub = df[df['metric_name'] == metric].copy()
    grouped = sub.groupby(['algo', 'mode'])['value'].agg(['mean', 'std', 'count']).reset_index()
    grouped['mean'] = grouped['mean'].round(2)
    grouped['std'] = grouped['std'].round(2)
    return grouped


def print_stats(df: pd.DataFrame) -> str:
    """Returns a markdown-formatted stats table string for all metrics."""
    lines = []
    for metric, _label, _scope in EXP1_METRICS:
        lines.append(f'\n### `{metric}`\n')
        tbl = descriptive_table(df, metric)
        # Pivot for nicer display: rows = algo, cols = mode, cell = mean ± std
        rows = []
        for algo in ALGO_ORDER:
            row = [algo.upper()]
            for mode in MODE_ORDER:
                cell = tbl[(tbl['algo'] == algo) & (tbl['mode'] == mode)]
                if cell.empty:
                    row.append('—')
                else:
                    m = cell['mean'].iloc[0]
                    s = cell['std'].iloc[0]
                    n = int(cell['count'].iloc[0])
                    row.append(f'{m:.2f} ± {s:.2f}  (n={n})')
            rows.append(row)
        # Markdown table
        header = '| algo | ' + ' | '.join(MODE_ORDER) + ' |'
        sep = '|' + '|'.join(['---'] * (1 + len(MODE_ORDER))) + '|'
        lines.append(header)
        lines.append(sep)
        for r in rows:
            lines.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(lines) + '\n'


def sweep_curve_per_metric(df: pd.DataFrame, metric: str, ylabel: str,
                           out_path: str, title_prefix: str = 'Exp 4') -> None:
    """One PNG with 3 subplots (one per algorithm), each a line plot
    of metric (mean ± std band) over Leader.communication_radius.
    """
    sub = df[df['metric_name'] == metric]
    fig, axes = plt.subplots(1, len(ALGO_ORDER), figsize=(13, 4), sharey=False)
    for ax, algo in zip(axes, ALGO_ORDER):
        algo_sub = sub[sub['algo'] == algo]
        agg = (algo_sub.groupby('leader_radius')['value']
                       .agg(['mean', 'std', 'count']).reset_index()
                       .sort_values('leader_radius'))
        x = agg['leader_radius'].values
        m = agg['mean'].values
        s = agg['std'].fillna(0.0).values
        ax.plot(x, m, marker='o', color='#DD8452', linewidth=1.6, label='wrapper')
        ax.fill_between(x, m - s, m + s, color='#DD8452', alpha=0.18)
        ax.set_title(f'{algo.upper()}', fontsize=11)
        ax.set_xlabel('Leader.communication_radius')
        ax.grid(linestyle=':', alpha=0.5)
        if ax is axes[0]:
            ax.set_ylabel(ylabel)
    fig.suptitle(f'{title_prefix} — {metric}', fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def descriptive_table_exp2(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """For Exp 4: mean ± std per (algo, leader_radius)."""
    sub = df[df['metric_name'] == metric].copy()
    grouped = sub.groupby(['algo', 'leader_radius'])['value'].agg(
        ['mean', 'std', 'count']
    ).reset_index()
    grouped['mean'] = grouped['mean'].round(2)
    grouped['std'] = grouped['std'].round(2)
    return grouped


def print_stats_exp2(df: pd.DataFrame) -> str:
    radii = sorted(df['leader_radius'].unique(), reverse=True)  # 2000 -> 0
    lines = []
    for metric, _label, _scope in EXP1_METRICS:
        lines.append(f'\n### `{metric}`\n')
        tbl = descriptive_table_exp2(df, metric)
        header = '| algo | ' + ' | '.join(f'r={int(r)}' for r in radii) + ' |'
        sep = '|' + '|'.join(['---'] * (1 + len(radii))) + '|'
        lines.append(header)
        lines.append(sep)
        for algo in ALGO_ORDER:
            row = [algo.upper()]
            for r in radii:
                cell = tbl[(tbl['algo'] == algo) & (tbl['leader_radius'] == r)]
                if cell.empty:
                    row.append('—')
                else:
                    m = cell['mean'].iloc[0]
                    s = cell['std'].iloc[0]
                    row.append(f'{m:.0f} ± {s:.0f}')
            lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines) + '\n'


# ───────────── Statistical tests (Stage c) ──────────────────────────

def tost_paired(x, y, delta):
    """Two One-Sided Tests on paired samples for equivalence within ±delta.

    Returns (mean_diff, p_tost). p_tost is max of the two one-sided
    t-test p-values; if p_tost < alpha, equivalence at margin delta is
    established.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    diff = x - y
    n = len(diff)
    if n < 2:
        return np.nan, np.nan
    mean_diff = diff.mean()
    se = diff.std(ddof=1) / np.sqrt(n)
    if se == 0:
        # Identical paired samples ⇒ trivially equivalent
        return mean_diff, 0.0 if abs(mean_diff) < delta else 1.0
    df_t = n - 1
    # H0: mean_diff <= -delta
    p_lower = 1.0 - ss.t.cdf((mean_diff + delta) / se, df=df_t)
    # H0: mean_diff >= +delta
    p_upper = ss.t.cdf((mean_diff - delta) / se, df=df_t)
    return mean_diff, max(p_lower, p_upper)


def paired_tost_per_algo(df, metric, mode_a, mode_b, delta_rel=0.05):
    """Per-algo paired TOST on mission-level metric. Returns dict
    {algo: (mean_diff_pct, delta_abs, p_tost, n_pairs)}.
    """
    out = {}
    sub = df[df.metric_name == metric]
    for algo in ALGO_ORDER:
        a = sub[(sub.algo == algo) & (sub['mode'] == mode_a)][['seed', 'value']]
        b = sub[(sub.algo == algo) & (sub['mode'] == mode_b)][['seed', 'value']]
        m = a.merge(b, on='seed', suffixes=('_a', '_b'))
        if m.empty:
            out[algo] = (np.nan, np.nan, np.nan, 0)
            continue
        pooled_mean = (m.value_a.mean() + m.value_b.mean()) / 2.0
        delta = delta_rel * pooled_mean
        mean_diff, p = tost_paired(m.value_a.values, m.value_b.values, delta)
        diff_pct = 100.0 * mean_diff / pooled_mean if pooled_mean != 0 else np.nan
        out[algo] = (diff_pct, delta, p, len(m))
    return out


def paired_wilcoxon_per_algo(df, metric, mode_a, mode_b):
    """Per-algo paired Wilcoxon signed-rank on per-(seed, agent) metric.
    Returns dict {algo: (median_diff, p_wilcoxon, n_pairs)}.
    """
    out = {}
    sub = df[df.metric_name == metric]
    for algo in ALGO_ORDER:
        a = sub[(sub.algo == algo) & (sub['mode'] == mode_a)][['seed', 'agent_id', 'value']]
        b = sub[(sub.algo == algo) & (sub['mode'] == mode_b)][['seed', 'agent_id', 'value']]
        m = a.merge(b, on=['seed', 'agent_id'], suffixes=('_a', '_b'))
        if m.empty:
            out[algo] = (np.nan, np.nan, 0)
            continue
        diff = m.value_a.values - m.value_b.values
        median_diff = float(np.median(diff))
        if np.all(diff == 0):
            out[algo] = (0.0, 1.0, len(m))
            continue
        try:
            res = ss.wilcoxon(diff, zero_method='wilcox', alternative='two-sided')
            out[algo] = (median_diff, float(res.pvalue), len(m))
        except ValueError:
            out[algo] = (median_diff, np.nan, len(m))
    return out


def print_tost_table(df, metric, label, delta_rel=0.05):
    """Markdown table: rows = algo, cols = mode pair, cell = Δ% (TOST p)."""
    pairs = [('dec', 'wrapper'), ('dec', 'baseline'), ('wrapper', 'baseline')]
    lines = [f'\n#### `{metric}` (TOST, equivalence margin δ = {delta_rel*100:.0f}% of pooled mean)\n']
    header = '| algo | ' + ' | '.join(f'{a}↔{b}' for a, b in pairs) + ' |'
    sep = '|' + '|'.join(['---'] * (1 + len(pairs))) + '|'
    lines.append(header)
    lines.append(sep)
    for algo in ALGO_ORDER:
        row = [algo.upper()]
        for a, b in pairs:
            res = paired_tost_per_algo(df, metric, a, b, delta_rel)
            diff_pct, delta_abs, p, n = res[algo]
            mark = '✓' if (not np.isnan(p) and p < 0.05) else '✗' if not np.isnan(p) else '—'
            row.append(f'Δ={diff_pct:+.2f}%, p={p:.3g} {mark}')
        lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines) + '\n'


def print_wilcoxon_table(df, metric, label):
    """Markdown table: rows = algo, cols = mode pair, cell = median diff (Wilcoxon p)."""
    pairs = [('dec', 'wrapper'), ('dec', 'baseline'), ('wrapper', 'baseline')]
    lines = [f'\n#### `{metric}` (paired Wilcoxon signed-rank, two-sided)\n']
    header = '| algo | ' + ' | '.join(f'{a}↔{b}' for a, b in pairs) + ' |'
    sep = '|' + '|'.join(['---'] * (1 + len(pairs))) + '|'
    lines.append(header)
    lines.append(sep)
    for algo in ALGO_ORDER:
        row = [algo.upper()]
        for a, b in pairs:
            res = paired_wilcoxon_per_algo(df, metric, a, b)
            med, p, n = res[algo]
            # p > 0.05 means we cannot reject "median diff = 0" — supports equivalence
            mark = '✓' if (not np.isnan(p) and p > 0.05) else '✗' if not np.isnan(p) else '—'
            row.append(f'med={med:+.2f}, p={p:.3g} {mark}')
        lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines) + '\n'


def stats_section_exp1(df, delta_rel=0.05):
    """Returns full markdown block of TOST + Wilcoxon tables for Exp 2."""
    out = []
    out.append('## Statistical tests (Exp 2, completed runs only)\n')
    n_seeds = df['seed'].nunique() if 'seed' in df.columns else 'N/A'
    out.append(f'Sample size: {n_seeds} seeds (paired by seed for mission-level, by (seed, agent_id) for agent-level).\n')

    out.append('### TOST — equivalence test for mission-level metrics')
    out.append('Two one-sided t-tests; equivalence at margin δ = ' f'{delta_rel*100:.0f}% '
               'of pooled mean. **✓** if `p_TOST < 0.05` (equivalence established within ±δ).')
    for metric in ('mission_completion_time', 'total_distance_moved'):
        out.append(print_tost_table(df, metric, metric, delta_rel))

    out.append('### Paired Wilcoxon — agent-level paired comparison')
    out.append('Per (seed, agent_id) pair. Two-sided. **✓** if `p > 0.05` '
               '(no statistically detectable median difference, supporting equivalence).')
    for metric in ('per_agent_distance_moved', 'per_agent_task_amount_done'):
        out.append(print_wilcoxon_table(df, metric, metric))
    return '\n'.join(out)


# ───────────── Filter / completion-rate helpers ──────────────────────

def filter_completed_only(df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows belonging to runs whose mission did not complete.
    Identifies non-completed runs by mission_completed metric == 0.0,
    then drops every row with that key tuple.
    """
    key_cols = ['seed', 'algo'] + (['mode'] if 'mode' in df.columns else []) \
                                 + (['leader_radius'] if 'leader_radius' in df.columns else [])
    mc = df[df.metric_name == 'mission_completed']
    bad_keys = mc[mc.value < 1.0][key_cols].drop_duplicates()
    if bad_keys.empty:
        return df
    merged = df.merge(bad_keys.assign(_drop=1), on=key_cols, how='left')
    return merged[merged._drop.isna()].drop(columns=['_drop'])


def completion_rate_table(df: pd.DataFrame) -> pd.DataFrame:
    mc = df[df.metric_name == 'mission_completed']
    group_cols = ['algo'] + (['mode'] if 'mode' in df.columns else []) \
                          + (['leader_radius'] if 'leader_radius' in df.columns else [])
    return mc.groupby(group_cols).value.agg(['mean', 'count']).rename(
        columns={'mean': 'completion_rate'})


def main():
    os.makedirs(FIG_DIR, exist_ok=True)

    # ── Exp 2 ──
    exp_dynamic_csv = os.path.join(DATA_DIR, 'exp2_dynamic_results.csv')
    if os.path.exists(exp_dynamic_csv):
        df1_raw = pd.read_csv(exp_dynamic_csv)
        df1 = filter_completed_only(df1_raw)
        n_dropped = (df1_raw.shape[0] - df1.shape[0])
        if n_dropped:
            print(f'(Exp 2: dropped {n_dropped} rows from incomplete runs)')
        print('\n=== Exp 2 — completion rate ===')
        print(completion_rate_table(df1_raw).to_string())
        print('\n=== Exp 2 figures ===')
        for metric, ylabel, _scope in EXP1_METRICS:
            out = os.path.join(FIG_DIR, f'exp2_{metric}.png')
            boxplot_per_metric(df1, metric, ylabel, out, title_prefix='Exp 2')
            print(f'  saved {out}')
        print('\n--- Exp 2 DESCRIPTIVE STATISTICS (mean ± std, completed runs only) ---')
        print(print_stats(df1))
        # Stage (c) — TOST + Wilcoxon
        stats_md = stats_section_exp1(df1, delta_rel=0.05)
        out_path = os.path.join(EXP_DIR, 'data', 'exp2_dynamic_stats.md')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(stats_md)
        print(f'\n  saved {out_path} (TOST + Wilcoxon)')
        print('\n' + stats_md)
    else:
        print(f'(skipped Exp 2 — no CSV at {exp_dynamic_csv})')

    # ── Exp 4 ──
    exp_sweep_csv = os.path.join(DATA_DIR, 'exp4_sweep_results.csv')
    if os.path.exists(exp_sweep_csv):
        df2_raw = pd.read_csv(exp_sweep_csv)
        df2 = filter_completed_only(df2_raw)
        n_dropped = (df2_raw.shape[0] - df2.shape[0])
        if n_dropped:
            print(f'\n(Exp 4: dropped {n_dropped} rows from incomplete runs)')
        print('\n=== Exp 4 — completion rate ===')
        print(completion_rate_table(df2_raw).to_string())
        print('\n=== Exp 4 figures ===')
        for metric, ylabel, _scope in EXP1_METRICS:
            out = os.path.join(FIG_DIR, f'exp4_{metric}.png')
            sweep_curve_per_metric(df2, metric, ylabel, out, title_prefix='Exp 4')
            print(f'  saved {out}')
        print('\n--- Exp 4 DESCRIPTIVE STATISTICS (mean ± std over Leader.comm, completed only) ---')
        print(print_stats_exp2(df2))
    else:
        print(f'(skipped Exp 4 — no CSV at {exp_sweep_csv})')


if __name__ == '__main__':
    main()
