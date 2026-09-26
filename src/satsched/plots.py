"""Static figures for the paper and poster (matplotlib, validated categorical palette)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from satsched.models import Stage  # noqa: E402
from satsched.simulator.engine import RunResult  # noqa: E402

# Fixed entity -> colour mapping (reference palette slots 1-4, validated adjacent-pair CVD safe).
POLICY_COLORS = {"value_aware": "#2a78d6", "priority_rules": "#eb6834", "process_all": "#1baf7a", "bent_pipe": "#eda100"}
POLICY_LABELS = {"value_aware": "Value-aware (ours)", "priority_rules": "Priority rules",
                 "process_all": "Process-all", "bent_pipe": "Bent-pipe"}
POLICY_ORDER = ["value_aware", "priority_rules", "process_all", "bent_pipe"]
SCENARIO_LABELS = {"nominal": "Nominal", "energy_starved": "Energy-\nstarved", "downlink_starved": "Downlink-\nstarved",
                   "storage_tight": "Storage-\ntight", "event_surge": "Event\nsurge"}
SCENARIO_ORDER = ["nominal", "energy_starved", "downlink_starved", "storage_tight", "event_surge"]
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3de", "#fcfcfb"
ECLIPSE, CONTACT = "#ecebe7", "#cde2fb"


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
        "text.color": INK, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "font.size": 10,
        "axes.titlesize": 11, "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 2,
    })


def _grouped_bars(ax, summary: list[dict], metric: str, ylabel: str, label_fmt: str = "{:.0f}") -> None:
    by = {(r["scenario"], r["policy"]): r for r in summary}
    scenarios = [s for s in SCENARIO_ORDER if any(k[0] == s for k in by)]
    width = 0.19
    x = np.arange(len(scenarios))
    for j, pol in enumerate(POLICY_ORDER):
        vals = [float(by[(s, pol)][metric]) if (s, pol) in by else np.nan for s in scenarios]
        errs = [float(by[(s, pol)].get(f"{metric}_ci95", 0) or 0) if (s, pol) in by else 0 for s in scenarios]
        pos = x + (j - 1.5) * (width + 0.02)
        ax.bar(pos, vals, width, color=POLICY_COLORS[pol], label=POLICY_LABELS[pol], edgecolor=SURFACE, linewidth=1)
        ax.errorbar(pos, vals, yerr=errs, fmt="none", ecolor=INK_2, elinewidth=1, capsize=2)
        pad = ax.get_ylim()[1] * 0.012
        for p, v, e in zip(pos, vals, errs):
            if np.isfinite(v):
                ax.text(p, v + e + pad, label_fmt.format(v), ha="center", va="bottom", fontsize=7, color=INK_2)
    ax.set_xticks(x, [SCENARIO_LABELS.get(s, s) for s in scenarios])
    ax.set_ylabel(ylabel)
    ax.grid(axis="x", visible=False)


def fig_metric_by_scenario(summary: list[dict], metric: str, ylabel: str, title: str, path: Path) -> Path:
    _style()
    fig, ax = plt.subplots(figsize=(8.2, 3.8))
    ax.set_ylim(0, max(float(r[metric]) for r in summary) * 1.18)
    _grouped_bars(ax, summary, metric, ylabel)
    ax.set_title(title, loc="left")
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _shade(ax, run: RunResult) -> None:
    sc = run.scenario
    for a, b in run.schedule.eclipse_intervals(0.0, sc.duration_s):
        ax.axvspan(a / 3600, b / 3600, color=ECLIPSE, lw=0)
    for w in run.schedule.windows:
        if w.start_s < sc.duration_s:
            ax.axvspan(w.start_s / 3600, w.end_s / 3600, color=CONTACT, lw=0)


def _label_line_ends(ax, ends: list[tuple[float, str]], x: float) -> None:
    """Direct labels at line ends, skipping any that would collide with an already placed one."""
    lo, hi = ax.get_ylim()
    min_gap = 0.07 * (hi - lo)
    placed: list[float] = []
    for y, text in ends:
        if all(abs(y - other) >= min_gap for other in placed):
            ax.annotate(text, (x, y), xytext=(4, 0), textcoords="offset points", fontsize=7.5, color=INK_2,
                        va="center")
            placed.append(y)


def fig_timeline(runs: dict[str, RunResult], path: Path) -> Path:
    """Battery, storage and cumulative value over one simulated day (small multiples, one axis each)."""
    _style()
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 6.4), sharex=True)
    any_run = next(iter(runs.values()))
    sat = any_run.scenario.satellite
    panels = [
        ("soc_wh", 100.0 / sat.battery_wh, "Battery (%)"),
        ("storage_mb", 100.0 / sat.storage_mb, "Storage used (%)"),
        ("value_cum", 1.0, "Value delivered"),
    ]
    for ax, (key, scale, label) in zip(axes, panels):
        _shade(ax, any_run)
        ends: list[tuple[float, str]] = []
        for pol in POLICY_ORDER:
            if pol not in runs:
                continue
            s = runs[pol].series
            t = s["time_s"] / 3600
            y = s[key] * scale
            ax.plot(t, y, color=POLICY_COLORS[pol], label=POLICY_LABELS[pol])
            ends.append((float(y[-1]), POLICY_LABELS[pol].split(" (")[0]))
        _label_line_ends(ax, ends, float(t[-1]))
        ax.set_ylabel(label)
        ax.grid(axis="x", visible=False)
    axes[0].axhline(sat.reserve_frac * 100, color=INK_2, lw=1, ls="--")
    axes[0].text(0.1, sat.reserve_frac * 100 + 2, "reserve", fontsize=7.5, color=INK_2)
    axes[-1].set_xlabel("Mission time (h)   ·   grey = eclipse, blue = ground-station pass")
    axes[0].set_title(f"One simulated day — {any_run.scenario.name.replace('_', '-')} scenario, seed {any_run.seed}",
                      loc="left")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=len(runs), loc="lower center", fontsize=8.5)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


OUTCOMES = [
    ("Delivered (processed onboard)", "#1c5cab"),
    ("Delivered (raw)", "#6da7ec"),
    ("Filtered onboard (useless)", "#b7d3f6"),
    ("Lost (dropped / overflow / expired)", "#8b8a85"),
    ("Still onboard at end", "#d6d5cf"),
]


def outcome_shares(run: RunResult) -> list[float]:
    n = len(run.items)
    delivered = [i for i in run.items if i.stage is Stage.DELIVERED]
    counts = [
        sum(1 for i in delivered if i.processed),
        sum(1 for i in delivered if not i.processed),
        sum(1 for i in run.items if i.stage is Stage.DISCARDED),
        sum(1 for i in run.items if i.stage in (Stage.DROPPED, Stage.OVERFLOW, Stage.EXPIRED)),
        sum(1 for i in run.items if i.active),
    ]
    return [100.0 * c / n for c in counts]


def fig_outcomes(runs: dict[str, RunResult], path: Path) -> Path:
    _style()
    fig, ax = plt.subplots(figsize=(8.2, 3.0))
    pols = [p for p in POLICY_ORDER if p in runs][::-1]
    for y, pol in enumerate(pols):
        left = 0.0
        for (label, color), share in zip(OUTCOMES, outcome_shares(runs[pol])):
            ax.barh(y, share, left=left, color=color, edgecolor=SURFACE, linewidth=2, height=0.62,
                    label=label if y == 0 else None)
            if share >= 6:
                ax.text(left + share / 2, y, f"{share:.0f}%", ha="center", va="center", fontsize=8,
                        color="white" if color in ("#1c5cab", "#8b8a85") else INK)
            left += share
    ax.set_yticks(range(len(pols)), [POLICY_LABELS[p] for p in pols])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of generated items (%)")
    ax.grid(axis="y", visible=False)
    ax.set_title("What happened to every data item (nominal scenario)", loc="left")
    ax.legend(ncol=3, fontsize=8, loc="upper center", bbox_to_anchor=(0.45, -0.28))
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _box(ax, xy, w, h, text, fc, ec=INK_2, fs=9, bold=False) -> None:
    ax.add_patch(FancyBboxPatch(xy, w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(xy[0] + w / 2, xy[1] + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", color=INK, wrap=True)


def _arrow(ax, a, b, color=INK_2) -> None:
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, lw=1.4, color=color))


def fig_architecture(path: Path) -> Path:
    """Block diagram of the onboard decision loop."""
    _style()
    fig, ax = plt.subplots(figsize=(9.0, 4.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")
    _box(ax, (0.1, 3.4), 1.8, 1.1, "Instruments\noptical · hyperspectral\nevent · science · TM", "#f0efec", fs=8)
    _box(ax, (0.1, 1.6), 1.8, 1.2, "Onboard storage\nraw items +\nproducts", "#f0efec", fs=8.5)
    _box(ax, (2.6, 0.5), 4.4, 4.2, "", "#eef4fc", ec="#2a78d6")
    ax.text(4.8, 4.45, "Value-aware decision engine (every 30 s)", ha="center", fontsize=9.5, fontweight="bold")
    steps = [
        "1  Value options: raw vs processed\n    (usefulness x priority x timeliness)",
        "2  Shadow prices by dual decomposition\n    downlink · energy · GPU · CPU · storage",
        "3  Net utility → PROCESS / RAW / NONE",
        "4  Admission · downlink order · storage guard",
    ]
    for k, s in enumerate(steps):
        _box(ax, (2.8, 3.55 - k * 0.8), 4.0, 0.66, s, "white", ec="#86b6ef", fs=7.8)
    _box(ax, (7.6, 3.4), 2.2, 1.1, "CPU / GPU\nprocess now", "#e8f6f0", fs=8.5)
    _box(ax, (7.6, 1.9), 2.2, 1.1, "Radio downlink\nduring passes\n→ ground station", "#fdf0e9", fs=8.5)
    _box(ax, (7.6, 0.4), 2.2, 1.1, "Store / drop", "#f0efec", fs=8.5)
    _box(ax, (0.1, 0.1), 1.8, 1.1, "Forecasts\npasses · eclipses\nbattery · queues", "#fff6df", fs=8)
    _arrow(ax, (1.0, 3.4), (1.0, 2.85))
    _arrow(ax, (1.9, 2.2), (2.6, 2.6))
    _arrow(ax, (1.9, 0.65), (2.6, 1.2))
    for y in (3.95, 2.45, 0.95):
        _arrow(ax, (7.0, 2.6), (7.6, y))
    _arrow(ax, (8.7, 3.4), (8.7, 3.0))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path
