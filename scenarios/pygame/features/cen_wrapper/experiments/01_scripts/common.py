"""Shared settings of the experiment runners: config files, designs (behaviour trees), teams and metrics.

Designs (CSV `system` label; paper name):
    hybrid_rules   Leader-as-proxy with both chattering rules (adopt + iso)
    hybrid, hybrid_iso, hybrid_adopt   Leader-as-proxy with no rule / iso only / adopt only (Table 2)
    relay_hold     Leader-as-relay with iso;  relay: without it (Table 2)
    solver_commit  Leader-as-solver with grace + reset + commit + iso;  solver: without any rule (Table 2)
    Dec-only is hybrid_rules with leader radius 0 (no follower reaches the leader).
The behaviour-tree XML files are in the scenario folder (cen_wrapper/): the final trees at its top level, variants with
rules removed in bt_ablation/, static trees in bt_static/. Their nodes are in plugins/cen_wrapper/bt_nodes.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _campaign import EXP_DIR, SCEN_ROOT, run_campaign  # noqa: E402,F401

RUN_STATIC = os.path.join(EXP_DIR, '01_scripts', '_run_static.py')
ALGOS = ['cbba', 'grape', 'hungarian']

# ── config files (configs/<group>/<file>) ─────────────────────────────────────
WRAPPER = {a: f'{a}/cenwrapper_{a}.yaml' for a in ALGOS}                                       # decentralised plugin
DEC = {'cbba': 'cbba/cbba.yaml', 'grape': 'grape/grape.yaml', 'hungarian': 'hungarian/dec_hungarian.yaml'}  # no leader
CEN = {'cbba': 'cbba/sga.yaml', 'grape': 'grape/cen_grape.yaml', 'hungarian': 'hungarian/hungarian.yaml'}  # + centralised solver


def yaml_path(group, rel):
    """group: 'static', 'dynamic/global' or 'dynamic/partial'."""
    return os.path.join(SCEN_ROOT, 'configs', group, rel)


# ── designs: dynamic runs ─────────────────────────────────────────────────────
DYNAMIC_SYSTEMS = {
    'hybrid':        {'leader_bt': 'bt_leader_proxy.xml', 'follower_bt': 'bt_ablation/bt_follower_proxy_no_rules.xml'},
    'hybrid_iso':    {'leader_bt': 'bt_leader_proxy.xml', 'follower_bt': 'bt_ablation/bt_follower_proxy_no_adopt.xml'},
    'hybrid_adopt':  {'leader_bt': 'bt_leader_proxy.xml', 'follower_bt': 'bt_ablation/bt_follower_proxy_no_iso.xml'},
    'hybrid_rules':  {'leader_bt': 'bt_leader_proxy.xml', 'follower_bt': 'bt_follower_proxy.xml'},
    'relay':         {'leader_bt': 'bt_leader_relay.xml', 'follower_bt': 'bt_ablation/bt_follower_relay_no_rules.xml'},
    'relay_hold':    {'leader_bt': 'bt_leader_relay.xml', 'follower_bt': 'bt_follower_relay.xml'},
    'solver':        {'leader_bt': 'bt_ablation/bt_leader_solver_no_grace.xml',
                      'follower_bt': {'cbba': 'bt_ablation/bt_follower_solver_no_rules.xml', 'hungarian': 'bt_ablation/bt_follower_solver_no_rules.xml',
                                      'grape': 'bt_ablation/bt_follower_solver_grape_no_rules.xml'}},
    'solver_commit': {'leader_bt': 'bt_leader_solver.xml',
                      'follower_bt': {'cbba': 'bt_follower_solver.xml', 'hungarian': 'bt_follower_solver.xml',
                                      'grape': 'bt_follower_solver_grape.xml'}},
    # Leader-as-solver with one of its rules switched off (Table 2)
    'solver_nograce':  {'leader_bt': 'bt_ablation/bt_leader_solver_no_grace.xml',
                        'follower_bt': {'cbba': 'bt_follower_solver.xml', 'hungarian': 'bt_follower_solver.xml',
                                        'grape': 'bt_follower_solver_grape.xml'}},
    'solver_noreset':  {'leader_bt': 'bt_leader_solver.xml',
                        'follower_bt': {'cbba': 'bt_ablation/bt_follower_solver_no_reset.xml',
                                        'hungarian': 'bt_ablation/bt_follower_solver_no_reset.xml',
                                        'grape': 'bt_ablation/bt_follower_solver_grape_no_reset.xml'}},
    'solver_nocommit': {'leader_bt': 'bt_leader_solver.xml',
                        'follower_bt': {'cbba': 'bt_ablation/bt_follower_solver_no_commit.xml', 'hungarian': 'bt_ablation/bt_follower_solver_no_commit.xml',
                                        'grape': 'bt_ablation/bt_follower_solver_grape_no_commit.xml'}},
}
# Leader-as-solver designs run the config that names the centralised solver plugin
SOLVER_SYSTEMS = {'solver', 'solver_commit', 'solver_nograce', 'solver_noreset', 'solver_nocommit'}


def dynamic_bts(system, algo):
    bts = DYNAMIC_SYSTEMS[system]
    follower_bt = bts['follower_bt']
    return {'leader_bt': bts['leader_bt'],
            'follower_bt': follower_bt[algo] if isinstance(follower_bt, dict) else follower_bt}


def dynamic_yaml(system, algo):
    return (yaml_path('dynamic/global', CEN[algo]) if system in SOLVER_SYSTEMS
            else yaml_path('dynamic/partial', WRAPPER[algo]))


# ── designs: static runs (robots do not move) ─────────────────────────────────
STATIC_SYSTEMS = {
    'hybrid': {'leader_bt': 'bt_static/bt_leader_proxy.xml', 'follower_bt': 'bt_static/bt_follower_proxy.xml'},
    'relay':  {'leader_bt': 'bt_leader_relay.xml', 'follower_bt': 'bt_static/bt_follower_relay.xml'},
}
# Leader-as-proxy with its boundary flows switched off (Table 1): inbound relay (In), outbound emission (Out)
ABLATION_LEADER_BT = {
    'none':          'bt_static/bt_leader_proxy_no_inbound_no_outbound.xml',
    'inbound_only':  'bt_static/bt_leader_proxy_no_outbound.xml',
    'outbound_only': 'bt_static/bt_leader_proxy_no_inbound.xml',
    'both':          'bt_static/bt_leader_proxy.xml',
}

# ── teams and limits ──────────────────────────────────────────────────────────
# CBBA 15 followers / 60 tasks (bundle 4), Hungarian 15 / 15, GRAPE the config's 40 / 10. CBBA tasks lie in
# [40, 1300] x [40, 700] (the static CBBA config's region, applied to dynamic runs too).
DENSE_TEAM = {
    'cbba':      {'follower_qty': 15, 'task_qty': 60, 'max_tasks_per_agent': 4},
    'hungarian': {'follower_qty': 15, 'task_qty': 15},
    'grape':     {},
}
DENSE_TASK_REGION = {'cbba': [40, 1300, 40, 700]}
MAX_TICKS = {'cbba': 12000, 'grape': 4000, 'hungarian': 8000}   # cap of dynamic runs; a capped run is not completed


def team_of(algo):
    """Team, task region and CBBA's full bundle reset for dynamic runs."""
    team = dict(DENSE_TEAM[algo])
    if algo in DENSE_TASK_REGION:
        team['task_region'] = DENSE_TASK_REGION[algo]
    if algo == 'cbba':
        team['cbba_bundle_reset'] = 'full'
    return team


STATIC_METRICS = [
    'cen_cen', 'cen_dec', 'dec_dec_same', 'dec_dec_split', 'overclaimed', 'unclaimed',
    'allocation', 'team_utility', 'path_length', 'ticks', 'last_change_tick', 'converged',
    'n_cen', 'n_dec', 'n_dec_components', 'follower_graph_connected',
    'team_graph_connected', 'comm_to_convergence', 'comm_per_tick_to_convergence',
]


def long_timeout(seconds=3600):
    """Raise the per-run timeout of dynamic runs (default 900 s); long CBBA runs can reach the 12,000-tick cap."""
    import _campaign
    run_single = _campaign.run_single
    _campaign.run_single = lambda spec, timeout=None, runner=None: run_single(spec, seconds, runner)
