from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .windows_fullflow import Api, AcceptanceError, completed_case, poll_task
from ..version import __version__
from ..windows_golden_journey_qualification import (
    EXPECTED_MOTORCAD_VERSION,
    GOLDEN_JOURNEY_BOOLEAN_GATES,
    REQUIRED_GOLDEN_JOURNEYS,
    REQUIRED_RELEASE_GATES,
    WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
    WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def portable(root: Path, path: Path) -> dict[str, Any]:
    return {
        "packaged_path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def wait_selector(page, selector: str, *, state: str = "visible", timeout_ms: int = 60000):
    return page.locator(selector).wait_for(state=state, timeout=timeout_ms)


def wait_enabled(page, selector: str, *, timeout_ms: int = 180000) -> None:
    page.wait_for_function(
        "selector => { const el=document.querySelector(selector); return !!el && !el.disabled && el.offsetParent !== null; }",
        selector,
        timeout=timeout_ms,
    )


def engineering_context(page) -> dict[str, Any]:
    try:
        return dict(page.evaluate("() => window.MCSEngineeringContext?.get?.() || {}") or {})
    except Exception:
        return {}


def wait_context(page, key: str, *, timeout_ms: int = 90000) -> str:
    page.wait_for_function(
        "key => !!window.MCSEngineeringContext?.get?.()?.[key]",
        key,
        timeout=timeout_ms,
    )
    return str(engineering_context(page).get(key) or "")


def click(page, selector: str, *, timeout_ms: int = 60000) -> None:
    wait_selector(page, selector, timeout_ms=timeout_ms)
    page.locator(selector).click(timeout=timeout_ms)


def maybe_click(page, selector: str, *, timeout_ms: int = 8000) -> bool:
    try:
        loc = page.locator(selector)
        if loc.count() and loc.first.is_visible(timeout=timeout_ms):
            loc.first.click(timeout=timeout_ms)
            return True
    except Exception:
        return False
    return False


def select_if_available(page, selector: str, value: str, *, timeout_ms: int = 60000) -> None:
    wait_selector(page, selector, timeout_ms=timeout_ms)
    page.locator(selector).select_option(value=value, timeout=timeout_ms)


def snapshot(page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=True)


def _task_completed(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "").upper() in {"COMPLETED", "SUCCEEDED"}


def _result_bundle(api: Api, case_id: str) -> dict[str, Any]:
    payload = api.get(f"/api/cases/{urllib.parse.quote(case_id)}/result-bundle")
    if isinstance(payload, dict) and isinstance(payload.get("result_bundle"), dict):
        row = dict(payload["result_bundle"])
        row["_api_result_bundle_hash"] = payload.get("result_bundle_hash")
        return row
    return dict(payload or {})


def _lineage_consistent(ctx: dict[str, Any], expected: dict[str, str]) -> bool:
    aliases = {
        "project_id": "projectId",
        "solution_id": "solutionId",
        "motor_revision_id": "motorRevisionId",
        "analysis_definition_id": "analysisId",
        "analysis_revision_id": "analysisRevisionId",
        "task_id": "taskId",
        "case_id": "caseId",
        "result_bundle_id": "resultBundleId",
    }
    for source, target in aliases.items():
        value = expected.get(source)
        observed = ctx.get(target)
        if value and observed and str(value) != str(observed):
            return False
    return True


def run_one_journey(
    browser,
    api: Api,
    *,
    base_url: str,
    artifact_root: Path,
    journey_id: str,
    headed: bool,
    task_timeout_s: int,
) -> dict[str, Any]:
    spec = REQUIRED_GOLDEN_JOURNEYS[journey_id]
    journey_root = artifact_root / "journeys" / journey_id.lower()
    journey_root.mkdir(parents=True, exist_ok=True)
    trace_path = journey_root / "playwright_trace.zip"
    design_shot = journey_root / "01_design.png"
    precheck_shot = journey_root / "02_precheck.png"
    result_shot = journey_root / "03_result.png"
    summary_path = journey_root / "summary.json"

    browser_context = browser.new_context(viewport={"width": 1680, "height": 1050})
    browser_context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = browser_context.new_page()
    page_errors: list[str] = []
    console_errors: list[str] = []
    http_errors: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("response", lambda response: http_errors.append({"status": response.status, "url": response.url}) if response.status >= 500 else None)

    row: dict[str, Any] = {
        "id": journey_id,
        "starter_id": spec["starter_id"],
        "template_id": spec["template_id"],
        "family": spec["family"],
        "status": "FAIL",
    }
    for key in GOLDEN_JOURNEY_BOOLEAN_GATES:
        row[key] = False

    def mark(action: str, **extra: Any) -> None:
        timeline.append({"at": now_iso(), "action": action, **extra})

    def ctx() -> dict[str, Any]:
        return engineering_context(page)

    try:
        page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded", timeout=90000)
        wait_selector(page, ".app-header", timeout_ms=90000)
        row["live_studio_shell"] = True
        mark("studio_loaded", url=page.url)

        maybe_click(page, "#setupContinueProjects", timeout_ms=4000)
        wait_selector(page, "#projectCreateName", timeout_ms=90000)
        project_name = f"V089D-{journey_id}-{int(time.time())}"
        page.locator("#projectCreateName").fill(project_name)
        page.locator("#projectCreateDescription").fill(
            f"V0.89-D live Windows Native Golden Journey qualification for {journey_id}."
        )
        click(page, "#projectCreate")
        project_id = wait_context(page, "projectId", timeout_ms=90000)
        row["project_id"] = project_id
        row["project_created_via_ui"] = bool(project_id)
        mark("project_created", project_id=project_id)

        stage_design = 'button[data-engineer-stage="design"]'
        if page.locator(stage_design).count() and not page.locator(stage_design).first.is_disabled():
            page.locator(stage_design).first.click()
        wait_selector(page, "#workspaceNewDesign", timeout_ms=90000)
        click(page, "#workspaceNewDesign")
        starter_selector = f'[data-starter-use="{spec["starter_id"]}"]'
        wait_selector(page, starter_selector, timeout_ms=90000)
        click(page, starter_selector)
        row["starter_opened_via_ui"] = True
        wait_enabled(page, "#goldenStarterConfirmV087", timeout_ms=90000)
        click(page, "#goldenStarterConfirmV087")
        solution_id = wait_context(page, "solutionId", timeout_ms=120000)
        motor_revision_id = wait_context(page, "motorRevisionId", timeout_ms=120000)
        row.update({"solution_id": solution_id, "motor_revision_id": motor_revision_id})
        row["rev1_created_via_ui"] = bool(solution_id and motor_revision_id)
        mark("starter_rev1_created", solution_id=solution_id, motor_revision_id=motor_revision_id)
        snapshot(page, design_shot)

        wait_selector(page, "#workspaceToAnalysisCanonical", timeout_ms=90000)
        click(page, "#workspaceToAnalysisCanonical")
        wait_selector(page, "#analysisCreateV076", timeout_ms=90000)
        click(page, "#analysisCreateV076")
        template_selector = '[data-analysis-template="rated_emag"]'
        wait_selector(page, template_selector, timeout_ms=90000)
        if not page.locator(template_selector).is_disabled():
            click(page, template_selector)
        wait_enabled(page, "#analysisConfirmCreateV076", timeout_ms=180000)
        click(page, "#analysisConfirmCreateV076")
        analysis_id = wait_context(page, "analysisId", timeout_ms=120000)
        analysis_revision_id = wait_context(page, "analysisRevisionId", timeout_ms=120000)
        row.update({"analysis_definition_id": analysis_id, "analysis_revision_id": analysis_revision_id})
        row["analysis_created_via_ui"] = bool(analysis_id and analysis_revision_id)
        mark("analysis_created", analysis_id=analysis_id, analysis_revision_id=analysis_revision_id)

        check_step = '[data-analysis-step-v076="check"]'
        wait_selector(page, check_step, timeout_ms=90000)
        click(page, check_step)
        wait_enabled(page, "#analysisFullCheckV076", timeout_ms=180000)
        click(page, "#analysisFullCheckV076")
        wait_enabled(page, "#analysisSubmitV076", timeout_ms=300000)
        row["full_native_precheck_via_ui"] = True
        mark("native_precheck_passed")
        snapshot(page, precheck_shot)

        click(page, "#analysisSubmitV076")
        task_id = wait_context(page, "taskId", timeout_ms=120000)
        row["task_id"] = task_id
        row["task_submitted_via_ui"] = bool(task_id)
        mark("task_submitted", task_id=task_id)

        task, cases = poll_task(api, task_id, task_timeout_s)
        row["task_completed"] = _task_completed(task)
        if not row["task_completed"]:
            raise AcceptanceError(f"{journey_id} task did not complete: {task.get('status')}")
        case = completed_case(cases)
        case_id = str(case.get("id") or "")
        if not case_id:
            raise AcceptanceError(f"{journey_id} completed case has no id")
        row["case_id"] = case_id
        bundle = _result_bundle(api, case_id)
        result_bundle_id = str(bundle.get("id") or bundle.get("result_bundle_id") or case.get("result_bundle_id") or "")
        result_bundle_hash = str(bundle.get("content_hash") or bundle.get("result_bundle_hash") or bundle.get("_api_result_bundle_hash") or case.get("result_bundle_hash") or "")
        if not result_bundle_id:
            raise AcceptanceError(f"{journey_id} result bundle missing for {case_id}")
        if not result_bundle_hash:
            # A stable content identity is mandatory. Read aggregate metadata when the compact endpoint omits the hash.
            detail = api.get(f"/api/result-bundles/{urllib.parse.quote(result_bundle_id)}/engineering-interpretation")
            result_bundle_hash = str((detail or {}).get("result_bundle_hash") or (detail or {}).get("content_hash") or "")
        if not result_bundle_hash:
            raise AcceptanceError(f"{journey_id} result bundle hash missing for {result_bundle_id}")
        row.update({"result_bundle_id": result_bundle_id, "result_bundle_hash": result_bundle_hash})
        row["result_bundle_ready"] = True
        mark("result_bundle_ready", case_id=case_id, result_bundle_id=result_bundle_id)

        # Re-open from the real Decision stage after solver completion; this proves UI recovery from task execution.
        page.reload(wait_until="domcontentloaded", timeout=90000)
        wait_selector(page, ".app-header", timeout_ms=90000)
        stage_decide = 'button[data-engineer-stage="decide"]'
        page.wait_for_function(
            "s => { const el=document.querySelector(s); return !!el && !el.disabled; }",
            stage_decide,
            timeout=180000,
        )
        click(page, stage_decide)
        wait_selector(page, "#viewerTaskSelect", timeout_ms=120000)
        select_if_available(page, "#viewerTaskSelect", task_id, timeout_ms=120000)
        # task selector change loads cases asynchronously; explicitly select the completed case when available.
        page.wait_for_function(
            "([selector,value]) => [...(document.querySelector(selector)?.options || [])].some(o => o.value === value)",
            ["#viewerCaseSelect", case_id],
            timeout=120000,
        )
        select_if_available(page, "#viewerCaseSelect", case_id, timeout_ms=120000)
        click(page, "#loadCaseViewer")
        wait_selector(page, "#viewerContent", timeout_ms=180000)
        page.wait_for_function(
            "() => { const el=document.querySelector('#viewerContent'); return !!el && !el.classList.contains('hidden'); }",
            timeout=180000,
        )
        row["result_opened_via_ui"] = True
        mark("result_opened_via_ui")
        snapshot(page, result_shot)

        final_ctx = ctx()
        expected = {
            "project_id": project_id,
            "solution_id": solution_id,
            "motor_revision_id": motor_revision_id,
            "analysis_definition_id": analysis_id,
            "analysis_revision_id": analysis_revision_id,
            "task_id": task_id,
            "case_id": case_id,
            "result_bundle_id": result_bundle_id,
        }
        row["lineage_consistent"] = _lineage_consistent(final_ctx, expected)
        row["final_engineering_context"] = final_ctx
        row["no_page_errors"] = not page_errors
        row["no_console_errors"] = not console_errors
        row["http_5xx"] = http_errors
        row["page_errors"] = page_errors
        row["console_errors"] = console_errors
        row["completed_at"] = now_iso()
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["page_errors"] = page_errors
        row["console_errors"] = console_errors
        row["http_5xx"] = http_errors
        mark("journey_failed", error=row["error"])
        try:
            snapshot(page, journey_root / "failure.png")
        except Exception:
            pass
    finally:
        try:
            browser_context.tracing.stop(path=str(trace_path))
        finally:
            browser_context.close()

    row["trace_evidence"] = trace_path.is_file() and trace_path.stat().st_size > 0
    row["screenshot_evidence"] = all(path.is_file() and path.stat().st_size > 0 for path in (design_shot, precheck_shot, result_shot))
    row["status"] = "PASS" if all(row.get(key) is True for key in GOLDEN_JOURNEY_BOOLEAN_GATES) else "FAIL"
    row["timeline"] = timeline
    write_json(summary_path, row)
    row["evidence"] = {
        "summary": portable(artifact_root, summary_path),
        "design_screenshot": portable(artifact_root, design_shot) if design_shot.is_file() else {},
        "precheck_screenshot": portable(artifact_root, precheck_shot) if precheck_shot.is_file() else {},
        "result_screenshot": portable(artifact_root, result_shot) if result_shot.is_file() else {},
        "playwright_trace": portable(artifact_root, trace_path) if trace_path.is_file() else {},
    }
    # Re-freeze summary with portable evidence identity for later inspection; the evidence manifest uses the final bytes.
    write_json(summary_path, {**row, "evidence": row["evidence"]})
    row["evidence"]["summary"] = portable(artifact_root, summary_path)
    return row


def freeze_manifest(root: Path, journeys: list[dict[str, Any]]) -> dict[str, Any]:
    # Refresh the summary hashes once all rows contain their final evidence references.
    for row in journeys:
        summary_meta = ((row.get("evidence") or {}).get("summary") or {})
        rel = str(summary_meta.get("packaged_path") or "")
        if rel:
            path = root / rel
            if path.is_file():
                row["evidence"]["summary"] = portable(root, path)
    files: dict[str, Any] = {}
    for row in journeys:
        for evidence in (row.get("evidence") or {}).values():
            rel = str((evidence or {}).get("packaged_path") or "")
            if not rel:
                continue
            path = root / rel
            if path.is_file():
                files[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    manifest_path = root / "evidence_manifest.json"
    write_json(manifest_path, files)
    return {
        "root": str(root.resolve()),
        "manifest": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "file_count": len(files),
        "evidence_complete": bool(files) and all(
            all(isinstance(meta, dict) and meta.get("packaged_path") for meta in (row.get("evidence") or {}).values())
            for row in journeys
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.formal and not platform.system().lower().startswith("win"):
        raise AcceptanceError("Formal V0.89-D qualification must run on Windows.")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - production dependency boundary
        raise AcceptanceError("Playwright is required for V0.89-D live UI qualification.") from exc

    artifact_root = Path(args.artifact_dir).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, artifact_root)
    native_summary = api.get("/api/windows-production-qualification")
    predecessor = native_summary.get("latest_qualified_run") or {}
    if args.formal and not native_summary.get("formal_qualified"):
        raise AcceptanceError("V0.88-F formal Windows Native qualification must PASS before V0.89-D.")
    predecessor_id = str(predecessor.get("run_id") or "")
    predecessor_hash = str(predecessor.get("content_hash") or "")
    if args.formal and (not predecessor_id or not predecessor_hash):
        raise AcceptanceError("Formal predecessor run identity/hash is missing.")

    release_gates = load_json(Path(args.release_gates), {}) if args.release_gates else {}
    if args.formal:
        missing = sorted(key for key in REQUIRED_RELEASE_GATES if release_gates.get(key) is not True)
        if missing:
            raise AcceptanceError(f"V0.89 release gates missing: {missing}")

    health = api.get("/api/health")
    if str(health.get("version") or "") != __version__:
        raise AcceptanceError(f"Studio version mismatch: {health.get('version')} != {__version__}")

    browser_info: dict[str, Any] = {
        "engine": "chromium",
        "live_studio_url": True,
        "base_url": args.base_url,
        "studio_version": __version__,
        "headed": bool(args.headed),
        "captured_at": now_iso(),
    }
    journeys: list[dict[str, Any]] = []
    with sync_playwright() as p:
        launch_args = {"headless": not args.headed}
        if args.chromium_executable:
            launch_args["executable_path"] = args.chromium_executable
        browser = p.chromium.launch(**launch_args)
        browser_info["browser_version"] = browser.version
        try:
            for sid in REQUIRED_GOLDEN_JOURNEYS:
                journeys.append(
                    run_one_journey(
                        browser,
                        api,
                        base_url=args.base_url,
                        artifact_root=artifact_root,
                        journey_id=sid,
                        headed=args.headed,
                        task_timeout_s=args.task_timeout,
                    )
                )
        finally:
            browser.close()

    artifacts = freeze_manifest(artifact_root, journeys)
    status = "PASS" if all(row.get("status") == "PASS" for row in journeys) else "FAIL"
    run_id = args.run_id or f"v089d-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    payload = {
        "run_id": run_id,
        "status": status,
        "platform": platform.platform(),
        "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "source_windows_qualification_run_id": predecessor_id,
        "source_windows_qualification_content_hash": predecessor_hash,
        "browser": browser_info,
        "golden_journeys": journeys,
        "release_gates": {key: release_gates.get(key) is True for key in REQUIRED_RELEASE_GATES},
        "artifacts": artifacts,
    }
    payload_path = artifact_root / "v089d_import_payload.json"
    write_json(payload_path, payload)
    imported = api.post("/api/windows-golden-journey-qualification-runs/import", payload)
    result = {
        "authority": WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
        "contract_version": WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION,
        "formal_requested": bool(args.formal),
        "payload_path": str(payload_path),
        "journey_passed": sum(1 for row in journeys if row.get("status") == "PASS"),
        "journey_required": len(REQUIRED_GOLDEN_JOURNEYS),
        "imported": imported,
    }
    write_json(artifact_root / "v089d_qualification_result.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V0.89-D live Windows Native Golden Journey qualification")
    parser.add_argument("--base-url", default=os.environ.get("MCS_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--release-gates", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--task-timeout", type=int, default=5400)
    parser.add_argument("--chromium-executable", default=os.environ.get("MCS_CHROMIUM_EXECUTABLE", ""))
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--headed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:
        print(f"V0.89-D qualification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    imported_run = ((result.get("imported") or {}).get("run") or {})
    return 0 if imported_run.get("formal_workstation_qualified") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())
