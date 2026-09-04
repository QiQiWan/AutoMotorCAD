from __future__ import annotations

import json
import subprocess
from pathlib import Path

from motorcad_studio.geometry_guard import validate_geometry_relations
from motorcad_studio.api.operations.workspace_motor_design import WorkspaceMotorDesignOperationsMixin
from motorcad_studio.models import GeometryPrecheckRequest
from motorcad_studio.registry import Registry
from motorcad_studio.template_service import TemplateService
from motorcad_studio.validation import normalize_parameters
from motorcad_studio.winding_guard import validate_winding_relations

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "motorcad_studio"
LEGACY = PACKAGE / "frontend_legacy"
STATIC = PACKAGE / "static"


def test_legacy_runtime_binds_structured_clone_to_real_window():
    source = (STATIC / "core" / "legacy-runtime.js").read_text(encoding="utf-8")
    assert "'structuredClone'" in source
    assert "WINDOW_METHODS.has(property)" in source
    # The runtime still binds structuredClone as a defense for other legacy code,
    # while the critical design editor/draft paths use JSON-safe cloning because
    # their payloads are API documents and must not depend on Window receivers.
    assert "structuredClone(value" not in (LEGACY / "design" / "editor.js").read_text(encoding="utf-8")
    assert "structuredClone(value" not in (LEGACY / "design" / "draft-service.js").read_text(encoding="utf-8")


def test_hard_refresh_route_is_primed_before_bootstrap_network_initialization():
    router = (LEGACY / "router.js").read_text(encoding="utf-8")
    app = (LEGACY / "app.js").read_text(encoding="utf-8")
    assert "function primeCurrent()" in router
    assert "document.documentElement.dataset.routeBoot='hydrating'" in router
    assert "primeCurrent,preferredRevisionEditor" in router
    startup = app[app.index("queueMicrotask(()=>{"): app.index("/* ---------------- V0.6", app.index("queueMicrotask(()=>{"))]
    assert startup.index("MCSRouter?.primeCurrent?.()") < startup.index("init().then")
    assert startup.index("await routeStart") < startup.index("initV06()")
    assert startup.index("await routeStart") < startup.index("initV011()")
    assert startup.index("await routeStart") < startup.index("loadStartupSetup(true)")


