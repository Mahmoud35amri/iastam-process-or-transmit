import math
from dataclasses import replace

import pytest

from satsched.experiments import gain_over, read_csv, run_grid, save_results, summarize, to_markdown, write_csv
from satsched.metrics import compute_metrics, per_type_table
from satsched.policies import make_policy
from satsched.scenarios import get_scenario
from satsched.simulator.engine import run_simulation

SHORT = replace(get_scenario("nominal"), duration_s=6 * 3600.0)


@pytest.fixture(scope="module")
def runs():
    return {name: run_simulation(SHORT, make_policy(name), seed=11) for name in ("bent_pipe", "value_aware")}


def test_metrics_are_consistent(runs):
    for run in runs.values():
        m = compute_metrics(run)
        assert 0 <= m["value_score_pct"] <= 100
        outcome = (m["delivered_pct"] + m["discarded_onboard_pct"] + m["dropped_pct"] + m["overflow_pct"]
                   + m["expired_pct"] + m["backlog_pct"])
        assert outcome == pytest.approx(100.0)
        assert m["completion_rate_pct"] == pytest.approx(m["delivered_pct"] + m["discarded_onboard_pct"])
        assert m["energy_total_wh"] == pytest.approx(m["energy_proc_wh"] + m["energy_radio_wh"])
        assert 0 <= m["storage_peak_pct"] <= 100 + 1e-9
        assert 0 <= m["min_soc_pct"] <= 100


def test_bent_pipe_never_processes(runs):
    m = compute_metrics(runs["bent_pipe"])
    assert m["processed_onboard_pct"] == 0 and m["energy_proc_wh"] == 0 and m["gpu_util_pct"] == 0


def test_per_type_table_covers_every_type(runs):
    rows = per_type_table(runs["value_aware"])
    assert {r["data_type"] for r in rows} == {k.name for k in SHORT.data_types}
    assert sum(r["generated"] for r in rows) == len(runs["value_aware"].items)


ROWS = [
    {"scenario": "a", "policy": "value_aware", "seed": 0, "value_score_pct": 50.0},
    {"scenario": "a", "policy": "value_aware", "seed": 1, "value_score_pct": 54.0},
    {"scenario": "a", "policy": "bent_pipe", "seed": 0, "value_score_pct": 40.0},
    {"scenario": "a", "policy": "bent_pipe", "seed": 1, "value_score_pct": 40.0},
]


def test_summarize_mean_and_ci():
    summary = summarize(ROWS, ["value_score_pct"])
    va = next(r for r in summary if r["policy"] == "value_aware")
    assert va["value_score_pct"] == pytest.approx(52.0)
    assert va["value_score_pct_ci95"] == pytest.approx(1.96 * math.sqrt(8) / math.sqrt(2))
    assert va["n_seeds"] == 2


def test_gain_over_reference():
    summary = summarize(ROWS, ["value_score_pct"])
    assert gain_over(summary, "bent_pipe") == {"a": pytest.approx(30.0)}


def test_markdown_and_csv_roundtrip(tmp_path):
    summary = summarize(ROWS, ["value_score_pct"])
    md = to_markdown(summary, ["value_score_pct"])
    assert "| a | value_aware | 52.0 ±" in md
    write_csv(ROWS, tmp_path / "rows.csv")
    back = read_csv(tmp_path / "rows.csv")
    assert back[0]["policy"] == "value_aware" and back[0]["value_score_pct"] == 50.0


def test_ablation_variants_are_valid_and_runnable():
    from satsched.experiments import ABLATIONS, run_variant

    assert "full_engine" in ABLATIONS and ABLATIONS["full_engine"] == {}
    row = run_variant(("storage_tight", "no_prices", 0))
    assert row["policy"] == "no_prices" and 0 <= row["value_score_pct"] <= 100


def test_run_grid_and_save(tmp_path):
    rows = run_grid(["nominal"], ["bent_pipe"], [0], workers=1)
    assert len(rows) == 1 and rows[0]["policy"] == "bent_pipe"
    summary = save_results(rows, tmp_path)
    assert (tmp_path / "runs.csv").exists() and (tmp_path / "summary.md").exists()
    assert summary[0]["n_seeds"] == 1
