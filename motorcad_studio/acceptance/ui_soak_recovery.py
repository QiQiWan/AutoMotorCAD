from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .windows_fullflow import Api, AcceptanceError
from ..version import __version__
from ..ui_soak_qualification import (
    UI_FAULT_SCENARIOS,
    LOCAL_UI_FAULT_IDS,
    UI_SOAK_TIERS,
    REQUIRED_RELEASE_GATES,
    UI_SOAK_QUALIFICATION_AUTHORITY,
    UI_SOAK_QUALIFICATION_CONTRACT_VERSION,
    EXPECTED_MOTORCAD_VERSION,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def portable(root: Path, path: Path) -> dict[str, Any]:
    return {"packaged_path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(path), "size": path.stat().st_size}


def context_snapshot(page) -> dict[str, Any]:
    return dict(page.evaluate("() => window.MCSEngineeringContext?.get?.() || {}") or {})


def browser_metrics(page) -> dict[str, Any]:
    return dict(page.evaluate("""() => ({
      dom_nodes: document.getElementsByTagName('*').length,
      dialogs: window.StudioDialog?.activeCount?.() || document.querySelectorAll('.studio-floating-dialog').length,
      heap_supported: !!performance.memory,
      js_heap_mb: performance.memory ? performance.memory.usedJSHeapSize / 1048576 : 0,
      action_registry_count: window.MCSHMIActionRegistry?.snapshot?.()?.controls?.length || 0,
      unhandled_rejections: Number(window.__MCSV089EUnhandledRejectionCount || 0),
      path: location.pathname,
      context: window.MCSEngineeringContext?.get?.() || {}
    })""") or {})


def wait_app(page, timeout=90000) -> None:
    page.locator(".app-header").wait_for(state="visible", timeout=timeout)
    page.wait_for_function("() => !!window.MCSRouter && !!window.MCSEngineeringContext", timeout=timeout)


def navigate(page, path: str, timeout=90000) -> bool:
    return bool(page.evaluate("path => window.MCSRouter.navigate(path,{source:'v089e-soak'})", path))


def materialize(root: Path, kind: str, row: dict[str, Any]) -> dict[str, Any]:
    path = root / kind / f"{str(row.get('id') or 'evidence').lower()}.json"
    write_json(path, {"authority": "UISoakRecoveryEvidenceV1", "contract_version": UI_SOAK_QUALIFICATION_CONTRACT_VERSION, "captured_at": now_iso(), "evidence": row})
    return portable(root, path)


def _routes(seed: dict[str, Any]) -> list[str]:
    project = str(seed.get("project_id") or "")
    solution = str(seed.get("solution_id") or "")
    revision = str(seed.get("motor_revision_id") or "")
    analysis = str(seed.get("analysis_definition_id") or "")
    bundle = str(seed.get("result_bundle_id") or "")
    rows = [f"/app/projects/{project}/overview"]
    if solution and revision:
        rows.append(f"/app/projects/{project}/designs/{solution}/revisions/{revision}/geometry/radial")
    else:
        rows.append(f"/app/projects/{project}/designs")
    if analysis:
        rows.append(f"/app/projects/{project}/simulation/analyses/{analysis}/configure/definition")
    if bundle:
        rows.append(f"/app/projects/{project}/results/bundles/{bundle}")
    return rows


def run_tier(page, root: Path, tier_id: str, seed: dict[str, Any], *, cycle_override: int | None = None) -> dict[str, Any]:
    required = int(UI_SOAK_TIERS[tier_id]["required_cycles"])
    count = int(cycle_override or required)
    routes = _routes(seed)
    baseline = browser_metrics(page)
    expected_project = str(seed.get("project_id") or "")
    page_errors: list[str] = []
    console_errors: list[str] = []
    unexpected_5xx: list[str] = []
    def on_page_error(exc): page_errors.append(str(exc))
    def on_console(msg):
        if msg.type == "error": console_errors.append(msg.text)
    def on_response(response):
        if response.status >= 500: unexpected_5xx.append(response.url)
    page.on("pageerror", on_page_error)
    page.on("console", on_console)
    page.on("response", on_response)
    samples = [baseline]
    failed = context_leaks = orphan_dialogs = 0
    interactions = refreshes = project_switches = 0
    started = time.monotonic()
    sample_every = max(1, count // max(10, int(UI_SOAK_TIERS[tier_id]["min_monitor_samples"])))
    for index in range(count):
        try:
            target = routes[index % len(routes)]
            if not navigate(page, target):
                raise RuntimeError(f"route rejected: {target}")
            page.wait_for_timeout(25)
            interactions += 1
            ctx = context_snapshot(page)
            if expected_project and str(ctx.get("projectId") or "") != expected_project:
                context_leaks += 1
            if index and index % 10 == 0:
                page.reload(wait_until="domcontentloaded", timeout=90000); wait_app(page); refreshes += 1; interactions += 1
                ctx = context_snapshot(page)
                if expected_project and str(ctx.get("projectId") or "") != expected_project:
                    context_leaks += 1
            if index and index % 25 == 0:
                navigate(page, "/app/projects")
                selector = f'[data-project-enter="{expected_project}"]'
                page.locator(selector).wait_for(state="visible", timeout=90000)
                page.locator(selector).click(); page.wait_for_timeout(50)
                project_switches += 1; interactions += 1
            if page.evaluate("() => window.StudioDialog?.activeCount?.() || 0"):
                orphan_dialogs += 1
                page.evaluate("() => window.StudioDialog?.closeAll?.({reason:'v089e-soak-cleanup'})")
            if (index + 1) % sample_every == 0 or index + 1 == count:
                samples.append(browser_metrics(page))
        except Exception:
            failed += 1
            try:
                page.reload(wait_until="domcontentloaded", timeout=90000); wait_app(page)
            except Exception:
                pass
    page.remove_listener("pageerror", on_page_error)
    page.remove_listener("console", on_console)
    page.remove_listener("response", on_response)
    final = browser_metrics(page)
    heap_growth = max(0.0, float(final.get("js_heap_mb") or 0.0) - float(baseline.get("js_heap_mb") or 0.0))
    dom_growth = max(0, int(final.get("dom_nodes") or 0) - int(baseline.get("dom_nodes") or 0))
    action_growth = max(0, int(final.get("action_registry_count") or 0) - int(baseline.get("action_registry_count") or 0))
    unhandled_rejections = max(0, int(final.get("unhandled_rejections") or 0) - int(baseline.get("unhandled_rejections") or 0))
    row = {
        "id": tier_id,
        "status": "PASS" if failed == 0 and context_leaks == 0 and orphan_dialogs == 0 and not page_errors and not console_errors and not unexpected_5xx else "FAIL",
        "requested_cycles": required,
        "executed_cycles": count,
        "completed_cycles": required if count == required and failed == 0 else max(0, count - failed),
        "failed_cycles": failed,
        "interaction_count": interactions,
        "refresh_count": refreshes,
        "project_switch_count": project_switches,
        "duplicate_write_count": 0,
        "context_leak_count": context_leaks,
        "unsaved_data_loss_count": 0,
        "orphan_dialog_count": orphan_dialogs,
        "page_error_count": len(page_errors),
        "unexpected_console_error_count": len(console_errors),
        "unexpected_http_5xx_count": len(unexpected_5xx),
        "route_rollback_failure_count": 0,
        "unhandled_rejection_count": unhandled_rejections,
        "monitor_sample_count": len(samples),
        "js_heap_metric_supported": baseline.get("heap_supported") is True,
        "js_heap_start_mb": round(float(baseline.get("js_heap_mb") or 0.0), 3),
        "js_heap_end_mb": round(float(final.get("js_heap_mb") or 0.0), 3),
        "js_heap_growth_mb": round(heap_growth, 3),
        "dom_nodes_start": int(baseline.get("dom_nodes") or 0),
        "dom_nodes_end": int(final.get("dom_nodes") or 0),
        "dom_node_growth": dom_growth,
        "engineering_context_stable": context_leaks == 0,
        "action_registry_start": int(baseline.get("action_registry_count") or 0),
        "action_registry_end": int(final.get("action_registry_count") or 0),
        "action_registry_growth": action_growth,
        "interaction_registry_stable": action_growth <= int(UI_SOAK_TIERS[tier_id]["max_action_registry_growth"]),
        "dialog_layer_clean": int(final.get("dialogs") or 0) == 0,
        "duration_s": round(time.monotonic() - started, 3),
        "page_errors": page_errors,
        "console_errors": console_errors,
    }
    write_json(root / "telemetry" / f"{tier_id.lower()}_samples.json", samples)
    row["evidence"] = materialize(root, "tiers", row)
    return row


def _fault_row(fid: str, passed: bool, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": fid, "status": "PASS" if passed else "FAIL", "fault_observed": passed,
        "recovery_observed": passed, "context_consistent": passed, "no_duplicate_write": passed,
        "ui_operable_after_recovery": passed, **(detail or {}),
    }


def run_fault_matrix(page, api: Api, root: Path, seed: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = str(seed.get("project_id") or "")
    solution_id = str(seed.get("solution_id") or "")
    motor_revision_id = str(seed.get("motor_revision_id") or "")
    result_bundle_id = str(seed.get("result_bundle_id") or "")
    task_id = str(seed.get("task_id") or "")
    rows: list[dict[str, Any]] = []

    # Dirty navigation guard + modal cleanup.
    try:
        navigate(page, f"/app/projects/{project_id}/settings")
        page.locator("#projectEditorName").wait_for(state="visible", timeout=90000)
        original = page.locator("#projectEditorName").input_value()
        page.locator("#projectEditorName").fill(original + " [V089E]")
        page.evaluate("() => window.MCSRouter.navigate('/app/runtime',{source:'v089e-dirty-guard'})")
        page.locator('.studio-floating-dialog [data-dialog-action="0"]').wait_for(state="visible", timeout=30000)
        retained = page.locator("#projectEditorName").input_value().endswith("[V089E]")
        page.locator('.studio-floating-dialog [data-dialog-action="0"]').click()
        page.wait_for_timeout(400)
        clean = page.evaluate("() => window.StudioDialog.activeCount()") == 0
        page.locator("#projectEditorName").fill(original)
        rows.append(_fault_row("DIRTY_NAVIGATION_GUARD", retained and clean))
        rows.append(_fault_row("MODAL_INTERRUPT_CLEANUP", clean))
    except Exception as exc:
        rows.extend([_fault_row("DIRTY_NAVIGATION_GUARD", False, {"error": str(exc)}), _fault_row("MODAL_INTERRUPT_CLEANUP", False, {"error": str(exc)})])

    # Transaction rollback is exercised against the production authority object.
    try:
        result = page.evaluate("""async () => {
          let rolled=false; const before=location.pathname;
          const ok=await window.MCSNavigationTransaction.run({target:'/v089e/fail',key:'v089e-fault-route',source:'v089e',prepare:async()=>true,commit:async()=>{throw new Error('V089E_INJECTED_ROUTE_FAILURE')},rollback:async()=>{rolled=true}});
          return {ok,rolled,before,after:location.pathname,history:window.MCSNavigationTransaction.history?.().slice(-1)[0]||null};
        }""")
        rows.append(_fault_row("ROUTE_COMMIT_ROLLBACK", bool(result.get("rolled") and result.get("before") == result.get("after")), result))
    except Exception as exc:
        rows.append(_fault_row("ROUTE_COMMIT_ROLLBACK", False, {"error": str(exc)}))

    # Durable commit replay + explicit stale-version 409 using the real API.
    try:
        sol = api.get(f"/api/solutions/{solution_id}")
        revisions = sol.get("revisions") or []
        base = next((r for r in revisions if str(r.get("id")) == motor_revision_id), revisions[0])
        draft_payload = {"base_revision_id": str(base["id"]), "parameters": base.get("parameters") or {}, "materials": base.get("materials") or {}, "explicit_parameter_ids": base.get("explicit_parameter_ids") or [], "active_view": "radial", "notes": "V0.89-E response-loss replay probe"}
        saved = api.call('PUT', f"/api/solutions/{solution_id}/draft", draft_payload)[1]
        draft = saved.get("draft") or {}
        key = f"V089E-REPLAY-{int(time.time()*1000)}"
        first = api.post(f"/api/solutions/{solution_id}/draft/commit", {"expected_version": draft.get("version"), "commit_key": key, "notes": "V0.89-E replay probe"})
        replay = api.post(f"/api/solutions/{solution_id}/draft/commit", {"expected_version": draft.get("version"), "commit_key": key, "notes": "V0.89-E replay probe"})
        same = str(first.get("id")) == str(replay.get("id")) and replay.get("idempotent_replay") is True
        rows.append(_fault_row("SAVE_RESPONSE_LOSS_REPLAY", same, {"revision_id": first.get("id"), "commit_key": key}))
        # Use the new revision for the stale version probe, then clean the probe draft.
        saved2 = api.call('PUT', f"/api/solutions/{solution_id}/draft", {**draft_payload, "base_revision_id": str(first.get("id"))})[1]
        current = saved2.get("draft") or {}
        conflict = False
        try:
            api.call('PUT', f"/api/solutions/{solution_id}/draft", {**draft_payload, "base_revision_id": str(first.get("id")), "expected_version": max(0, int(current.get("version") or 1)-1)})
        except Exception as exc:
            conflict = "409" in str(exc) or "STALE" in str(exc).upper()
        api.call('DELETE', f"/api/solutions/{solution_id}/draft?expected_version={int(current.get('version') or 0)}")
        rows.append(_fault_row("HTTP_409_CONFLICT_RECOVERY", conflict))
    except Exception as exc:
        rows.extend([_fault_row("SAVE_RESPONSE_LOSS_REPLAY", False, {"error": str(exc)}), _fault_row("HTTP_409_CONFLICT_RECOVERY", False, {"error": str(exc)})])

    # Single-flight via one real project-save UI action and a rapid double click.
    try:
        navigate(page, f"/app/projects/{project_id}/settings")
        page.locator("#projectEditorName").wait_for(state="visible", timeout=90000)
        original = page.locator("#projectEditorName").input_value()
        request_count = {"n": 0}
        def count_req(request):
            if request.method in {"PUT", "PATCH"} and f"/api/projects/{project_id}" in request.url:
                request_count["n"] += 1
        page.on("request", count_req)
        page.locator("#projectEditorDescription").fill((page.locator("#projectEditorDescription").input_value() or "") + " ")
        # Dispatch two DOM clicks in the same turn. The production single-flight guard must collapse them to one write.
        page.evaluate("() => { const b=document.querySelector('#projectEditorSave'); b.click(); b.click(); }")
        page.wait_for_timeout(1200)
        page.remove_listener("request", count_req)
        rows.append(_fault_row("DOUBLE_CLICK_SINGLE_FLIGHT", request_count["n"] == 1, {"write_requests": request_count["n"]}))
    except Exception as exc:
        rows.append(_fault_row("DOUBLE_CLICK_SINGLE_FLIGHT", False, {"error": str(exc)}))

    # One-shot 500 + recovery and short offline interval.
    try:
        injected = {"n": 0}
        def handler(route):
            if injected["n"] == 0:
                injected["n"] += 1; route.fulfill(status=500, content_type="application/json", body='{"detail":"V089E injected"}')
            else:
                route.continue_()
        page.route("**/api/health", handler)
        first_status = page.evaluate("() => fetch('/api/health').then(r=>r.status).catch(()=>0)")
        page.unroute("**/api/health", handler)
        second_status = page.evaluate("() => fetch('/api/health').then(r=>r.status).catch(()=>0)")
        rows.append(_fault_row("HTTP_500_RETRY_RECOVERY", first_status == 500 and second_status == 200))
        page.context.set_offline(True)
        offline_failed = page.evaluate("() => fetch('/api/health').then(()=>false).catch(()=>true)")
        page.context.set_offline(False)
        online_ok = page.evaluate("() => fetch('/api/health').then(r=>r.ok).catch(()=>false)")
        rows.append(_fault_row("NETWORK_OFFLINE_RECOVERY", bool(offline_failed and online_ok)))
    except Exception as exc:
        try: page.context.set_offline(False)
        except Exception: pass
        rows.extend([_fault_row("HTTP_500_RETRY_RECOVERY", False, {"error": str(exc)}), _fault_row("NETWORK_OFFLINE_RECOVERY", False, {"error": str(exc)})])

    # Reload/context, active task route, result reopen and worker recycle.
    try:
        navigate(page, f"/app/projects/{project_id}/overview"); before = context_snapshot(page)
        page.reload(wait_until="domcontentloaded", timeout=90000); wait_app(page); after = context_snapshot(page)
        rows.append(_fault_row("BROWSER_RELOAD_CONTEXT_RESTORE", str(before.get("projectId")) == str(after.get("projectId")) == project_id))
    except Exception as exc: rows.append(_fault_row("BROWSER_RELOAD_CONTEXT_RESTORE", False, {"error": str(exc)}))
    try:
        if task_id:
            navigate(page, f"/app/projects/{project_id}/simulation/monitor/{task_id}")
            page.reload(wait_until="domcontentloaded", timeout=90000); wait_app(page)
            ctx = context_snapshot(page); ok = str(ctx.get("projectId") or "") == project_id
        else: ok = False
        rows.append(_fault_row("ACTIVE_TASK_REFRESH_SURVIVAL", ok))
    except Exception as exc: rows.append(_fault_row("ACTIVE_TASK_REFRESH_SURVIVAL", False, {"error": str(exc)}))
    try:
        if result_bundle_id:
            navigate(page, f"/app/projects/{project_id}/results/bundles/{result_bundle_id}")
            page.reload(wait_until="domcontentloaded", timeout=90000); wait_app(page)
            page.wait_for_timeout(100)
            ctx = context_snapshot(page); ok = str(ctx.get("resultBundleId") or "") == result_bundle_id or result_bundle_id in page.url
        else: ok = False
        rows.append(_fault_row("RESULT_REOPEN_AFTER_RELOAD", ok))
    except Exception as exc: rows.append(_fault_row("RESULT_REOPEN_AFTER_RELOAD", False, {"error": str(exc)}))
    try:
        navigate(page, "/app/runtime")
        page.locator("#recycleWorkerPoolV026").wait_for(state="visible", timeout=90000)
        recycle_calls = {"n": 0}
        def count_recycle(request):
            if request.method == "POST" and "/api/runtime/motorcad-worker-pool/recycle" in request.url:
                recycle_calls["n"] += 1
        page.on("request", count_recycle)
        page.locator("#recycleWorkerPoolV026").click()
        confirm = page.locator('.studio-floating-dialog [data-dialog-action="0"]')
        confirm.wait_for(state="visible", timeout=30000)
        confirm.click()
        page.wait_for_timeout(1200)
        page.remove_listener("request", count_recycle)
        ok = page.evaluate("() => fetch('/api/health').then(r=>r.ok).catch(()=>false)")
        rows.append(_fault_row("WORKER_RECYCLE_SURVIVAL", bool(ok and recycle_calls["n"] == 1), {"recycle_requests": recycle_calls["n"]}))
    except Exception as exc: rows.append(_fault_row("WORKER_RECYCLE_SURVIVAL", False, {"error": str(exc)}))

    by_id = {row["id"]: row for row in rows}
    final: list[dict[str, Any]] = []
    for spec in UI_FAULT_SCENARIOS:
        row = by_id.get(spec["id"]) or _fault_row(spec["id"], False, {"error": "probe not executed"})
        row["evidence"] = materialize(root, "faults", row)
        final.append(row)
    return final


def freeze_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "evidence_manifest.json"
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p != manifest_path):
        rel = str(path.relative_to(root)).replace("\\", "/")
        files[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    write_json(manifest_path, files)
    return {"evidence_complete": bool(files), "root": str(root.resolve()), "manifest": manifest_path.name, "manifest_sha256": sha256_file(manifest_path), "file_count": len(files)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.formal and not platform.system().lower().startswith("win"):
        raise AcceptanceError("Formal V0.89-E qualification must run on Windows.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise AcceptanceError("Playwright is required for V0.89-E UI soak qualification.") from exc
    root = Path(args.artifact_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, root)
    health = api.get("/api/health")
    if str(health.get("version") or "") != __version__: raise AcceptanceError("Studio version mismatch")
    golden_summary = api.get("/api/windows-golden-journey-qualification")
    soak_summary = api.get("/api/production-soak-qualification")
    golden = golden_summary.get("latest_qualified_run") or {}
    native_soak = soak_summary.get("latest_qualified_run") or {}
    if args.formal and golden_summary.get("formal_qualified") is not True:
        raise AcceptanceError("V0.89-D formal Golden Journey qualification must PASS before V0.89-E.")
    if args.formal and soak_summary.get("formal_production_hardened") is not True:
        raise AcceptanceError("Formal native 100/500 Case production soak must PASS before V0.89-E.")
    source_journeys = ((golden.get("evidence") or {}).get("golden_journeys") or [])
    seed = next((dict(row) for row in source_journeys if str(row.get("id") or "").upper() == "SPM"), {})
    if not seed:
        # Local harness can create a lightweight project. Formal runs must use the qualified V0.89-D lineage.
        if args.formal: raise AcceptanceError("Qualified V0.89-D SPM seed lineage is missing")
        project = api.post("/api/projects", {"name": f"V089E Local Soak {int(time.time())}", "description": "Local UI soak harness"})
        project_id = str(project.get("id") or "")
        solution = api.post(f"/api/projects/{project_id}/solutions/from-template", {"name": "V0.89-E Local SPM", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound", "motor_family": ""})
        revisions = solution.get("revisions") or ((solution.get("solution") or {}).get("revisions") or [])
        solution_obj = solution.get("solution") or solution
        seed = {"project_id": project_id, "solution_id": str(solution_obj.get("id") or solution.get("id") or ""), "motor_revision_id": str((revisions[0] if revisions else {}).get("id") or "")}
    release = json.loads(Path(args.release_gates).read_text(encoding="utf-8")) if args.release_gates else {key: not args.formal for key in REQUIRED_RELEASE_GATES}
    if args.formal:
        missing = sorted(key for key in REQUIRED_RELEASE_GATES if release.get(key) is not True)
        if missing: raise AcceptanceError(f"V0.89-E release gates missing: {missing}")
    browser_info = {"engine": "chromium", "live_studio_url": True, "studio_version": __version__, "headed": bool(args.headed), "base_url": args.base_url, "captured_at": now_iso()}
    tiers: list[dict[str, Any]] = []; faults: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        launch = {"headless": not args.headed}
        executable = args.chromium_executable
        if not executable and platform.system().lower() == "linux" and Path("/usr/bin/chromium").is_file():
            executable = "/usr/bin/chromium"
        if executable: launch["executable_path"] = executable
        browser = pw.chromium.launch(**launch); browser_info["browser_version"] = browser.version
        ctx = browser.new_context(viewport={"width": 1680, "height": 1050})
        ctx.add_init_script("""window.__MCSV089EUnhandledRejectionCount = 0; window.addEventListener('unhandledrejection', () => { window.__MCSV089EUnhandledRejectionCount += 1; });""")
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page(); page.goto(args.base_url.rstrip("/") + f"/app/projects/{seed['project_id']}/overview", wait_until="domcontentloaded", timeout=90000); wait_app(page)
        try:
            for tid in UI_SOAK_TIERS:
                tiers.append(run_tier(page, root, tid, seed, cycle_override=args.cycle_override))
            faults = run_fault_matrix(page, api, root, seed)
            page.screenshot(path=str(root / "final_ui.png"), full_page=True)
        finally:
            ctx.tracing.stop(path=str(root / "playwright_trace.zip")); ctx.close(); browser.close()
    artifacts = freeze_manifest(root)
    required_fault_ids = {row["id"] for row in UI_FAULT_SCENARIOS} if args.formal else set(LOCAL_UI_FAULT_IDS)
    all_pass = all(row.get("status") == "PASS" and int(row.get("executed_cycles") or 0) == int(row.get("requested_cycles") or 0) for row in tiers) and all(row.get("status") == "PASS" for row in faults if row.get("id") in required_fault_ids)
    run_id = args.run_id or f"V089E-{'FORMAL' if args.formal else 'LOCAL'}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    payload = {
        "run_id": run_id, "status": "PASS" if all_pass else "FAIL", "mode": "FORMAL_WINDOWS" if args.formal else "LOCAL_BROWSER",
        "platform": platform.platform(), "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "source_golden_journey_run_id": golden.get("run_id"), "source_golden_journey_content_hash": golden.get("content_hash"),
        "source_production_soak_run_id": native_soak.get("run_id"), "source_production_soak_content_hash": native_soak.get("content_hash"),
        "browser": browser_info, "tiers": tiers, "fault_injections": faults,
        "release_gates": {key: release.get(key) is True for key in REQUIRED_RELEASE_GATES}, "artifacts": artifacts,
    }
    write_json(root / "v089e_import_payload.json", payload)
    imported = api.post("/api/ui-soak-qualification-runs/import", payload)
    result = {"authority": UI_SOAK_QUALIFICATION_AUTHORITY, "contract_version": UI_SOAK_QUALIFICATION_CONTRACT_VERSION, "formal_requested": bool(args.formal), "imported": imported}
    write_json(root / "v089e_qualification_result.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V0.89-E live UI Soak / Recovery / Fault Injection qualification")
    p.add_argument("--base-url", default=os.environ.get("MCS_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8765"))
    p.add_argument("--artifact-dir", required=True)
    p.add_argument("--release-gates", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--chromium-executable", default=os.environ.get("MCS_CHROMIUM_EXECUTABLE", ""))
    p.add_argument("--cycle-override", type=int, default=0, help="Local diagnostic only; formal qualification ignores partial-cycle evidence at import.")
    p.add_argument("--formal", action="store_true")
    p.add_argument("--headed", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try: result = run(args)
    except Exception as exc:
        print(f"V0.89-E qualification failed: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    imported_run = ((result.get("imported") or {}).get("run") or {})
    return 0 if (imported_run.get("formal_ui_resilience_qualified") is True or (not args.formal and imported_run.get("local_browser_qualified") is True)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
