"""3-way equivalence benchmark for CentralisationWrapper.

Runs CBBA / GRAPE / Hungarian × {pure-dec, wrapper, centralised baseline}
across N seeds and writes a Markdown report (Korean) + raw JSON to
`results/3way_benchmark_<timestamp>/`.

Usage:
    python scenarios/pygame/features/cen_wrapper/test/run_3way_benchmark.py             # default: 100 seeds
    python scenarios/pygame/features/cen_wrapper/test/run_3way_benchmark.py --seeds=20  # quick check
    python scenarios/pygame/features/cen_wrapper/test/run_3way_benchmark.py --timeout=60
"""
import os
import sys
import json
import argparse
import subprocess
import statistics
from datetime import datetime

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['PYTHONIOENCODING'] = 'utf-8'

SCEN_ROOT = 'scenarios/pygame/features/cen_wrapper'

# (algo, mode) -> yaml path under SCEN_ROOT
YAMLS = {
    'CBBA': {
        'pure-dec': 'configs/static/cbba/cbba.yaml',
        'wrapper':  'configs/static/cbba/cenwrapper_cbba.yaml',
        'baseline': 'configs/static/cbba/sga.yaml',
    },
    'GRAPE': {
        'pure-dec': 'configs/static/grape/grape.yaml',
        'wrapper':  'configs/static/grape/cenwrapper_grape.yaml',
        'baseline': 'configs/static/grape/cen_grape.yaml',
    },
    'Hungarian': {
        'pure-dec': 'configs/static/hungarian/dec_hungarian.yaml',
        'wrapper':  'configs/static/hungarian/cenwrapper_hungarian.yaml',
        'baseline': 'configs/static/hungarian/hungarian.yaml',
    },
}
MODES = ('pure-dec', 'wrapper', 'baseline')


def run_one(yaml_rel, seed, timeout_sec):
    """Run one (yaml × seed) in a subprocess. Returns dict or None on error."""
    code = '''
import os, sys, asyncio, time, json
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, ".")
from core.utils import set_config
set_config("__YAML_PATH__")
from core.utils import config
config["simulation"]["random_seed"] = __SEED__
config["simulation"]["rendering_mode"] = "None"
config["simulation"].setdefault("saving_options", {})
for k in ("save_gif","save_timewise_result_csv","save_agentwise_result_csv","save_config_yaml"):
    config["simulation"]["saving_options"][k] = False
config["simulation"].setdefault("bt_visualiser", {})["enabled"] = False
config["simulation"]["mode"] = "static"
config["simulation"]["static_timeout_sec"] = __TIMEOUT__
import importlib
sim_module = importlib.import_module(config["scenario"]["environment"] + ".sim.sim")
sim = getattr(sim_module, "Sim")(config)
from platforms.pygame.bt_runner import BTRunner
bt = BTRunner(config)
bt.initialize(sim.agents)
t0 = time.time()
async def run():
    n = 0
    while sim.running and n < 200000:
        await bt.step(); sim.update_simulation()
        n += 1
    return n
n = asyncio.run(run())
elapsed = time.time() - t0
sig = sorted([(a.agent_id, getattr(a, "assigned_task_id", None)) for a in sim.agents if a.type == "Follower"])
print("RESULT:" + json.dumps({"sig": sig, "running": sim.running, "elapsed": elapsed, "ticks": n}))
'''
    code = code.replace('__YAML_PATH__', f'{SCEN_ROOT}/{yaml_rel}') \
               .replace('__SEED__', str(seed)) \
               .replace('__TIMEOUT__', str(timeout_sec))
    try:
        out = subprocess.run([sys.executable, '-c', code],
                             capture_output=True, text=True,
                             timeout=timeout_sec + 30,  # safety margin over sim's TIMEOUT_SEC
                             encoding='utf-8', errors='replace')
        for line in (out.stdout or '').splitlines():
            if line.startswith('RESULT:'):
                return json.loads(line[len('RESULT:'):])
    except subprocess.TimeoutExpired:
        return None
    return None


