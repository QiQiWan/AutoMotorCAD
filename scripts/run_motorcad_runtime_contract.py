from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.runtime.runtime_contract import RuntimeContractRegistry
from motorcad_studio.settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def motorcad_process_snapshot() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "create_time"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            exe = str(proc.info.get("exe") or "").lower()
            if "motorcad" not in name and "motor-cad" not in name and "motorcad" not in exe and "motor-cad" not in exe:
                continue
            memory = proc.info.get("memory_info")
            rows.append({
                "pid": int(proc.info["pid"]),
                "name": proc.info.get("name"),
                "exe": proc.info.get("exe"),
                "rss_mb": round((memory.rss if memory else 0) / 1024 / 1024, 2),
                "create_time": proc.info.get("create_time"),
            })
        except (psutil.Error, OSError, ValueError):
            continue
    return rows


def show_context(mc: Any, context: str) -> None:
    if context == "EMag":
        mc.show_magnetic_context()
    elif context == "Therm":
        mc.show_thermal_context()
    elif context == "Mechanical":
        mc.show_mechanical_context()
    elif context == "Lab":
        if hasattr(mc, "set_motorlab_context"):
            mc.set_motorlab_context()
        else:
            mc.display_screen("Lab")


def contexts_for_analysis(analysis: str) -> list[str]:
    return {
        "emag": ["EMag"],
        "thermal_steady": ["Therm"],
        "thermal_transient": ["Therm"],
        "emag_thermal": ["EMag", "Therm"],
        "emag_thermal_coupled": ["EMag", "Therm"],
        "mechanical": ["Mechanical"],
        "lab_magnetic": ["Lab"],
        "lab_operating_point": ["Lab"],
    }[analysis]


def solve(mc: Any, analysis: str) -> None:
    if analysis == "emag":
        mc.show_magnetic_context(); mc.do_magnetic_calculation()
    elif analysis == "thermal_steady":
        mc.show_thermal_context(); mc.do_steady_state_analysis()
    elif analysis == "thermal_transient":
        mc.show_thermal_context(); mc.do_transient_analysis()
    elif analysis == "emag_thermal":
        mc.show_magnetic_context(); mc.do_magnetic_calculation()
        mc.show_thermal_context(); mc.do_steady_state_analysis()
    elif analysis == "emag_thermal_coupled":
        mc.show_magnetic_context(); mc.do_magnetic_thermal_calculation()
    elif analysis == "mechanical":
        mc.show_mechanical_context(); mc.do_mechanical_calculation()
    elif analysis == "lab_magnetic":
        if hasattr(mc, "set_motorlab_context"): mc.set_motorlab_context()
        mc.calculate_magnetic_lab()
    elif analysis == "lab_operating_point":
        if hasattr(mc, "set_motorlab_context"): mc.set_motorlab_context()
        mc.calculate_operating_point_lab()


