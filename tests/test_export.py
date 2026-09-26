import csv
import json

from satsched.export import build_demo, eclipses, export_dataset, scenario_dict, write_demo_js
from satsched.scenarios import get_scenario
from satsched.simulator.engine import make_environment


def test_scenario_dict_is_json_serialisable():
    d = scenario_dict(get_scenario("nominal"))
    assert json.loads(json.dumps(d))["name"] == "nominal"
    assert d["data_types"][0]["processor"] == "gpu"


def test_eclipses_follow_orbit_geometry():
    for name in ("nominal", "nominal_synthetic"):
        sc = get_scenario(name)
        schedule, _ = make_environment(sc, 0)
        ecl = eclipses(schedule, sc.duration_s)
        assert ecl and all(b > a for a, b in ecl) and ecl[-1][1] <= sc.duration_s
        durations = [b - a for a, b in ecl[1:-1]]
        assert all(abs(d - sc.orbit.eclipse_s) < 120 for d in durations)  # ~34-35 min shadow per orbit


def test_demo_payload_records_geometry_provenance():
    from satsched.export import geometry_meta

    real = geometry_meta(get_scenario("nominal"))
    assert real["source"] == "real" and real["norad_id"] == 40697
    assert geometry_meta(get_scenario("nominal_synthetic"))["source"] == "synthetic"


def test_export_dataset_matches_simulation_environment(tmp_path):
    written = export_dataset(["nominal"], [5], tmp_path)
    assert (tmp_path / "scenarios.json") in written
    with (tmp_path / "nominal" / "seed_005" / "items.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    _, workload = make_environment(get_scenario("nominal"), 5)
    assert len(rows) == len(workload.items)
    assert int(rows[3]["useful_truth"]) == int(workload.truth[3])


def test_build_demo_payload_has_all_policies(tmp_path):
    payload = build_demo("nominal", seed=2, every=8, decision_limit=50)
    assert set(payload["policies"]) == {"bent_pipe", "process_all", "priority_rules", "bandwidth_rules", "value_aware"}
    va = payload["policies"]["value_aware"]
    assert len(va["series"]["t_min"]) == len(va["series"]["dl_sent_mb"])
    assert 0 < len(payload["decisions"]) <= 50
    assert any(d["why"] for d in payload["decisions"])
    out = write_demo_js(payload, tmp_path / "data.js")
    text = out.read_text()
    assert text.startswith("window.SATSCHED_DATA = ")
    json.loads(text[len("window.SATSCHED_DATA = "):-2])
