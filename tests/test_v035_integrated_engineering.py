from __future__ import annotations

import json
from pathlib import Path

from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.result_viewer import ResultViewerService
from motorcad_studio.thermal_network import normalize_thermal_network
from motorcad_studio.version import __version__
from motorcad_studio.winding_definition import build_winding_definition_evidence, parse_winding_pattern_text


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
V035 = (ROOT / "motorcad_studio" / "static" / "v035.js").read_text(encoding="utf-8")


def test_v035_version_and_asset_order():
    assert __version__ == "0.35.0"
    assert 'data-studio-version="0.35.0"' in INDEX
    assert '/static/v035.js?v=0.35.0' in INDEX
    assert INDEX.index("/static/v031.js") < INDEX.index("/static/v035.js") < INDEX.index("/static/router.js")


def test_winding_pattern_becomes_structured_native_evidence(tmp_path: Path):
    text = "Coil,Phase,Go Slot,Return Slot,Turns,Parallel Path\n1,1,1,6,80,1\n2,2,2,7,80,1\n"
    parsed = parse_winding_pattern_text(text)
    assert parsed["structured"] is True
    assert parsed["coil_count"] == 2
    assert parsed["coils"][0]["go_slot"] == 1
    pattern = tmp_path / "winding_pattern.txt"
    pattern.write_text(text, encoding="utf-8")
    evidence = build_winding_definition_evidence(
        pattern,
        {"id": "demo"},
        {"slot_count": 12, "turns_per_coil": 80},
        {"winding_validation": {"status": "PASS", "details": {"fundamental_winding_factor": 0.94}}},
    )
    assert evidence["definition_status"] == "STRUCTURED_NATIVE"
    assert evidence["source_sha256"]
    assert {"coil_table", "winding_factor"}.issubset(evidence["verified_native_fields"])


def test_unknown_winding_format_stays_raw_evidence():
    parsed = parse_winding_pattern_text("Motor-CAD winding output\nrelease-specific opaque data")
    assert parsed["structured"] is False
    assert parsed["parse_mode"] == "unrecognized"
    assert parsed["coils"] == []


def test_thermal_contract_distinguishes_native_network_from_summary():
    native = normalize_thermal_network({"tables": {"thermal_network": {
        "nodes": [{"id": "w", "name": "Winding", "temperature": 91.2}, {"id": "h", "name": "Housing", "temperature": 52}],
        "edges": [{"from": "w", "to": "h", "resistance": 0.18, "heat_flow": 220}],
    }}})
    assert native["native"] is True
    assert native["completeness"] == {"topology": True, "temperatures": True, "resistances": True}
    summary = normalize_thermal_network({"scalars": {"winding_average_temperature_c": 88.0}}, {"ambient_temperature_c": 25})
    assert summary["native"] is False
    assert summary["status"] == "SUMMARY_ONLY"
    assert summary["edges"] == []
    assert "未将其表示为" in summary["disclaimer"]


def test_fea_normalization_exposes_fields_regions_connectivity_and_probe_capability(tmp_path: Path):
    raw = tmp_path / "fea.csv"
    raw.write_text(
        "Step,RegCode,X,Y,B,Pt,TriIndex,Node1,Node2,Node3\n"
        "0,stator,0,0,1.2,0.01,1,1,2,3\n"
        "1,rotor,1,1,1.5,0.02,2,2,3,4\n",
        encoding="utf-8",
    )
    result = normalize_fea_csv(raw, tmp_path / "frames", 100)
    assert result["normalized"] is True
    assert result["available_fields"] == ["b", "pt"]
    assert result["regions"] == ["rotor", "stator"]
    assert result["capabilities"]["nearest_point_probe"] is True
    assert result["capabilities"]["connectivity_metadata"] is True
    assert result["capabilities"]["mesh_edges"] is False
    frame = json.loads((tmp_path / "frames" / "frame_0000.json").read_text(encoding="utf-8"))
    assert frame["points"][0]["element_id"] == 1
    assert frame["points"][0]["node_ids"] == [1, 2, 3]


class _Registry:
    def parameter_schema(self, _template_id=None):
        return {"air_gap": {"label": "气隙", "unit": "mm"}}

    def output_schema(self, _template_id=None):
        return {
            "efficiency_percent": {"label": "效率", "unit": "%"},
            "total_loss_w": {"label": "总损耗", "unit": "W"},
        }


def _case(case_id: str, air_gap: float, speed: float, fidelity: str, efficiency: float, loss: float) -> dict:
    return {
        "case": {"id": case_id, "task_id": "T", "template_id": "demo", "execution_status": "SUCCEEDED", "quality_status": "PASS", "design_revision_id": f"D-{case_id}", "scenario_revision_id": f"S-{case_id}", "run_configuration_id": f"R-{case_id}"},
        "inputs": {"parameters": {"air_gap": air_gap}, "scenario": {"shaft_speed_rpm": speed}, "solver_settings": {"fidelity": fidelity}, "fingerprint": {"hash": case_id}},
        "results": {"scalars": {"efficiency_percent": efficiency, "total_loss_w": loss}},
        "warnings": [], "quality": [],
    }


def test_case_compare_v2_covers_domains_pareto_traceability_and_descriptive_influence():
    service = object.__new__(ResultViewerService)
    service.registry = _Registry()
    payloads = {
        "A": _case("A", 1.0, 3000, "standard", 94.0, 220),
        "B": _case("B", 0.8, 4000, "high", 95.0, 210),
        "C": _case("C", 1.2, 4000, "standard", 93.5, 250),
    }
    service.case_payload = payloads.get
    result = service.compare_cases(["A", "B", "C"])
    assert result["comparison_schema_version"] == 2
    assert result["pareto"]["case_ids"] == ["B"]
    assert all(result["changed_domains"][key] for key in ("design", "scenario", "solver"))
    assert len(result["traceability"]) == 3
    assert result["decision_summary"][1]["improvements"] == ["efficiency_percent", "total_loss_w"]
    assert result["influence"]
    assert all(row["interpretation"] == "descriptive_only_not_causal" for row in result["influence"])


def test_frontend_exposes_native_playback_probe_and_decision_boundaries():
    for token in (
        "fea-frames", "fea-probe", "2–98% 分位", "不插值伪造等值线",
        "thermal_network", "DECISION WORKSPACE", "描述性影响", "PARETO",
    ):
        assert token in V035