def benchmark(seeds, timeout_sec):
    """results[seed][algo][mode] = {sig, running, elapsed, ticks}"""
    results = {}
    total = len(seeds) * len(YAMLS) * len(MODES)
    done = 0
    print(f'Running {total} simulations ({len(seeds)} seeds x {len(YAMLS)} algos x {len(MODES)} modes), timeout_sec={timeout_sec}\n')
    t_start = datetime.now()
    for seed in seeds:
        results[seed] = {}
        for algo, modes in YAMLS.items():
            results[seed][algo] = {}
            for mode in MODES:
                r = run_one(modes[mode], seed, timeout_sec)
                results[seed][algo][mode] = r
                done += 1
        elapsed_min = (datetime.now() - t_start).total_seconds() / 60.0
        print(f'  seed={seed:>3} done ({done}/{total}, {elapsed_min:.1f} min elapsed)')
    return results


def analyze(results, seeds):
    """Per-algorithm summary statistics."""
    summary = {}
    for algo in YAMLS:
        stats = {
            'total': len(seeds),
            'pure_eq_wrapper': 0,
            'wrapper_eq_baseline': 0,
            '3way_match': 0,
            'timeouts': {m: 0 for m in MODES},
            'errors':   {m: 0 for m in MODES},
            'ticks':    {m: [] for m in MODES},
            'elapsed':  {m: [] for m in MODES},
            'mismatches': [],  # list of {seed, broken_pairs}
        }
        for seed in seeds:
            data = results[seed][algo]
            sigs = {}
            for m in MODES:
                r = data.get(m)
                if r is None:
                    stats['errors'][m] += 1
                    sigs[m] = None
                    continue
                if r['running']:  # didn't terminate via stability → timeout
                    stats['timeouts'][m] += 1
                stats['ticks'][m].append(r['ticks'])
                stats['elapsed'][m].append(r['elapsed'])
                sigs[m] = tuple(tuple(x) for x in r['sig'])
            pure_eq_wrapper = sigs['pure-dec'] is not None and sigs['pure-dec'] == sigs['wrapper']
            wrapper_eq_baseline = sigs['wrapper'] is not None and sigs['wrapper'] == sigs['baseline']
            three_way = pure_eq_wrapper and wrapper_eq_baseline
            if pure_eq_wrapper:
                stats['pure_eq_wrapper'] += 1
            if wrapper_eq_baseline:
                stats['wrapper_eq_baseline'] += 1
            if three_way:
                stats['3way_match'] += 1
            else:
                broken = []
                if not pure_eq_wrapper:
                    broken.append('pure-dec ≠ wrapper')
                if not wrapper_eq_baseline:
                    broken.append('wrapper ≠ baseline')
                stats['mismatches'].append({'seed': seed, 'broken': broken})
        summary[algo] = stats
    return summary


def fmt_avg(values):
    if not values:
        return '—'
    if len(values) == 1:
        return f'{values[0]:.1f}'
    return f'{statistics.mean(values):.1f}'