def test_afpm_stack_is_annular_rz_section_with_clear_bore():
    render_utils = (LEGACY / "design" / "render-utils.js").read_text(encoding="utf-8")
    geometry = (LEGACY / "design" / "geometry.js").read_text(encoding="utf-8")
    script = f"""
      globalThis.window=globalThis;
      window.MCS_I18N={{language:'zh',t:(zh,en)=>zh}};
      window.esc=value=>String(value??'');
      const motorObject={{
        topology_id:'afpm', flux_direction:'axial', rotor_position:'dual_disc',
        stator:{{inner_diameter_mm:132,outer_diameter_mm:204,lamination_length_mm:35,slot:{{count:12}}}},
        rotor:{{inner_diameter_mm:132,outer_diameter_mm:204,lamination_length_mm:10,magnet:{{length_mm:10,thickness_mm:30,arrangement:'axial_surface'}}}},
        shaft:{{diameter_mm:100}}, winding:{{slot_count:12,pole_count:10,turns_per_coil:37}},
        materials:{{}},parameters:{{}},derived:{{air_gap_mm:1.5}},identity:{{}},warnings:[]
      }};
      window.MCSMotorObject={{resolve:()=>motorObject}};
      eval({json.dumps(render_utils)});
      eval({json.dumps(geometry)});
      const html=window.MCSDesignGeometry.longitudinalView({{data:{{}},values:{{}},editable:false}});
      const result={{
        annular:(html.match(/data-afpm-annular=\\"true\\"/g)||[]).length,
        gap:(html.match(/data-afpm-gap=\\"true\\"/g)||[]).length,
        bore:html.includes('data-afpm-bore-shaft=\\"true\\"'),
        oldFullHeight:html.includes('height=\\"320\\"'),
        title:html.includes('AFPM 双转子单定子 r-z 装配剖面'),
      }};
      process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["annular"] >= 6
    assert payload["gap"] == 4  # two upper/lower bands for each of two air gaps
    assert payload["bore"] is True
    assert payload["oldFullHeight"] is False
    assert payload["title"] is True


def test_afpm_default_template_studio_geometry_and_winding_are_valid():
    registry = Registry(PACKAGE / "config")
    templates = TemplateService(
        PACKAGE / "seed_data" / "inventory.json",
        PACKAGE / "seed_data" / "templates",
        registry,
    )
    template = templates.get_template("e14_eMobility_AFM")
    schema = registry.parameter_schema("e14_eMobility_AFM")
    merged = normalize_parameters(dict(template.get("defaults") or {}), schema)
    geometry = validate_geometry_relations(merged, template, [])
    winding = validate_winding_relations(merged, template, [])
    assert geometry["valid"] is True, geometry.get("issues")
    assert winding["valid"] is True, winding.get("issues")
    assert template["model_source"]["active_type"] in {"registered_template", "local_mot"}


def test_motorcad_template_check_imports_normalizer_from_package_root():
    source = (PACKAGE / "api" / "operations" / "workspace_motor_design.py").read_text(encoding="utf-8")
    assert "from ...validation import normalize_parameters" in source
    assert "from .validation import normalize_parameters" not in source


def test_internal_studio_module_error_is_not_mislabeled_as_pymotorcad_missing():
    source = (PACKAGE / "api" / "operations" / "shared.py").read_text(encoding="utf-8")
    internal = source.index("'no module named' in joined and 'motorcad_studio.' in joined")
    pymotorcad = source.index("'ansys.motorcad' in joined")
    assert internal < pymotorcad



def test_afpm_template_precheck_operation_executes_after_refactor_import_fix():
    registry = Registry(PACKAGE / "config")
    templates = TemplateService(
        PACKAGE / "seed_data" / "inventory.json",
        PACKAGE / "seed_data" / "templates",
        registry,
    )
    class FakeOperations:
        pass
    fake = FakeOperations()
    fake.templates = templates
    fake.registry = registry
    fake._clean_parameter_overrides = lambda values: dict(values or {})
    payload = GeometryPrecheckRequest(parameters={}, explicit_parameter_ids=[])
    result = WorkspaceMotorDesignOperationsMixin.template_geometry_precheck(
        fake, "e14_eMobility_AFM", payload
    )
    assert result["status"] == "PASS", result
    assert result["geometry"]["valid"] is True
    assert result["winding"]["valid"] is True


def test_design_editor_failure_is_logged_and_reset_for_retry():
    source = (LEGACY / "design" / "editor.js").read_text(encoding="utf-8")
    assert "DESIGN_EDITOR_LOAD_FAILED" in source
    assert "legacy_owner" in source
    assert "wb.data = null" in source
    assert "data-retry-design-editor" in source


def test_modern_bootstrap_shields_durable_route_until_context_is_hydrated():
    source = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    assert "routeHydrationShield" in source
    assert "window.location.pathname" in source
    assert "mcs:route-ready" in source
    assert "mcs:route-error" in source
    assert "正在恢复当前工程页面" in source


def test_preflight_only_surfaces_pymotorcad_mismatch_when_deployment_declares_a_pin():
    source = (PACKAGE / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    assert 'pymotorcad_status = "WARN"' in source
    assert "required_pymotorcad" in source
    assert '"required_version": required_pymotorcad or None' in source


def test_material_library_discovers_default_database_outside_roaming_appdata(tmp_path, monkeypatch):
    from motorcad_studio.db import Database
    from motorcad_studio.material_library import MaterialLibraryService

    local = tmp_path / "Local"
    defaults_dir = local / "Ansys" / "MotorCAD" / "2026R1" / "Config"
    db_dir = local / "Ansys" / "MotorCAD" / "2026R1" / "Materials"
    defaults_dir.mkdir(parents=True)
    db_dir.mkdir(parents=True)
    solids = db_dir / "Solids.mdb"
    solids.write_text(
        "[Test Magnet]\nType=Fixed_Solid\nSolid Type=Magnet\nDensity=7500\nMagnetBrValue=1.2\n",
        encoding="utf-8",
    )
    (defaults_dir / "Defaults.INI").write_text(
        f"Solid Database File={solids}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("MOTORCAD_STUDIO_SOLIDS_DB", raising=False)
    monkeypatch.delenv("MOTORCAD_DEFAULTS_FILE", raising=False)
    service = MaterialLibraryService(Database(tmp_path / "studio.db"), tmp_path / "runtime", "2026R1")
    result = service.scan_and_import()
    assert any(Path(row["path"]) == solids.resolve() for row in result["candidates"])
    assert result["imported"]
    assert service.list_records(kind="solid", material_type="Magnet")[0]["name"] == "Test Magnet"
    assert any("localappdata" in row["source"] for row in result["diagnostics"]["searched_roots"])


def test_material_picker_auto_scans_and_surfaces_database_manager():
    library = (LEGACY / "materials" / "library.js").read_text(encoding="utf-8")
    materials = (LEGACY / "design" / "materials.js").read_text(encoding="utf-8")
    editor = (LEGACY / "design" / "editor.js").read_text(encoding="utf-8")
    assert "autoScanAttempted" in library
    assert "data-material-picker-scan-v0916" in library
    assert "data-material-open-manager-v0916" in library
    assert "材料数据库管理" in materials
    assert "material_database_path: selectedDatabase" in editor


def test_canonical_solution_cards_expose_safe_delete_action():
    source = (LEGACY / "canonical-project-flow.js").read_text(encoding="utf-8")
    actions = (LEGACY / "hmi" / "action-registry.js").read_text(encoding="utf-8")
    assert "data-canonical-delete" in source
    assert "/solutions/${encodeURIComponent(design.id)}`" in source
    assert "method:'DELETE'" in source
    assert "data-canonical-delete" in actions


def test_afpm_native_precheck_uses_linear_cross_section_policy_without_generic_auto_repair():
    solver = (PACKAGE / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    authority = (PACKAGE / "native" / "motorcad" / "readback_authority.py").read_text(encoding="utf-8")
    assert 'geometry_validation_mode": "afm_linear_cross_section" if is_afm' in solver
    afm_branch = solver[solver.index("        if is_afm:"):solver.index("        elif hasattr(mc, \"check_if_geometry_is_valid\"):")]
    assert "check_if_geometry_is_valid(1)" not in afm_branch
    assert "MotorCADAFMLinearCrossSectionValidationV1" in afm_branch
    assert 'validation_mode="afm_linear_cross_section" if is_afm' in authority
    assert "AFM geometry tree capture skipped" in authority


def test_afpm_native_geometry_readback_executes_without_generic_geometry_api_or_unbound_spatial():
    from types import SimpleNamespace
    from motorcad_studio.native.motorcad.readback_authority import NativeGeometryWindingReadbackAuthority

    class FakePlan:
        metadata = {"native_readback_contract": {"parameters": []}}
        identity = SimpleNamespace(topology_id="afpm", family_id="afpm", native_motor_type="BPM_AFM")
        design_snapshot_hash = "design-hash"
        def content_hash(self):
            return "plan-hash"

    class FakeMotorCAD:
        def check_if_geometry_is_valid(self, edit_geometry):
            raise AssertionError("generic geometry API must not be called for AFM standard-template precheck")
        def get_geometry_tree(self):
            raise AssertionError("AFM geometry tree must not be called on runtimes where it is unsupported")

    row = NativeGeometryWindingReadbackAuthority().capture_geometry(FakeMotorCAD(), FakePlan())
    assert row.valid is True
    assert row.status == "MATCH"
    assert row.validation_mode == "afm_linear_cross_section"
    assert row.validation_authority == "MotorCADAFMLinearCrossSectionValidationV1"
    assert row.spatial_geometry["status"] == "UNAVAILABLE"
    assert row.spatial_geometry["region_count"] == 0


def test_afpm_solver_precheck_keeps_generic_overlap_failure_as_nonblocking_diagnostic(tmp_path):
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

    class FakeMotorCAD:
        calls = []
        def show_magnetic_context(self):
            return None
        def check_if_geometry_is_valid(self, edit_geometry):
            self.calls.append(edit_geometry)
            if edit_geometry == 1:
                raise AssertionError("AFM automatic generic geometry repair must never run")
            raise RuntimeError('Regions "Stator" and "1Magnet1" intersect. Geometry check failed.')
        def save_to_file(self, path):
            Path(path).write_text("[Model]\n", encoding="utf-8")

    adapter = object.__new__(MotorCADSolverAdapter)
    mc = FakeMotorCAD()
    validation, warnings = adapter._validate_model(
        mc,
        {"id": "e14_eMobility_AFM", "family_id": "afpm", "defaults": {}, "winding": {}},
        [],
        {},
        [],
        tmp_path,
    )
    assert mc.calls == [0]
    assert validation["geometry_validation_mode"] == "afm_linear_cross_section"
    assert validation["geometry_effective_valid"] is True
    assert validation["geometry_api_succeeded"] is None
    assert validation["generic_geometry_api_diagnostic"]["succeeded"] is False
    assert validation["geometry_auto_recovery_attempted"] is False
    assert warnings


def test_material_library_discovers_motorcad_install_default_file_location(tmp_path, monkeypatch):
    from motorcad_studio.db import Database
    from motorcad_studio.material_library import MaterialLibraryService

    install = tmp_path / "ANSYS Inc" / "v261" / "motorcad"
    data_dir = install / "Motor-CAD Data"
    data_dir.mkdir(parents=True)
    exe = install / "MotorCAD.exe"
    exe.write_bytes(b"")
    solids = data_dir / "Solids.mdb"
    solids.write_text(
        "[N30UH]\nType=Fixed_Solid\nSolid Type=Magnet\nDensity=7500\nMagnetBrValue=1.1\n",
        encoding="utf-8",
    )
    (data_dir / "Defaults.INI").write_text(f"Solid Database File={solids}\n", encoding="utf-8")
    for key in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "USERPROFILE", "PUBLIC", "MOTORCAD_DEFAULTS_FILE"):
        monkeypatch.delenv(key, raising=False)
    service = MaterialLibraryService(Database(tmp_path / "studio.db"), tmp_path / "runtime", "2026R1", str(exe))
    result = service.scan_and_import()
    assert result["imported"]
    assert service.list_records(kind="solid", material_type="Magnet")[0]["name"] == "N30UH"
    assert any("Motor-CAD Data" in row["path"] for row in result["diagnostics"]["defaults_files"])


def test_v0917_raw_automation_identifier_is_canonicalized_before_motorcad_rpc(tmp_path):
    from motorcad_studio.automation_registry import (
        AutomationParameterParser,
        AutomationRegistryKey,
        AutomationRegistryStore,
        canonical_automation_name,
        valid_automation_name,
    )
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

    assert canonical_automation_name("当前Definition") == "CurrentDefinition"
    assert canonical_automation_name("Torque计算") == "TorqueCalculation"
    assert canonical_automation_name("BackEMF计算") == "BackEMFCalculation"
    assert canonical_automation_name("CoggingTorque计算") == "CoggingTorqueCalculation"
    assert valid_automation_name("CurrentDefinition") is True
    assert valid_automation_name("Torque计算") is True
    assert valid_automation_name("当前电流") is False
    parsed = AutomationParameterParser.parse("Automation Name,Value\n当前Definition,2\n")
    assert parsed[0]["automation_name"] == "CurrentDefinition"
    assert parsed[0]["name_normalized"] is True

    store = AutomationRegistryStore(tmp_path)
    key = AutomationRegistryKey("2026R1", "BPM", "EMag")
    try:
        store.import_text(key, "Automation Name,Value\n当前电流,1\n")
    except ValueError as exc:
        assert "非Motor-CAD原生标识符" in str(exc)
    else:
        raise AssertionError("localized raw Automation identifier must fail closed")

    class FakeMotorCAD:
        def __init__(self):
            self.values = {}
        def show_magnetic_context(self):
            return None
        def set_variable(self, name, value):
            self.values[name] = value
        def get_variable(self, name):
            return self.values[name]

    adapter = object.__new__(MotorCADSolverAdapter)
    adapter.visible = False
    adapter.strict_mapping = True
    mc = FakeMotorCAD()
    audit, warnings = adapter._apply_raw_variables(
        mc, {"当前Definition": 2}, context="EMag", audit_prefix="regression"
    )
    assert mc.values == {"CurrentDefinition": 2}
    assert audit["regression:EMag:CurrentDefinition"]["source_name"] == "当前Definition"
    assert any("当前Definition → CurrentDefinition" in row for row in warnings)


def test_v0917_installation_discovery_is_bounded_and_cached(tmp_path, monkeypatch):
    import motorcad_studio.installation as installation_module
    from motorcad_studio.installation import MotorCADInstallationManager

    root = tmp_path / "ANSYS Inc"
    exe = root / "v261" / "motorcad" / "MotorCAD.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    manager = MotorCADInstallationManager(tmp_path / "runtime")
    monkeypatch.setattr(installation_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(manager, "_standard_roots", lambda: [root])
    monkeypatch.setattr(manager, "_registry_candidates", lambda: [])

    calls = {"count": 0}
    original = manager._filesystem_candidates
    def counted():
        calls["count"] += 1
        return original()
    monkeypatch.setattr(manager, "_filesystem_candidates", counted)

    # Normal route reads never scan the host when no selection exists. Explicit
    # rescan/auto-select is the only expensive discovery path.
    first = manager.scan()
    second = manager.scan()
    forced = manager.scan(force=True)
    cached = manager.scan()
    assert calls["count"] == 1
    assert first == second == []
    assert cached == forced
    assert any(Path(row["exe_path"]) == exe.resolve() for row in forced)
    source = (PACKAGE / "installation.py").read_text(encoding="utf-8")
    filesystem_body = source[source.index("    def _filesystem_candidates"):source.index("    def selected", source.index("    def _filesystem_candidates"))]
    assert ".rglob(" not in filesystem_body
    assert '"v*/motorcad/MotorCAD.exe"' in filesystem_body


def test_v0918_selected_installation_is_a_zero_discovery_hot_path(tmp_path, monkeypatch):
    from motorcad_studio.installation import MotorCADInstallationManager

    exe = tmp_path / "ANSYS Motor-CAD" / "2026R1" / "MotorCAD.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    manager = MotorCADInstallationManager(tmp_path / "runtime")
    manager.select(str(exe))
    monkeypatch.setattr(manager, "_registry_candidates", lambda: (_ for _ in ()).throw(AssertionError("registry scan on hot path")))
    monkeypatch.setattr(manager, "_filesystem_candidates", lambda: (_ for _ in ()).throw(AssertionError("filesystem scan on hot path")))
    rows = manager.scan()
    assert len(rows) == 1
    assert rows[0]["selected"] is True
    assert Path(rows[0]["exe_path"]) == exe.resolve()


def test_v0918_analysis_toolbar_and_raw_solver_identifiers_survive_route_and_i18n_lifecycles():
    analysis = (LEGACY / "analysis" / "unified-configuration.js").read_text(encoding="utf-8")
    action_registry = (LEGACY / "hmi" / "action-registry.js").read_text(encoding="utf-8")
    i18n = (LEGACY / "i18n.js").read_text(encoding="utf-8")
    assert "mountPromise" in analysis and "refreshPromise" in analysis
    assert "loadPromise" not in analysis
    assert "#analysisCreateV076" in analysis
    assert "document.addEventListener('click'" in analysis
    assert 'data-i18n-skip translate="no"' in analysis
    assert "technicalIdentifier" in i18n
    assert "analysisCreateV076" in action_registry


def test_v0918_studio_release_does_not_pin_pymotorcad_package_version():
    import motorcad_studio.release as release
    from motorcad_studio.windows_production_qualification import qualification_matrix_spec

    assert release.REQUIRED_PYMOTORCAD_VERSION is None
    manifest = release.public_release_manifest()
    assert manifest["external_runtime"]["required_pymotorcad_version"] is None
    assert manifest["compatibility_policy"]["external_runtime"] == "capability-qualified"
    matrix = qualification_matrix_spec()
    assert matrix["environment_gates"]["pymotorcad_version"] is None
    assert matrix["environment_gates"]["pymotorcad_policy"] == "capability-qualified"
    workstation_ui = (LEGACY / "runtime" / "workstation-acceptance.js").read_text(encoding="utf-8")
    assert "pymotorcad_version==='0.8.8'" not in workstation_ui


def test_v0918_health_hot_path_does_not_construct_full_motorcad_adapter():
    source = (PACKAGE / "platform" / "system" / "service.py").read_text(encoding="utf-8")
    body = source[source.index("    def health(self)"):source.index("    def environment_manifest", source.index("    def health(self)"))]
    assert "self.adapter().capabilities()" not in body
    assert "MotorCADSolverAdapter.import_status()" in body
    assert "motorcad_health" in body


def test_v0917_solver_visualization_has_afpm_specific_geometry_and_axial_stack():
    source = (LEGACY / "workflow" / "native-context.js").read_text(encoding="utf-8")
    assert "function buildAxialMachine" in source
    assert "annularSectorPath" in source
    assert "AFPM · 双转子单定子" in source
    assert "双转子-单定子轴向堆叠" in source
    assert "magnet_arc_deg" in source
    assert "stator_lamination_length_mm" in source
    assert "air_gap_mm" in source


def test_v0917_locked_engineer_journey_stage_cannot_navigate():
    source = (LEGACY / "workflow" / "engineer-journey.js").read_text(encoding="utf-8")
    assert "btn.disabled" in source
    assert "btn.getAttribute('aria-disabled')==='true'" in source
    assert "btn.dataset.workflowGate==='BLOCKED'" in source
    assert "btn.dataset.stageStatus==='BLOCKED'" in source
    assert "window.MCSGlobalWorkflowTruth?.sync?.()" in source


def test_v0917_analysis_template_catalog_resolves_design_context_only_once():
    from motorcad_studio.analysis_guidance import AnalysisGuidanceService

    service = object.__new__(AnalysisGuidanceService)
    service.version = 1
    service.policy = {}
    service.templates = {
        "a": {"label": "A", "module": "EMag", "recipe_id": "r1", "motor_types": ["BPM"]},
        "b": {"label": "B", "module": "EMag", "recipe_id": "r2", "motor_types": ["BPM"]},
        "c": {"label": "C", "module": "Therm", "recipe_id": "r3", "motor_types": ["BPM"]},
    }
    calls = {"design": 0, "motor": 0, "catalog": 0}
    def design_context(_rid):
        calls["design"] += 1
        return {"id": _rid}, {"id": "D1"}
    def motor_context(_design):
        calls["motor"] += 1
        return {"motor_type_id": "BPM", "template_id": "e14_eMobility_AFM"}
    class Platform:
        def analysis_catalog(self, motor_type, template_id):
            calls["catalog"] += 1
            return {"recipes": [
                {"id": "r1", "module": "EMag", "available": True},
                {"id": "r2", "module": "EMag", "available": True},
                {"id": "r3", "module": "Therm", "available": True},
            ]}
    service._design_context = design_context
    service._motor_context = motor_context
    service.platform = Platform()
    result = service.list_templates("REV-1")
    assert len(result["templates"]) == 3
    assert all(row["available"] for row in result["templates"])
    assert calls == {"design": 1, "motor": 1, "catalog": 1}


def test_v0917_winding_validator_separates_readback_sentinel_from_new_native_errors():
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
    from motorcad_studio.winding_guard import parse_motorcad_winding_messages

    sentinel = "15:20:45 : pymotorcad: Coil index too high. Check number of coils per path."
    assert parse_motorcad_winding_messages([sentinel])["valid"] is False
    assert "MOTORCAD_WINDING_COIL_INDEX_OUT_OF_RANGE" in parse_motorcad_winding_messages([sentinel])["codes"]

    before = ["15:20:44 : Loaded file: e14.mtt", sentinel]
    after = [
        "15:20:44 : Loaded file: e14.mtt\n"
        + sentinel
        + "\n15:20:46 : Regions Stator and StatorAir intersect.\n15:20:46 : Geometry check failed."
    ]
    delta = MotorCADSolverAdapter._message_delta(before, after)
    assert not any("Coil index too high" in line for line in delta)
    assert parse_motorcad_winding_messages(delta)["valid"] is True

    actual_new = MotorCADSolverAdapter._message_delta(before, [*before, sentinel])
    assert parse_motorcad_winding_messages(actual_new)["valid"] is False
