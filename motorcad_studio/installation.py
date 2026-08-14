from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_VERSION_PATTERNS = [
    re.compile(r"(?P<year>20\d{2})[._ -]?[Rr]?(?P<release>[12])"),
    re.compile(r"(?P<year>20\d{2})[._ -](?P<release>[12])"),
    re.compile(r"(?P<year>20\d{2})"),
]


@dataclass(frozen=True)
class MotorCADInstallation:
    installation_id: str
    exe_path: str
    version: str | None
    source: str
    exists: bool
    selected: bool = False


class MotorCADInstallationManager:
    """Discover and select a Motor-CAD executable without requiring GUI interaction.

    PyMotorCAD's supported `set_motorcad_exe()` utility is used at launch time. The
    selected executable is persisted under the Studio runtime directory so all
    workers launch the same Motor-CAD version.
    """

    def __init__(self, runtime_dir: Path, configured_exe: str | None = None):
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.selection_path = self.runtime_dir / "motorcad_installation.json"
        self.configured_exe = configured_exe or os.getenv("MOTORCAD_STUDIO_MOTORCAD_EXE") or os.getenv("MOTORCAD_EXE")

    @staticmethod
    def _version_from_path(path: Path) -> str | None:
        text = str(path)
        for pattern in _VERSION_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            year = match.groupdict().get("year")
            release = match.groupdict().get("release")
            if year and release:
                return f"{year}R{release}"
            if year:
                return year
        return None

    @staticmethod
    def _id_for(path: Path) -> str:
        return hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]

    def _candidate(self, path: Path, source: str) -> MotorCADInstallation:
        resolved = path.expanduser().resolve()
        return MotorCADInstallation(
            installation_id=self._id_for(resolved),
            exe_path=str(resolved),
            version=self._version_from_path(resolved),
            source=source,
            exists=resolved.is_file(),
            selected=False,
        )

    def _registry_candidates(self) -> list[MotorCADInstallation]:
        if platform.system() != "Windows":
            return []
        try:
            import winreg  # type: ignore
        except Exception:
            return []
        results: list[MotorCADInstallation] = []
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, base in keys:
            try:
                with winreg.OpenKey(hive, base) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            name = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, name) as sub:
                                display, _ = winreg.QueryValueEx(sub, "DisplayName")
                                if "motor-cad" not in str(display).lower() and "motorcad" not in str(display).lower():
                                    continue
                                location = ""
                                try:
                                    location, _ = winreg.QueryValueEx(sub, "InstallLocation")
                                except OSError:
                                    pass
                                if location:
                                    root_path = Path(str(location))
                                    for exe_name in ("Motor-CAD.exe", "MotorCAD.exe", "Motor-CAD_64.exe"):
                                        candidate = root_path / exe_name
                                        if candidate.is_file():
                                            results.append(self._candidate(candidate, "windows_registry"))
                        except (OSError, ValueError):
                            continue
            except OSError:
                continue
        return results

    @staticmethod
    def _standard_roots() -> list[Path]:
        values = [
            os.getenv("ANSYS_MOTORCAD_ROOT"),
            os.getenv("MOTORCAD_ROOT"),
            r"C:\ANSYS_Motor-CAD",
            r"C:\Program Files\ANSYS Inc",
            r"C:\Program Files\ANSYS Motor-CAD",
        ]
        return [Path(value) for value in values if value]

    def _filesystem_candidates(self) -> list[MotorCADInstallation]:
        if platform.system() != "Windows":
            return []
        results: list[MotorCADInstallation] = []
        exe_patterns = ("Motor-CAD*.exe", "MotorCAD*.exe")
        for root in self._standard_roots():
            if not root.exists() or not root.is_dir():
                continue
            # Motor-CAD's default root is small enough for a recursive search. For
            # Program Files, constrain traversal to paths containing Motor/Motor-CAD.
            try:
                for pattern in exe_patterns:
                    for path in root.rglob(pattern):
                        text = str(path).lower()
                        if "motor" not in text:
                            continue
                        results.append(self._candidate(path, "filesystem"))
            except (OSError, PermissionError):
                continue
        return results

    def selected(self) -> MotorCADInstallation | None:
        # A manual selection made in Studio must take precedence over an inherited
        # environment variable.  Otherwise the UI can report a successful bind while
        # every worker continues to use MOTORCAD_EXE from the parent shell.
        if self.selection_path.exists():
            try:
                payload = json.loads(self.selection_path.read_text(encoding="utf-8"))
                path = Path(payload["exe_path"])
                item = self._candidate(path, payload.get("source", "runtime_selection"))
                return MotorCADInstallation(**{**asdict(item), "selected": True})
            except Exception:
                # A corrupt runtime selection should not prevent fallback to the
                # configured environment path.
                pass
        explicit = self.configured_exe
        if explicit:
            item = self._candidate(Path(explicit), "environment")
            return MotorCADInstallation(**{**asdict(item), "selected": True})
        return None

    def effective_exe(self) -> str | None:
        """Return the executable that automation should actually use right now."""
        selected = self.selected()
        if selected and selected.exists:
            return selected.exe_path
        if self.configured_exe:
            candidate = Path(self.configured_exe).expanduser()
            if candidate.is_file():
                return str(candidate.resolve())
        return None

    def scan(self) -> list[dict[str, Any]]:
        candidates: list[MotorCADInstallation] = []
        if self.configured_exe:
            candidates.append(self._candidate(Path(self.configured_exe), "environment"))
        candidates.extend(self._registry_candidates())
        candidates.extend(self._filesystem_candidates())
        selected = self.selected()
        if selected and all(Path(item.exe_path) != Path(selected.exe_path) for item in candidates):
            candidates.append(selected)

        unique: dict[str, MotorCADInstallation] = {}
        for item in candidates:
            unique[str(Path(item.exe_path)).lower()] = item
        selected_path = str(Path(selected.exe_path)).lower() if selected else None
        rows = []
        for item in unique.values():
            row = asdict(item)
            row["selected"] = selected_path == str(Path(item.exe_path)).lower()
            rows.append(row)
        rows.sort(key=lambda row: (not row["selected"], row.get("version") or "", row["exe_path"]), reverse=False)
        return rows

    def select(self, exe_path: str) -> dict[str, Any]:
        normalized = str(exe_path or "").strip().strip('"')
        if not normalized:
            raise FileNotFoundError("Motor-CAD executable path is empty")
        item = self._candidate(Path(normalized), "runtime_selection")
        if not item.exists:
            raise FileNotFoundError(f"Motor-CAD executable not found: {normalized}")
        if Path(item.exe_path).suffix.lower() != ".exe":
            raise FileNotFoundError(f"Selected file is not an executable: {normalized}")
        payload = asdict(item)
        payload["selected"] = True
        self.selection_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def browse_native(self, timeout_s: float = 180.0) -> dict[str, Any]:
        """Open a host-side Windows file picker for Motor-CAD.exe.

        Browser JavaScript cannot read an arbitrary local executable path. Because
        Studio is normally hosted on the same Windows engineering workstation, this
        helper opens a native Windows file dialog in the server user session. A plain
        text path entry remains available when the server is non-interactive.
        """
        if platform.system() != "Windows":
            return {"selected": False, "supported": False, "reason": "windows_only"}
        powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh.exe") or shutil.which("pwsh")
        if not powershell:
            return {"selected": False, "supported": False, "reason": "powershell_unavailable"}
        initial = ""
        current = self.selected()
        if current:
            try:
                parent = Path(current.exe_path).parent
                if parent.exists():
                    initial = str(parent)
            except Exception:
                initial = ""
        initial_ps = initial.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$owner=New-Object System.Windows.Forms.Form; "
            "$owner.Text='MotorCAD Studio'; $owner.TopMost=$true; $owner.ShowInTaskbar=$false; "
            "$owner.StartPosition='CenterScreen'; $owner.Size=New-Object System.Drawing.Size(2,2); $owner.Opacity=0.01; "
            "$owner.Show(); $owner.Activate(); [System.Windows.Forms.Application]::DoEvents(); "
            "$d=New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title='MotorCAD Studio - Select Motor-CAD executable'; "
            "$d.Filter='Motor-CAD executable (*.exe)|*.exe|All files (*.*)|*.*'; "
            f"$d.InitialDirectory='{initial_ps}'; "
            "$d.CheckFileExists=$true; $d.Multiselect=$false; $d.RestoreDirectory=$true; "
            "$r=$d.ShowDialog($owner); "
            "if($r -eq [System.Windows.Forms.DialogResult]::OK){[Console]::Out.Write('MCS_PATH='+$d.FileName)}; "
            "$owner.Close(); $owner.Dispose();"
        )
        try:
            proc = subprocess.run(
                [powershell, "-NoProfile", "-STA", "-Command", script],
                capture_output=True, text=True, timeout=max(10.0, float(timeout_s)), check=False,
            )
        except subprocess.TimeoutExpired:
            return {"selected": False, "supported": True, "reason": "dialog_timeout"}
        except Exception as exc:
            return {"selected": False, "supported": True, "reason": "dialog_error", "error": f"{type(exc).__name__}: {exc}"}
        stdout = (proc.stdout or "").strip()
        chosen = ""
        for line in stdout.splitlines():
            if line.startswith("MCS_PATH="):
                chosen = line[len("MCS_PATH="):].strip()
                break
        if not chosen:
            stderr = (proc.stderr or "").strip()[:2000]
            if proc.returncode != 0 or stderr:
                return {
                    "selected": False,
                    "supported": True,
                    "reason": "dialog_process_failed",
                    "backend": "powershell_winforms",
                    "returncode": proc.returncode,
                    "stderr": stderr,
                }
            return {
                "selected": False,
                "supported": True,
                "cancelled": True,
                "backend": "powershell_winforms",
                "returncode": proc.returncode,
            }
        try:
            selected = self.select(chosen)
        except Exception as exc:
            return {"selected": False, "supported": True, "reason": "invalid_selection", "error": str(exc), "exe_path": chosen, "backend": "powershell_winforms", "returncode": proc.returncode}
        return {"selected": True, "supported": True, "installation": selected, "backend": "powershell_winforms", "returncode": proc.returncode}

    def clear_selection(self) -> None:
        if self.selection_path.exists():
            self.selection_path.unlink()

    def auto_select(self, target_version: str | None = None) -> MotorCADInstallation | None:
        selected = self.selected()
        if selected and selected.exists:
            return selected
        rows = [row for row in self.scan() if row.get("exists")]
        if not rows:
            return None
        if target_version:
            exact = [row for row in rows if str(row.get("version") or "").lower() == target_version.lower()]
            if exact:
                self.select(exact[0]["exe_path"])
                return self.selected()
        # Prefer newest recognized version; otherwise the first detected executable.
        rows.sort(key=lambda row: (row.get("version") or "", row.get("exe_path") or ""), reverse=True)
        self.select(rows[0]["exe_path"])
        return self.selected()

    def configure_pymotorcad(self, target_version: str | None = None, auto_select: bool = True) -> dict[str, Any]:
        selected = self.selected()
        if not selected and auto_select:
            selected = self.auto_select(target_version)
        if not selected:
            return {"configured": False, "reason": "no_selected_executable"}
        if not selected.exists:
            return {"configured": False, "reason": "selected_executable_missing", "exe_path": selected.exe_path}
        from ansys.motorcad.core.rpc_client_core import set_motorcad_exe

        set_motorcad_exe(selected.exe_path)
        return {
            "configured": True,
            "exe_path": selected.exe_path,
            "version": selected.version,
            "installation_id": selected.installation_id,
            "auto_selected": auto_select,
        }