def write_report(summary, seeds, timeout_sec, output_dir):
    md_path = os.path.join(output_dir, 'report.md')
    n = len(seeds)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('# CentralisationWrapper 3-way 동등성 벤치마크\n\n')
        f.write(f'- 실행 일시: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'- Seed 개수: **{n}**개 (1 ~ {seeds[-1] if seeds else 0})\n')
        f.write(f'- Static-mode timeout: {timeout_sec} 초 (wall-clock)\n')
        f.write(f'- 알고리즘 × 모드: {len(YAMLS)} × {len(MODES)} = {len(YAMLS) * len(MODES)} yaml, 총 {n * len(YAMLS) * len(MODES)} runs\n\n')

        # ── 1. 일치율 표 ─────────────────────────────────────
        f.write('## 1. 일치율 (Equivalence Rates)\n\n')
        f.write('각 seed 마다 세 모드의 최종 follower→task 할당 시그니처를 비교한 결과입니다.\n\n')
        f.write('| 알고리즘 | 3-way 일치 | pure-dec ↔ wrapper (Proposition 2) | wrapper ↔ baseline (Proposition 1) |\n')
        f.write('|---|---|---|---|\n')
        for algo, stats in summary.items():
            f.write(f'| **{algo}** | {stats["3way_match"]}/{stats["total"]} | {stats["pure_eq_wrapper"]}/{stats["total"]} | {stats["wrapper_eq_baseline"]}/{stats["total"]} |\n')
        f.write('\n')
        f.write('- **3-way 일치**: 세 모드의 시그니처가 모두 동일\n')
        f.write('- **pure-dec ↔ wrapper**: CentralisationWrapper 가 pure-dec 와 같은 결과를 만들어내는지 (paper Proposition 2)\n')
        f.write('- **wrapper ↔ baseline**: CentralisationWrapper 가 hand-written 중앙형 baseline 과 같은 결과인지 (paper Proposition 1)\n\n')

        # ── 2. 수렴 통계 ─────────────────────────────────────
        f.write('## 2. 수렴 통계 (Convergence Stats)\n\n')
        f.write('| 알고리즘 | 모드 | 평균 BT tick | 평균 wall-clock (s) | timeout | error |\n')
        f.write('|---|---|---|---|---|---|\n')
        for algo, stats in summary.items():
            for m in MODES:
                f.write(f'| {algo} | {m} | {fmt_avg(stats["ticks"][m])} | {fmt_avg(stats["elapsed"][m])} | {stats["timeouts"][m]}/{stats["total"]} | {stats["errors"][m]}/{stats["total"]} |\n')
        f.write('\n')
        f.write(f'- **timeout**: `static_timeout_sec={timeout_sec}` 초 안에 안정성 감지 실패 → 강제 종료된 run 수\n')
        f.write('- **error**: subprocess 자체가 실패한 run 수 (예: import 에러, 외부 timeout)\n\n')

        # ── 3. 불일치 발생 seed (있을 경우) ──────────────────
        f.write('## 3. 불일치 발생 Seed\n\n')
        any_mismatch = any(stats['mismatches'] for stats in summary.values())
        if not any_mismatch:
            f.write(f'**모든 seed ({n}/{n}) 에서 3-way 일치 확인.** ✓\n\n')
        else:
            f.write('| 알고리즘 | seed | 어긋난 페어 |\n')
            f.write('|---|---|---|\n')
            for algo, stats in summary.items():
                for mm in stats['mismatches']:
                    f.write(f'| {algo} | {mm["seed"]} | {", ".join(mm["broken"])} |\n')
            f.write('\n')

        # ── 4. 결론 ──────────────────────────────────────────
        f.write('## 4. 결론\n\n')
        all_match = all(stats['3way_match'] == stats['total'] for stats in summary.values())
        if all_match:
            f.write(f'**100% 검증 통과**. CBBA / GRAPE / Hungarian 세 알고리즘 모두 {n}개 seed 에서 3-way 동등성을 만족합니다. CentralisationWrapper Decorator 가 알고리즘에 무관하게 (`AssignTask` child 만 바꿔 끼우면) pure-dec 분산 방식과 hand-written 중앙형 baseline 둘 다와 일치하는 결과를 생성한다는 paper 의 핵심 주장 (Proposition 1 & 2) 을 실험적으로 확인.\n')
        else:
            f.write('일부 seed 에서 불일치 발생. 위 표 3 참조.\n')
    return md_path


def main():
    parser = argparse.ArgumentParser(description='3-way equivalence benchmark')
    parser.add_argument('--seeds', type=int, default=100, help='Number of seeds (1..N)')
    parser.add_argument('--timeout', type=float, default=30.0, help='static_timeout_sec for sim')
    args = parser.parse_args()

    seeds = list(range(1, args.seeds + 1))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join('results', f'3way_benchmark_{timestamp}')
    os.makedirs(output_dir, exist_ok=True)

    results = benchmark(seeds, args.timeout)
    raw_path = os.path.join(output_dir, 'raw.json')
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump({str(s): r for s, r in results.items()}, f, indent=2, ensure_ascii=False)

    summary = analyze(results, seeds)
    md_path = write_report(summary, seeds, args.timeout, output_dir)

    print(f'\n[OK] Report:    {md_path}')
    print(f'[OK] Raw data:  {raw_path}')


if __name__ == '__main__':
    main()
