from motorcad_studio.solvers.motorcad_runtime import finalize_geometry_recovery


def test_successful_motorcad_recovery_promotes_final_geometry_gate():
    result = finalize_geometry_recovery({
        "geometry_api_succeeded": False,
        "geometry_auto_recovery_attempted": True,
        "geometry_auto_recovery_succeeded": True,
        "geometry_recovery_return": None,
        "geometry_recheck_return": None,
        "geometry_adjustments": {
            "slot_opening": {"before": 2.0, "after": 1.95, "explicit": False},
        },
    })
    assert result["geometry_initial_api_succeeded"] is False
    assert result["geometry_api_succeeded"] is True
    assert result["geometry_recovered"] is True


def test_explicit_parameter_adjustment_never_promotes_recovery():
    result = finalize_geometry_recovery({
        "geometry_api_succeeded": False,
        "geometry_auto_recovery_attempted": True,
        "geometry_auto_recovery_succeeded": True,
        "geometry_recheck_return": None,
        "blocking_adjustments": {
            "air_gap": {"before": 1.0, "after": 1.1, "explicit": True},
        },
    })
    assert result["geometry_api_succeeded"] is False
    assert "geometry_recovered" not in result


def test_no_recovery_keeps_original_geometry_state():
    result = finalize_geometry_recovery({
        "geometry_api_succeeded": True,
        "geometry_auto_recovery_attempted": False,
        "geometry_auto_recovery_succeeded": None,
    })
    assert result["geometry_api_succeeded"] is True
    assert "geometry_recovered" not in result
