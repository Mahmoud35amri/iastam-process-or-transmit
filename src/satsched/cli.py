"""Command line interface.

    python -m satsched.cli run --scenario nominal --policy value_aware --seed 0
    python -m satsched.cli bench --seeds 20 --out results
    python -m satsched.cli dataset --seeds 3 --out data
    python -m satsched.cli demo --scenario nominal --seed 7 --out dashboard/data.js
    python -m satsched.cli figures --results results --out docs/figures
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from satsched.experiments import (
    gain_over,
    read_csv,
    run_ablation,
    run_grid,
    save_results,
    summarize,
    to_markdown,
    write_csv,
)
from satsched.export import build_demo, export_dataset, write_demo_js
from satsched.metrics import compute_metrics
from satsched.policies import POLICY_NAMES, make_policy
from satsched.scenarios import ALL_SCENARIOS, SCENARIOS, get_scenario
from satsched.simulator.engine import run_simulation

log = logging.getLogger("satsched")


def _cmd_run(args: argparse.Namespace) -> None:
    result = run_simulation(get_scenario(args.scenario), make_policy(args.policy), args.seed)
    print(json.dumps(compute_metrics(result), indent=2))


def _cmd_bench(args: argparse.Namespace) -> None:
    rows = run_grid(args.scenarios, args.policies, range(args.seed0, args.seed0 + args.seeds), args.workers)
    summary = save_results(rows, Path(args.out))
    print((Path(args.out) / "summary.md").read_text(encoding="utf-8"))
    for ref in ("priority_rules", "process_all", "bent_pipe"):
        gains = gain_over(summary, ref)
        print(f"value gain vs {ref}: " + ", ".join(f"{k} {v:+.1f}%" for k, v in gains.items()))


def _cmd_ablation(args: argparse.Namespace) -> None:
    rows = run_ablation(args.scenarios, range(args.seed0, args.seed0 + args.seeds), args.workers)
    out = Path(args.out)
    write_csv(rows, out / "ablation_runs.csv")
    summary = summarize(rows)
    write_csv(summary, out / "ablation_summary.csv")
    md = to_markdown(summary, ["value_score_pct", "energy_total_wh", "time_below_reserve_pct", "overflow_pct"])
    (out / "ablation_summary.md").write_text(md, encoding="utf-8")
    print(md)


def _cmd_geometry(args: argparse.Namespace) -> None:
    from satsched.geometry import GROUND_STATIONS, ORBIT_DIR, compute_geometry, save_geometry

    lines = [ln for ln in Path(args.tle).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 3:
        raise SystemExit(f"{args.tle}: expected a 3-line TLE (name, line 1, line 2)")
    geo = compute_geometry(tuple(lines[:3]), GROUND_STATIONS[args.station], days=args.days,
                           masks=tuple(args.masks), step_s=args.step)
    out = save_geometry(geo, ORBIT_DIR / args.name)
    per_mask = {m: sum(1 for p in geo.passes if p[0] == m) / args.days for m in args.masks}
    mean_ecl = sum(b - a for a, b in geo.eclipses) / max(len(geo.eclipses), 1) / 60
    print(f"wrote {out}: period {geo.period_s / 60:.2f} min, mean eclipse {mean_ecl:.1f} min, "
          + ", ".join(f"{v:.1f} passes/day above {m:g} deg" for m, v in per_mask.items()))


def _cmd_dataset(args: argparse.Namespace) -> None:
    paths = export_dataset(args.scenarios, list(range(args.seeds)), Path(args.out))
    print(f"wrote {len(paths)} files to {args.out}")


def _cmd_demo(args: argparse.Namespace) -> None:
    summary_csv = Path(args.results) / "summary.csv"
    benchmark = read_csv(summary_csv) if summary_csv.exists() else []
    payload = build_demo(args.scenario, args.seed, benchmark=benchmark)
    print(f"wrote {write_demo_js(payload, Path(args.out))}")


def _cmd_figures(args: argparse.Namespace) -> None:
    from satsched import plots

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = read_csv(Path(args.results) / "summary.csv")
    plots.fig_architecture(out / "architecture.png")
    plots.fig_metric_by_scenario(summary, "value_score_pct", "Value captured (% of ideal)",
                                 "Decision quality: scientific value delivered", out / "value_by_scenario.png")
    plots.fig_metric_by_scenario(summary, "energy_total_wh", "Discretionary energy (Wh / day)",
                                 "Energy spent on processing + downlink", out / "energy_by_scenario.png")
    plots.fig_metric_by_scenario(summary, "completion_rate_pct", "Completed items (%)",
                                 "Task completion (delivered or filtered onboard)", out / "completion_by_scenario.png")
    scenario = get_scenario(args.scenario)
    runs = {p: run_simulation(scenario, make_policy(p), args.seed) for p in POLICY_NAMES}
    plots.fig_timeline({p: runs[p] for p in ("value_aware", "priority_rules", "process_all")}, out / "timeline.png")
    plots.fig_outcomes(runs, out / "outcomes.png")
    starved = get_scenario("energy_starved")
    runs_e = {p: run_simulation(starved, make_policy(p), args.seed) for p in ("value_aware", "priority_rules", "process_all")}
    plots.fig_timeline(runs_e, out / "timeline_energy_starved.png")
    print(f"figures written to {out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="satsched", description="Onboard process-or-transmit decision engine")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="simulate one day with one policy")
    run.add_argument("--scenario", default="nominal", choices=sorted(ALL_SCENARIOS))
    run.add_argument("--policy", default="value_aware", choices=POLICY_NAMES)
    run.add_argument("--seed", type=int, default=0)
    run.set_defaults(func=_cmd_run)

    bench = sub.add_parser("bench", help="all scenarios x policies x seeds")
    bench.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=sorted(ALL_SCENARIOS))
    bench.add_argument("--policies", nargs="+", default=list(POLICY_NAMES), choices=POLICY_NAMES)
    bench.add_argument("--seeds", type=int, default=20)
    bench.add_argument("--seed0", type=int, default=0, help="first seed (tuning used 1000-1003)")
    bench.add_argument("--workers", type=int, default=None)
    bench.add_argument("--out", default="results")
    bench.set_defaults(func=_cmd_bench)

    abl = sub.add_parser("ablation", help="value-aware engine with components switched off")
    abl.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=sorted(ALL_SCENARIOS))
    abl.add_argument("--seeds", type=int, default=20)
    abl.add_argument("--seed0", type=int, default=0)
    abl.add_argument("--workers", type=int, default=None)
    abl.add_argument("--out", default="results")
    abl.set_defaults(func=_cmd_ablation)

    geo = sub.add_parser("geometry", help="compute real passes + eclipses from a TLE (needs skyfield)")
    geo.add_argument("--tle", default="data/orbit/sentinel2a.tle")
    geo.add_argument("--station", default="toulouse", choices=["toulouse", "kiruna", "svalbard"])
    geo.add_argument("--days", type=int, default=62)
    geo.add_argument("--masks", type=float, nargs="+", default=[10.0, 20.0])
    geo.add_argument("--step", type=float, default=10.0, help="illumination sampling step (s)")
    geo.add_argument("--name", default="sentinel2a_toulouse")
    geo.set_defaults(func=_cmd_geometry)

    data = sub.add_parser("dataset", help="export the synthetic benchmark dataset")
    data.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=sorted(ALL_SCENARIOS))
    data.add_argument("--seeds", type=int, default=3)
    data.add_argument("--out", default="data")
    data.set_defaults(func=_cmd_dataset)

    demo = sub.add_parser("demo", help="export the dashboard payload")
    demo.add_argument("--scenario", default="nominal", choices=sorted(ALL_SCENARIOS))
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--results", default="results")
    demo.add_argument("--out", default="dashboard/data.js")
    demo.set_defaults(func=_cmd_demo)

    figs = sub.add_parser("figures", help="render paper/poster figures")
    figs.add_argument("--results", default="results")
    figs.add_argument("--scenario", default="nominal", choices=sorted(ALL_SCENARIOS))
    figs.add_argument("--seed", type=int, default=7)
    figs.add_argument("--out", default="docs/figures")
    figs.set_defaults(func=_cmd_figures)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