def post_report(url: str, report: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(report, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url.rstrip("/") + "/api/runtime/contract/formal",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=30) as response:  # noqa: S310 - explicit local operator URL
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Windows Motor-CAD持久实例/许可证/RPC运行时契约测试。默认只做生命周期与许可证检查；--solve才执行真实求解。"
    )
    parser.add_argument("--iterations", type=int, default=20, help="复用循环次数；正式耐久建议至少100")
    parser.add_argument("--analysis", choices=["emag", "thermal_steady", "thermal_transient", "emag_thermal", "emag_thermal_coupled", "mechanical", "lab_magnetic", "lab_operating_point"], default="emag")
    parser.add_argument("--template", default="i5", help="每轮重新加载的Motor-CAD注册模板；空字符串表示不加载")
    parser.add_argument("--exe", default=None, help="Motor-CAD.exe；默认使用Studio已绑定路径")
    parser.add_argument("--solve", action="store_true", help="每轮执行真实求解。耗时且会实际占用对应许可证。")
    parser.add_argument("--confirm-license-use", action="store_true", help="确认允许get_licence()实际checkout许可证；未提供则拒绝运行")
    parser.add_argument("--output", default=None, help="报告JSON输出路径")
    parser.add_argument("--studio-url", default=None, help="可选：运行结束后POST到正在运行的Studio，例如 http://127.0.0.1:8765")
    parser.add_argument("--commit-local", action="store_true", help="Studio停止时可直接写入本地runtime_contract.json；运行中的Studio优先使用--studio-url")
    args = parser.parse_args()

    if platform.system() != "Windows":
        print(json.dumps({"passed": False, "reason": "windows_required", "platform": platform.platform()}, ensure_ascii=False, indent=2))
        return 2
    if not args.confirm_license_use:
        print("拒绝运行：get_licence()会实际checkout对应Motor-CAD许可证。请确认后增加 --confirm-license-use。")
        return 2
    iterations = max(1, int(args.iterations))
    manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    effective_exe = args.exe or manager.effective_exe()
    if not effective_exe or not Path(effective_exe).is_file():
        print(f"Motor-CAD.exe不可用: {effective_exe}")
        return 2

    try:
        from ansys.motorcad.core.rpc_client_core import set_motorcad_exe
        import ansys.motorcad.core as pymotorcad
    except Exception as exc:
        print(f"PyMotorCAD不可用: {type(exc).__name__}: {exc}")
        return 2

    set_motorcad_exe(str(Path(effective_exe).resolve()))
    registry = RuntimeContractRegistry(
        settings.runtime_dir / "runtime_contract.json",
        target_version=settings.motorcad_version,
        configured_exe=str(Path(effective_exe).resolve()),
        stale_hours=settings.runtime_contract_stale_hours,
    )
    environment_signature = registry.snapshot()["status_summary"]["environment_signature"]
    campaign_id = f"MCRC-{uuid.uuid4().hex[:12].upper()}"
    cycles: list[dict[str, Any]] = []
    started = time.monotonic()

    for index in range(iterations):
        cycle_started = time.monotonic()
        mc = None
        row: dict[str, Any] = {"index": index + 1, "started_at": utc_now(), "success": False}
        try:
            mc = pymotorcad.MotorCAD(
                reuse_parallel_instances=True,
                keep_instance_open=True,
                use_blackbox_licence=settings.use_blackbox_licence,
            )
            row["connected"] = True
            try:
                mc.set_variable("MessageDisplayState", 2)
            except Exception as exc:
                row["message_display_warning"] = f"{type(exc).__name__}: {exc}"
            try:
                mc.display_screen("Scripting")
            except Exception:
                pass
            try:
                mc.clear_message_log()
            except Exception:
                pass
            if args.template:
                mc.load_template(args.template)
                row["template_loaded"] = args.template
            licences: dict[str, Any] = {}
            for context in contexts_for_analysis(args.analysis):
                show_context(mc, context)
                value = mc.get_licence()
                licences[context] = {"checked": True, "return": value}
            row["licences"] = licences
            if args.solve:
                solve(mc, args.analysis)
                row["solve_completed"] = True
            try:
                row["messages_tail"] = list(mc.get_messages(10) or [])[-10:]
            except Exception:
                row["messages_tail"] = []
            row["success"] = True
        except BaseException as exc:
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)
            row["traceback"] = traceback.format_exc(limit=20)
        finally:
            if mc is not None:
                try:
                    # Keep the free instance available between cycles; close the final
                    # one explicitly so a contract campaign does not leave an owned
                    # Motor-CAD process behind.
                    if index == iterations - 1:
                        mc.quit()
                        row["release"] = "quit"
                    else:
                        mc.set_free()
                        row["release"] = "set_free"
                except Exception as exc:
                    row["release_error"] = f"{type(exc).__name__}: {exc}"
                    row["success"] = False
            row["elapsed_ms"] = round((time.monotonic() - cycle_started) * 1000.0, 2)
            processes = motorcad_process_snapshot()
            row["motorcad_processes"] = processes
            row["total_motorcad_rss_mb"] = round(sum(float(item.get("rss_mb") or 0.0) for item in processes), 2)
            cycles.append(row)
            print(f"[{index + 1}/{iterations}] {'PASS' if row['success'] else 'FAIL'} {row['elapsed_ms']} ms")
            if not row["success"]:
                break

    successes = sum(1 for row in cycles if row.get("success"))
    report = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "kind": "windows_motorcad_runtime_contract",
        "passed": successes == iterations,
        "started_at": cycles[0]["started_at"] if cycles else utc_now(),
        "finished_at": utc_now(),
        "elapsed_s": round(time.monotonic() - started, 3),
        "environment_signature": environment_signature,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "target_motorcad_version": settings.motorcad_version,
        "motorcad_exe": str(Path(effective_exe).resolve()),
        "pymotorcad_version": getattr(pymotorcad, "__version__", None),
        "analysis": args.analysis,
        "template": args.template or None,
        "solve": bool(args.solve),
        "iterations_requested": iterations,
        "iterations_completed": len(cycles),
        "successes": successes,
        "max_motorcad_rss_mb": max((float(row.get("total_motorcad_rss_mb") or 0.0) for row in cycles), default=0.0),
        "cycles": cycles,
        "authority_note": "该报告验证当前Windows工作站上的PyMotorCAD实例复用、set_free/quit、许可证checkout与可选求解链路；它不代表Ansys官方认证。",
    }
    output = Path(args.output) if args.output else settings.runtime_dir / f"runtime_contract_{campaign_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"报告: {output}")

    if args.studio_url:
        try:
            post_report(args.studio_url, report)
            print("已通过Studio API导入正式Runtime Contract报告。")
        except Exception as exc:
            print(f"报告导入Studio失败: {type(exc).__name__}: {exc}")
            report["studio_import_error"] = f"{type(exc).__name__}: {exc}"
    elif args.commit_local:
        registry.set_formal_contract(report)
        print("已直接写入本地runtime_contract.json。请仅在Studio未运行时使用该方式。")

    return 0 if report["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
