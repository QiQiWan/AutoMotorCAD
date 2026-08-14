from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.main import app
from motorcad_studio.models import SolverResult
from motorcad_studio.runtime import solver_process
from motorcad_studio.runtime.solver_process import SolverProcessRunner

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_project_manager_can_edit_basic_information_and_list_counts():
    created = client.post(
        "/api/projects",
        json={"name": "V018 project", "description": "initial"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    updated = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "V018 renamed", "description": "managed from project page"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "V018 renamed"
    assert updated.json()["description"] == "managed from project page"

    rows = client.get("/api/projects").json()
    row = next(item for item in rows if item["id"] == project_id)
    assert row["counts"] == {"designs": 0, "scenarios": 0, "experiments": 0, "tasks": 0}


def test_v018_frontend_starts_with_runtime_setup_and_has_dedicated_project_manager():
    html = client.get("/").text
    app_js = client.get("/static/app.js").text
    workflow_js = client.get("/static/workflow.js").text

    assert '<section id="setup" class="tab active">' in html
    assert '<section id="projects" class="tab">' in html
    assert 'id="projectManagerList"' in html
    assert 'id="projectCreate"' in html
    assert 'id="projectEditorDelete"' in html
    assert 'id="activeProjectSelect"' not in html
    assert 'id="activeProjectBadge"' in html
    assert 'data-project-tab' in html
    assert "updateProjectNavState" in app_js
    assert "projectScoped.has(id)&&!state.activeProjectId" in app_js
    assert "motorcad:'setup'" in workflow_js
    assert "project:'projects'" in workflow_js


def test_client_contract_advertises_v018_workflow_features():
    payload = client.get("/api/client-contract").json()
    assert payload["features"]["startup_runtime_setup"] is True
    assert payload["features"]["project_manager"] is True
    assert payload["features"]["project_edit"] is True


def test_manual_motorcad_binding_overrides_environment_path(tmp_path: Path):
    env_exe = tmp_path / "Motor-CAD-2025R2.exe"
    manual_exe = tmp_path / "Motor-CAD-2026R1.exe"
    env_exe.write_bytes(b"env")
    manual_exe.write_bytes(b"manual")

    manager = MotorCADInstallationManager(tmp_path / "runtime", configured_exe=str(env_exe))
    assert Path(manager.selected().exe_path) == env_exe.resolve()

    manager.select(f'  "{manual_exe}"  ')
    selected = manager.selected()
    assert selected is not None
    assert Path(selected.exe_path) == manual_exe.resolve()
    assert selected.source == "runtime_selection"

    manager.clear_selection()
    assert Path(manager.selected().exe_path) == env_exe.resolve()


def test_native_browser_uses_topmost_owner_and_persists_selection(tmp_path: Path, monkeypatch):
    exe = tmp_path / "Motor-CAD.exe"
    exe.write_bytes(b"exe")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout=f"MCS_PATH={exe}\n", stderr="", returncode=0)

    monkeypatch.setattr("motorcad_studio.installation.platform.system", lambda: "Windows")
    monkeypatch.setattr("motorcad_studio.installation.shutil.which", lambda _: "powershell.exe")
    monkeypatch.setattr("motorcad_studio.installation.subprocess.run", fake_run)

    manager = MotorCADInstallationManager(tmp_path / "runtime")
    result = manager.browse_native(timeout_s=30)
    assert result["selected"] is True
    assert Path(result["installation"]["exe_path"]) == exe.resolve()
    command = captured["command"]
    assert isinstance(command, list)
    script = command[-1]
    assert "$owner.TopMost=$true" in script
    assert "$d.ShowDialog($owner)" in script
    assert "MCS_PATH=" in script


def test_solver_runner_does_not_poll_pipe_again_after_final_frame(monkeypatch):
    final = {"type": "final", "ok": True, "result": SolverResult(scalars={"Torque": 42.0}).model_dump(mode="json")}

    class ParentConn:
        def __init__(self):
            self.poll_calls = 0
            self.closed = False

        def poll(self, _timeout=0):
            self.poll_calls += 1
            if self.poll_calls == 1:
                return True
            raise BrokenPipeError(109, "pipe ended")

        def recv(self):
            return final

        def close(self):
            self.closed = True

    class ChildConn:
        def close(self):
            pass

    class Process:
        pid = 12345
        exitcode = 0

        def start(self):
            pass

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    parent = ParentConn()

    class Context:
        def Pipe(self, duplex=False):
            assert duplex is False
            return parent, ChildConn()

        def Process(self, **kwargs):
            return Process()

    monkeypatch.setattr(solver_process.mp, "get_context", lambda _: Context())

    result = SolverProcessRunner(timeout_s=10).run(
        {"unused": True},
        progress=lambda *_: None,
        cancel_check=lambda: False,
    )
    assert result.scalars["Torque"] == 42.0
    # This is the Windows WinError 109 regression: once the final frame is read,
    # another PeekNamedPipe/poll must never be attempted.
    assert parent.poll_calls == 1
    assert parent.closed is True


def test_favicon_request_no_longer_generates_404_noise():
    response = client.get("/favicon.ico")
    assert response.status_code == 204
