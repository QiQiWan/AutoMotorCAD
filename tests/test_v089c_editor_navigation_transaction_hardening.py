from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v089c_navigation_transaction_authority_precedes_editors_and_owns_route_commit():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    nav_asset = '/static/routing/navigation-transaction.js?v=0.89.9'
    assert nav_asset in html
    assert html.index(nav_asset) < html.index('/static/app.js?v=0.89.9')
    assert html.index(nav_asset) < html.index('/static/design/editor.js?v=0.89.9')
    assert html.index(nav_asset) < html.index('/static/analysis/unified-configuration.js?v=0.89.9')
    source = (STATIC / "routing" / "navigation-transaction.js").read_text(encoding="utf-8")
    for token in (
        "NavigationTransactionAuthorityV1",
        "SUPERSEDED",
        "mcs:navigation-transaction-committed",
        "withActionLock",
        "beforeunload",
        "hasUnsafeChanges",
    ):
        assert token in source
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    assert "MCSNavigationTransaction.run" in router
    assert "browser:popstate" in router
    assert "project-editor:close" in router
    assert "lastStablePath" in router
    assert "rollback" in router


def test_v089c_editor_and_analysis_frontends_have_transaction_guards_and_stable_replay_keys():
    editor = (STATIC / "design" / "editor.js").read_text(encoding="utf-8")
    analysis = (STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8")
    app_source = (STATIC / "app.js").read_text(encoding="utf-8")
    dialogs = (STATIC / "dialogs.js").read_text(encoding="utf-8")

    assert "commit_key: commitKey" in editor
    assert "idempotent_replay" in editor
    prepare_segment = editor.split("async function prepareRouteChange", 1)[1].split("document.addEventListener('click'", 1)[0]
    assert "leavePrepared = true" in prepare_segment
    assert "verification?.dispose" not in prepare_segment
    assert "mcs:navigation-transaction-committed" in editor

    for token in (
        "flushCurrentAnalysisEditor",
        "currentStepDirty",
        "input-domain-switch",
        "hmi-mode-change",
        "analysis-refresh",
        "stableSubmissionKey",
        "submission_key:submissionKey",
        "id:'analysis-editor'",
        "analysis-submit:",
    ):
        assert token in analysis

    for token in (
        "project-editor-unsaved-v089c",
        "保存并继续",
        "id:'project-editor'",
        "project-editor-save:",
        "project-create",
        "project-manager:trash-toggle",
    ):
        assert token in app_source

    assert "closeAll" in dialogs
    assert "actionFired" in dialogs
    assert "setTimeout(remove,320)" in dialogs


def test_v089c_design_draft_commit_replay_returns_exact_revision_without_duplicate_history():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "V089-C Replay", "description": "commit replay"})
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        starter = client.post(
            f"/api/projects/{project_id}/design-starters/golden_spm_servo",
            json={"name": "Replay Motor", "inputs": {"air_gap": 0.8}},
        )
        assert starter.status_code == 201, starter.text
        solution = starter.json()
        solution_id = solution["id"]
        base = solution["revisions"][0]
        parameters = dict(base.get("parameters") or {})
        parameters["air_gap"] = float(parameters.get("air_gap", 0.8)) + 0.01

        saved = client.put(
            f"/api/solutions/{solution_id}/draft",
            json={
                "base_revision_id": base["id"],
                "parameters": parameters,
                "materials": base.get("materials") or {},
                "explicit_parameter_ids": sorted(set([*(base.get("explicit_parameter_ids") or []), "air_gap"])),
                "active_view": "radial",
                "notes": "V0.89-C replay draft",
            },
        )
        assert saved.status_code == 200, saved.text
        draft_version = saved.json()["draft"]["version"]
        commit_key = "EDC-TEST-REPLAY-0001"
        payload = {"expected_version": draft_version, "commit_key": commit_key, "notes": "V0.89-C replay commit"}

        first = client.post(f"/api/solutions/{solution_id}/draft/commit", json=payload)
        assert first.status_code == 201, first.text
        first_revision = first.json()
        assert first_revision["idempotent_replay"] is False
        assert first_revision["editor_transaction"]["commit_key"] == commit_key
        assert first_revision["editor_transaction"]["commit_contract_version"] == "0.89-C"

        after_first = client.get(f"/api/solutions/{solution_id}")
        assert after_first.status_code == 200
        revision_ids_after_first = [row["id"] for row in after_first.json()["revisions"]]

        replay = client.post(f"/api/solutions/{solution_id}/draft/commit", json=payload)
        assert replay.status_code == 201, replay.text
        replay_revision = replay.json()
        assert replay_revision["idempotent_replay"] is True
        assert replay_revision["id"] == first_revision["id"]
        assert replay_revision["revision"] == first_revision["revision"]

        after_replay = client.get(f"/api/solutions/{solution_id}")
        assert after_replay.status_code == 200
        assert [row["id"] for row in after_replay.json()["revisions"]] == revision_ids_after_first

        wrong_key = client.post(
            f"/api/solutions/{solution_id}/draft/commit",
            json={**payload, "commit_key": "EDC-TEST-REPLAY-OTHER"},
        )
        assert wrong_key.status_code == 404


def test_v089c_analysis_submission_reuses_same_key_until_success_or_contract_change():
    source = (STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8")
    assert "submissionFingerprint!==fingerprint" in source
    assert "resetSubmissionKey();contextStore()?.setExecution" in source
    assert "if(!plan?.can_submit){resetSubmissionKey()" in source
    assert "Revision 已变更，请重新运行完整计算前检查" in source
    # No per-click key generation is allowed in the execute payload anymore.
    execute_segment = source.split("/execute`,{method:'POST'", 1)[1].split("contextStore()?.setExecution", 1)[0]
    assert "newSubmissionKey()" not in execute_segment
    assert "submission_key:submissionKey" in execute_segment
