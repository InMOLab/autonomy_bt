"""Analysis + plot for Exp 3 (4-case boundary conflict ablation).

4 conditions toggle the two proposed mesh mechanisms independently:

  baseline     — Relay OFF, Forward OFF  (bt_follower_static.xml)
  relay_only   — Relay ON,  Forward OFF  (bt_follower_static_relay_only.xml)
  forward_only — Relay OFF, Forward ON   (bt_follower_static_forward_only.xml)
  full         — Relay ON,  Forward ON   (bt_follower_static_relay.xml)

Run from project root (autonomy_bt/):
    python scenarios/pygame/features/cen_wrapper/experiments/scripts/analyze_boundary.py
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'
EXP_DIR = os.path.join(SCEN_ROOT, 'experiments')
DATA_DIR = os.path.join(EXP_DIR, 'data')
FIG_DIR = os.path.join(EXP_DIR, 'figures')

ALGO_ORDER = ['cbba', 'hungarian']
COND_ORDER = ['baseline', 'relay_only', 'forward_only', 'full']
COND_COLOR = {
    'baseline':     '#C44E52',
    'relay_only':   '#DD8452',
    'forward_only': '#8172B2',
    'full':         '#4C72B0',
}

METRICS = [
    ('bundle_total_conflicts', 'Bundle conflicts (unclaimed + over-claimed)'),
    ('bundle_overclaimed',     'Bundle over-claimed tasks (duplicates)'),
    ('bundle_unclaimed',       'Bundle unclaimed tasks (no claimer)'),
    ('primary_overclaimed',    'Primary over-claimed (duplicate primary)'),
]


def boxplot_conflicts(df, metric, ylabel, out_path):
    fig, axes = plt.subplots(1, len(ALGO_ORDER), figsize=(11, 4), sharey=False)
    for ax, algo in zip(axes, ALGO_ORDER):
        sub = df[df.algo == algo]
        data = [sub[sub.condition == c][metric].values for c in COND_ORDER]
        bp = ax.boxplot(data, tick_labels=COND_ORDER, patch_artist=True, widths=0.55)
        for patch, cond in zip(bp['boxes'], COND_ORDER):
            patch.set_facecolor(COND_COLOR[cond])
            patch.set_alpha(0.65)
        for median in bp['medians']:
            median.set_color('black')
            median.set_linewidth(1.6)
        ax.set_title(f'{algo.upper()}', fontsize=11)
        ax.grid(axis='y', linestyle=':', alpha=0.5)
        ax.tick_params(axis='x', rotation=20)
        if ax is axes[0]:
            ax.set_ylabel(ylabel)
    fig.suptitle(f'Exp 3 — {metric}', fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def bar_mean_conflicts(df, metric, ylabel, out_path):
    """Grouped bar chart: mean ± std per (algo, condition)."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    n_cond = len(COND_ORDER)
    bar_w = 0.8 / n_cond
    x = np.arange(len(ALGO_ORDER))
    for i, cond in enumerate(COND_ORDER):
        means, stds = [], []
        for algo in ALGO_ORDER:
            vals = df[(df.algo == algo) & (df.condition == cond)][metric]
            means.append(vals.mean() if len(vals) else 0)
            stds.append(vals.std() if len(vals) else 0)
        offsets = x + (i - (n_cond - 1) / 2) * bar_w
        ax.bar(offsets, means, bar_w, yerr=stds,
               color=COND_COLOR[cond], edgecolor='black', linewidth=0.5,
               alpha=0.8, label=cond, capsize=3)
    ax.set_xticks(x)
    ax.set_xticklabels([a.upper() for a in ALGO_ORDER])
    ax.set_ylabel(ylabel)
    ax.set_title(f'Exp 3 — {metric}', fontsize=12)
    ax.grid(axis='y', linestyle=':', alpha=0.5)
    ax.legend(title='condition', loc='upper right', fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def stats_table(df):
    rows = []
    for algo in ALGO_ORDER:
        for cond in COND_ORDER:
            sub = df[(df.algo == algo) & (df.condition == cond)]
            row = {'algo': algo, 'condition': cond, 'n': len(sub)}
            for metric, _ in METRICS:
                row[f'{metric}_mean'] = sub[metric].mean()
                row[f'{metric}_std'] = sub[metric].std()
            rows.append(row)
    return pd.DataFrame(rows)


def baseline_vs_full_paired(df, metric):
    """Per-seed paired comparison: baseline → full (the headline ablation)."""
    print(f'\n=== Paired baseline → full on `{metric}` ===')
    for algo in ALGO_ORDER:
        sub = df[df.algo == algo]
        pivot = sub.pivot_table(index='seed', columns='condition', values=metric)
        if 'baseline' not in pivot.columns or 'full' not in pivot.columns:
            print(f'  {algo}: missing condition (baseline or full) — skip')
            continue
        pivot['delta'] = pivot['baseline'] - pivot['full']
        n_better = int((pivot['delta'] > 0).sum())
        n_same = int((pivot['delta'] == 0).sum())
        n_worse = int((pivot['delta'] < 0).sum())
        print(f'  {algo.upper()}: better={n_better} same={n_same} worse={n_worse}  '
              f'mean delta={pivot["delta"].mean():.2f}')


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    csv_path = os.path.join(DATA_DIR, 'exp3_boundary_results.csv')
    if not os.path.exists(csv_path):
        sys.exit(f'No CSV at {csv_path}')
    df = pd.read_csv(csv_path)

    print('=== Exp 3 — descriptive stats ===')
    print(stats_table(df).to_string(index=False))
    print()

    for metric, _ in METRICS:
        baseline_vs_full_paired(df, metric)

    for metric, ylabel in METRICS:
        out = os.path.join(FIG_DIR, f'exp3_{metric}_box.png')
        boxplot_conflicts(df, metric, ylabel, out)
        print(f'  saved {out}')
        out2 = os.path.join(FIG_DIR, f'exp3_{metric}_bar.png')
        bar_mean_conflicts(df, metric, ylabel, out2)
        print(f'  saved {out2}')


if __name__ == '__main__':
    main()
