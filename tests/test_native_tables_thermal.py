from pathlib import Path

from motorcad_studio.native_tables import parse_thermal_node_table


def test_parse_thermal_node_table_accepts_native_node_temperature_rows(tmp_path: Path) -> None:
    source = tmp_path / "steady.csv"
    source.write_text(
        "Motor-CAD Steady State Results\n"
        "Node,Temperature (C),Heat Flow (W)\n"
        "Winding,174.4666,485.05\n"
        "Stator,131.2,310.4\n"
        "Housing,72.4,174.65\n",
        encoding="utf-8",
    )

    table, error = parse_thermal_node_table(source)

    assert error is None
    assert table is not None
    assert table["row_count"] == 3
    assert table["semantic_columns"]["node"] == "Node"
    assert table["semantic_columns"]["temperature"] == "Temperature (C)"
    assert table["semantic_columns"]["heat_flow"] == "Heat Flow (W)"
    assert table["topology_edges_available"] is False
    assert table["rows"][0] == {
        "node_id": "Winding",
        "name": "Winding",
        "temperature_c": 174.4666,
        "heat_flow_w": 485.05,
    }


def test_parse_thermal_node_table_rejects_summary_without_node_identity(tmp_path: Path) -> None:
    source = tmp_path / "steady-summary.csv"
    source.write_text(
        "Motor-CAD Steady State Results\n"
        "Metric,Value\n"
        "Winding Max Temperature,174.4666\n"
        "Total Loss,485.05\n",
        encoding="utf-8",
    )

    table, error = parse_thermal_node_table(source)

    assert table is None
    assert error == "thermal_temperature_column_not_found"


def test_parse_thermal_node_table_requires_node_like_identity(tmp_path: Path) -> None:
    source = tmp_path / "steady-temperature-summary.csv"
    source.write_text(
        "Motor-CAD Steady State Results\n"
        "Temperature (C),Value\n"
        "174.4666,1\n"
        "72.4,2\n",
        encoding="utf-8",
    )

    table, error = parse_thermal_node_table(source)

    assert table is None
    assert error == "thermal_node_identity_column_not_found"
