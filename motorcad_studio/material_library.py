from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from .db import Database

_INDEXED_KEY = re.compile(r"^(?P<base>.*?)\s*\[(?P<index>\d+)\]\s*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scalar(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        return text


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _material_section_hash(material: dict[str, Any]) -> str:
    """Stable hash of one material section, independent from the database file hash."""
    canonical = {
        "name": str(material.get("name") or ""),
        "kind": str(material.get("kind") or ""),
        "material_type": str(material.get("material_type") or ""),
        "properties": material.get("properties") or {},
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _material_type(properties: dict[str, Any]) -> str:
    fixed = str(properties.get("Type") or "")
    if "fluid" in fixed.lower():
        return "Fluid"
    declared = str(properties.get("Solid Type") or "").strip()
    if declared:
        normalized = declared.lower()
        if normalized == "magnet":
            return "Magnet"
        if normalized == "steel":
            return "Steel"
        if normalized in {"general", "solid"}:
            return "General"
        return declared
    keys = {key.lower() for key in properties}
    if any(key.startswith("magnet") for key in keys):
        return "Magnet"
    if any(key.startswith("bvalue") or key.startswith("hvalue") or "lossdensity" in key for key in keys):
        return "Steel"
    return "General"


def _kind(properties: dict[str, Any]) -> str:
    fixed = str(properties.get("Type") or "")
    return "fluid" if "fluid" in fixed.lower() else "solid"


def _curve(properties: dict[str, Any], x_key: str, y_key: str) -> list[dict[str, Any]]:
    xs: dict[int, Any] = {}
    ys: dict[int, Any] = {}
    for key, value in properties.items():
        match = _INDEXED_KEY.match(key)
        if not match:
            continue
        base = match.group("base").strip()
        index = int(match.group("index"))
        if base == x_key:
            xs[index] = value
        elif base == y_key:
            ys[index] = value
    return [{"index": index, "x": xs.get(index), "y": ys.get(index)} for index in sorted(set(xs) | set(ys))]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _magnet_reference_summary(properties: dict[str, Any]) -> dict[str, Any]:
    """Build transparent engineering reference curves from scalar magnet data.

    Many Motor-CAD Solids.mdb magnet records (including the bundled N30UH record)
    contain Br, intrinsic HcJ, relative permeability and temperature coefficients,
    but no sampled BValue_Magnet/HValue_Magnet arrays. In that case the UI should
    still visualize the data without pretending it came from measured curve points.
    The B-H reference line is therefore explicitly marked as derived and uses
    B(H,T) = Br(T) + mu0 * mur * H up to B=0 (HcB). HcJ remains a separate intrinsic
    coercivity temperature series and is never substituted for HcB.
    """
    br0 = _number(properties.get("MagnetBrValue"))
    mur = _number(properties.get("MagneturValue"))
    hcj0 = _number(properties.get("MagnetHcJValue"))
    tref = _number(properties.get("MagnetRefTemp"))
    alpha_br = _number(properties.get("MagnetTempCoefBr"))
    alpha_hcj = _number(properties.get("MagnetTempCoefHcJ"))
    tmin = _number(properties.get("ValidMagnetTemperature_Min"))
    tmax = _number(properties.get("ValidMagnetTemperature_Max"))
    if br0 is None or mur is None or mur <= 0:
        return {"bh_reference": [], "temperature_points": [], "source": None}
    tref = 20.0 if tref is None else tref
    alpha_br = 0.0 if alpha_br is None else alpha_br
    alpha_hcj = 0.0 if alpha_hcj is None else alpha_hcj
    lo = tmin if tmin is not None else tref
    hi = tmax if tmax is not None else tref
    if hi < lo:
        lo, hi = hi, lo
    if abs(hi - lo) < 1e-12:
        temperatures = [tref]
    else:
        temperatures = [lo + (hi - lo) * i / 4 for i in range(5)]
        if lo <= tref <= hi and all(abs(value - tref) > 1e-9 for value in temperatures):
            temperatures.append(tref)
            temperatures.sort()
    mu0 = 4.0 * math.pi * 1e-7
    temp_points: list[dict[str, Any]] = []
    ref_curve: list[dict[str, Any]] = []
    # Use the reference temperature for the detailed line; temperature trends are
    # exposed separately so the chart remains readable.
    br_ref = br0 * (1.0 + alpha_br / 100.0 * (tref - tref))
    hcb = br_ref / (mu0 * mur) if mu0 * mur else None
    if hcb and math.isfinite(hcb) and hcb > 0:
        for i in range(41):
            h = -hcb + hcb * i / 40.0
            b = br_ref + mu0 * mur * h
            ref_curve.append({"h": h, "b": b, "temperature": tref})
    hcj_magnitude0 = abs(hcj0) if hcj0 is not None else None
    for temp in temperatures:
        br = br0 * (1.0 + alpha_br / 100.0 * (temp - tref))
        # Motor-CAD databases may store HcJ with a negative second-quadrant sign.
        # The engineering temperature chart reports coercivity magnitude |HcJ|,
        # so a normal negative temperature coefficient remains visually decreasing.
        hcj = hcj_magnitude0 * (1.0 + alpha_hcj / 100.0 * (temp - tref)) if hcj_magnitude0 is not None else None
        temp_points.append({"temperature": temp, "br": br, "hcj": hcj})
    return {
        "bh_reference": ref_curve,
        "temperature_points": temp_points,
        "reference_temperature": tref,
        "source": "derived_from_scalar_magnet_properties",
        "equation": "B(H,Tref)=Br(Tref)+mu0*mur*H; HcB=Br/(mu0*mur)",
        "note": "Engineering reference derived from Br, mur and temperature coefficients; not raw measured B-H samples.",
        "hcj_display": "magnitude",
        "hcj_source_sign": -1 if hcj0 is not None and hcj0 < 0 else (1 if hcj0 is not None else None),
    }


def summarize_properties(properties: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "Thermal Conductivity", "Specific Heat", "Density", "ElectricalResistivity",
        "TempCoefElectricalResistivity", "PoissonsRatio", "YoungsCoefficient", "YieldStress",
        "MagnetBrValue", "MagnetHcJValue", "MagneturValue", "MagnetTempCoefBr",
        "MagnetTempCoefHcJ", "MagnetRefTemp", "ValidMagnetTemperature_Min",
        "ValidMagnetTemperature_Max", "LaminationThickness", "KcValue", "KhValue_Steinmetz",
        "KhValue_Bertotti", "KeddyValue_Steinmetz", "KexcValue", "alphaValue_Steinmetz",
        "alphaValue_Bertotti", "betavalue_Steinmetz",
    ]
    summary = {key: properties[key] for key in keys if key in properties}
    bh = _curve(properties, "HValue", "BValue")
    loss = []
    frequencies: dict[int, Any] = {}
    flux: dict[int, Any] = {}
    densities: dict[int, Any] = {}
    for key, value in properties.items():
        match = _INDEXED_KEY.match(key)
        if not match:
            continue
        base, index = match.group("base").strip(), int(match.group("index"))
        if base == "Frequency":
            frequencies[index] = value
        elif base == "FluxDensity":
            flux[index] = value
        elif base == "LossDensity":
            densities[index] = value
    for index in sorted(set(frequencies) | set(flux) | set(densities)):
        loss.append({"index": index, "frequency": frequencies.get(index), "flux_density": flux.get(index), "loss_density": densities.get(index)})
    magnet_bh: list[dict[str, Any]] = []
    magnet_t: dict[int, Any] = {}
    magnet_b: dict[int, Any] = {}
    magnet_h: dict[int, Any] = {}
    for key, value in properties.items():
        match = _INDEXED_KEY.match(key)
        if not match:
            continue
        base, index = match.group("base").strip(), int(match.group("index"))
        if base == "Temperature":
            magnet_t[index] = value
        elif base == "BValue_Magnet":
            magnet_b[index] = value
        elif base == "HValue_Magnet":
            magnet_h[index] = value
    for index in sorted(set(magnet_t) | set(magnet_b) | set(magnet_h)):
        magnet_bh.append({"index": index, "temperature": magnet_t.get(index), "b": magnet_b.get(index), "h": magnet_h.get(index)})

    temperature_curves: dict[str, list[dict[str, Any]]] = {}
    bases = set()
    for key in properties:
        match = _INDEXED_KEY.match(key)
        if match and match.group("base").strip().endswith(" Temp"):
            bases.add(match.group("base").strip()[:-5])
    for base in sorted(bases):
        points = _curve(properties, f"{base} Temp", f"{base} Value")
        if points:
            temperature_curves[base] = points
    magnet_reference = _magnet_reference_summary(properties)
    return {
        "core": summary, "bh_curve": bh, "magnet_bh_curve": magnet_bh,
        "magnet_reference_curve": magnet_reference.get("bh_reference") or [],
        "magnet_temperature_points": magnet_reference.get("temperature_points") or [],
        "magnet_reference_meta": {key: value for key, value in magnet_reference.items() if key not in {"bh_reference", "temperature_points"}},
        "loss_points": loss, "temperature_curves": temperature_curves,
    }


def parse_mdb_text(text: str) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    name: str | None = None
    properties: dict[str, Any] = {}
    raw_entries: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal name, properties, raw_entries
        if not name:
            return
        materials.append({
            "name": name,
            "kind": _kind(properties),
            "material_type": _material_type(properties),
            "properties": dict(properties),
            "raw_entries": list(raw_entries),
            "summary": summarize_properties(properties),
        })
        name, properties, raw_entries = None, {}, []

    for raw_line in text.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            name = line[1:-1].strip()
            continue
        if name is None or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        parsed = _scalar(value)
        properties[key] = parsed
        raw_entries.append({"key": key, "value": parsed})
    flush()
    return materials


def parse_mdb(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return parse_mdb_text(raw.decode(encoding))
        except UnicodeError:
            continue
    return parse_mdb_text(raw.decode("latin-1", errors="replace"))


def serialize_mdb(records: Iterable[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for record in records:
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        props = dict(record.get("properties") or {})
        if "Type" not in props:
            props["Type"] = "Fixed_Fluid" if str(record.get("kind")) == "fluid" else "Fixed_Solid"
        if str(record.get("kind")) != "fluid" and "Solid Type" not in props:
            material_type = str(record.get("material_type") or "General")
            if material_type in {"General", "Magnet", "Steel"}:
                props["Solid Type"] = material_type
        lines = [f"[{name}]"]
        preferred = ["Type", "Solid Type", "Thermal Conductivity", "Specific Heat", "Density", "Notes"]
        emitted: set[str] = set()
        for key in preferred:
            if key in props:
                lines.append(f"{key}={_text(props[key])}")
                emitted.add(key)
        for key, value in props.items():
            if key in emitted:
                continue
            lines.append(f"{key}={_text(value)}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + ("\n" if chunks else "")


class MaterialLibraryService:
    def __init__(self, db: Database, runtime_dir: Path, motorcad_version: str, motorcad_exe: str | None = None):
        self.db = db
        self.runtime_dir = Path(runtime_dir)
        self.motorcad_version = motorcad_version
        self.motorcad_exe = motorcad_exe
        self.managed_dir = self.runtime_dir / "material_library"
        self.managed_dir.mkdir(parents=True, exist_ok=True)
        self._last_discovery_diagnostics: dict[str, Any] = {}

    @staticmethod
    def _record_id(source_path: str, name: str) -> str:
        token = hashlib.sha256(f"{source_path}|{name}".encode("utf-8", errors="ignore")).hexdigest()[:20]
        return f"MAT-{token}"

    def discover_databases(self) -> list[dict[str, Any]]:
        """Discover Motor-CAD material databases without walking an entire drive.

        Motor-CAD stores the selected Solids/Fluids databases in Defaults.INI and
        may place those files under Roaming/Local AppData, ProgramData, Public
        Documents, or the installation tree.  Older Studio builds searched only
        Roaming AppData plus two paths adjacent to MotorCAD.exe, which misses common
        2026R1 workstation layouts.  The discovery below keeps the search bounded to
        known Motor-CAD roots while recording enough diagnostics for the UI/logs.
        """
        candidates: dict[str, dict[str, Any]] = {}
        diagnostics: dict[str, Any] = {"searched_roots": [], "defaults_files": [], "direct_candidates": []}

        def resolved_path(value: str | Path) -> Path:
            expanded = os.path.expandvars(os.path.expanduser(str(value).strip().strip('"')))
            path = Path(expanded)
            try:
                return path.resolve()
            except OSError:
                return path

        def remember_root(path: Path | None, source: str) -> Path | None:
            if path is None:
                return None
            root = resolved_path(path)
            key = str(root).casefold()
            if not any(str(row.get("path", "")).casefold() == key for row in diagnostics["searched_roots"]):
                diagnostics["searched_roots"].append({"path": str(root), "source": source, "exists": root.exists()})
            return root

        def add(path_value: str | Path | None, source: str) -> None:
            if not path_value:
                return
            path = resolved_path(path_value)
            if path.suffix.lower() != ".mdb" or not path.exists() or not path.is_file():
                return
            key = str(path).casefold()
            if key in candidates:
                return
            try:
                parsed = parse_mdb(path)
                if not parsed:
                    raise ValueError("未解析到标准 Motor-CAD INI 材料段；文件可能为空或格式不兼容。Granta 材料库为加密 .gdb，需先通过 Motor-CAD 导入到普通工作数据库")
                count = len(parsed)
                digest = _file_hash(path)
            except Exception as exc:
                candidates[key] = {"path": str(path), "source": source, "exists": True, "readable": False, "error": str(exc)}
                return
            name = path.name.lower()
            kind = "fluid" if "fluid" in name else "solid" if "solid" in name else "mixed"
            candidates[key] = {"path": str(path), "source": source, "exists": True, "readable": True, "kind": kind, "material_count": count, "file_hash": digest}

        def add_defaults(defaults_value: str | Path | None, source: str) -> None:
            if not defaults_value:
                return
            defaults = resolved_path(defaults_value)
            key = str(defaults).casefold()
            if any(str(row.get("path", "")).casefold() == key for row in diagnostics["defaults_files"]):
                return
            row = {"path": str(defaults), "source": source, "exists": defaults.exists() and defaults.is_file()}
            diagnostics["defaults_files"].append(row)
            if not row["exists"]:
                return
            try:
                raw = defaults.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError as exc:
                row["error"] = str(exc)
                return
            referenced = 0
            for line in raw.splitlines():
                if "=" not in line:
                    continue
                _, value = line.split("=", 1)
                value = os.path.expandvars(value.strip().strip('"'))
                if ".mdb" not in value.lower():
                    continue
                db_path = Path(value)
                if not db_path.is_absolute():
                    db_path = defaults.parent / db_path
                add(db_path, f"Defaults.INI:{defaults}")
                referenced += 1
            row["mdb_references"] = referenced

        def bounded_named_scan(root: Path | None, source: str, *, limit: int = 120) -> None:
            root = remember_root(root, source) if root else None
            if root is None or not root.exists() or not root.is_dir():
                return
            found = 0
            try:
                for name in ("Defaults.INI", "defaults.ini"):
                    for candidate in islice(root.rglob(name), limit):
                        add_defaults(candidate, source)
                        found += 1
                        if found >= limit:
                            return
                for name in ("Solids.mdb", "solids.mdb", "Fluids.mdb", "fluids.mdb"):
                    for candidate in islice(root.rglob(name), max(1, limit - found)):
                        add(candidate, source)
                        diagnostics["direct_candidates"].append({"path": str(candidate), "source": source})
                        found += 1
                        if found >= limit:
                            return
            except (OSError, PermissionError):
                return

        add(os.getenv("MOTORCAD_STUDIO_SOLIDS_DB"), "env:MOTORCAD_STUDIO_SOLIDS_DB")
        add(os.getenv("MOTORCAD_STUDIO_FLUIDS_DB"), "env:MOTORCAD_STUDIO_FLUIDS_DB")

        defaults_env = os.getenv("MOTORCAD_DEFAULTS_FILE")
        if defaults_env:
            p = resolved_path(defaults_env)
            add_defaults(p if p.suffix.lower() == ".ini" else p / "Defaults.INI", "env:MOTORCAD_DEFAULTS_FILE")

        # Known Motor-CAD user/application roots.  These are intentionally specific;
        # no search starts at a drive root or the full user profile.
        roots: list[tuple[Path, str]] = []
        for env_name in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA"):
            raw = os.getenv(env_name)
            if raw:
                base = Path(raw)
                roots.extend([
                    (base / "Ansys", f"{env_name.lower()}-ansys"),
                    (base / "Motor-CAD", f"{env_name.lower()}-motor-cad"),
                    (base / "MotorCAD", f"{env_name.lower()}-motorcad"),
                ])
        user = os.getenv("USERPROFILE")
        if user:
            docs = Path(user) / "Documents"
            roots.extend([(docs / "Ansys", "user-documents-ansys"), (docs / "Motor-CAD", "user-documents-motor-cad"), (docs / "MotorCAD", "user-documents-motorcad")])
        public = os.getenv("PUBLIC")
        if public:
            docs = Path(public) / "Documents"
            roots.extend([(docs / "Ansys", "public-documents-ansys"), (docs / "Motor-CAD", "public-documents-motor-cad"), (docs / "MotorCAD", "public-documents-motorcad")])

        if self.motorcad_exe:
            exe = resolved_path(self.motorcad_exe)
            install = exe.parent
            # Fast path for standard install layouts.
            for root in (install, install / "Motor-CAD Data", install / "Data", install / "Resources", install.parent / "Motor-CAD Data"):
                add_defaults(root / "Defaults.INI", "motorcad-install")
                add(root / "Solids.mdb", "motorcad-install")
                add(root / "Fluids.mdb", "motorcad-install")
            # Search only the Motor-CAD installation subtree, never all of ANSYS Inc.
            roots.insert(0, (install, "motorcad-install-scan"))

        seen_roots: set[str] = set()
        for root, source in roots:
            key = str(root).casefold()
            if key in seen_roots:
                continue
            seen_roots.add(key)
            bounded_named_scan(root, source)

        diagnostics["candidate_count"] = len(candidates)
        diagnostics["readable_count"] = sum(1 for row in candidates.values() if row.get("readable"))
        self._last_discovery_diagnostics = diagnostics
        return sorted(candidates.values(), key=lambda row: (0 if "Defaults.INI" in row.get("source", "") else 1, row.get("path", "")))

    def import_database(self, path_value: str, *, replace: bool = True, source: str = "manual") -> dict[str, Any]:
        path = Path(path_value).expanduser().resolve()
        if path.suffix.lower() != ".mdb":
            raise ValueError("材料数据库必须是 .mdb 文件")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        materials = parse_mdb(path)
        if not materials:
            raise ValueError("未解析到标准 Motor-CAD INI 材料段。Granta 材料库为加密 .gdb，需先通过 Motor-CAD/Granta 导入到普通 .mdb 工作数据库")
        digest = _file_hash(path)
        now = _now()
        source_path = str(path)
        rows: list[tuple[Any, ...]] = []
        for material in materials:
            record_id = self._record_id(source_path, material["name"])
            payload = self.db.dumps(material)
            rows.append((record_id, material["name"], material["kind"], material["material_type"], "motorcad_database", source_path, digest, self.motorcad_version, payload, now, now))
        with self.db.transaction() as conn:
            if replace:
                conn.execute("DELETE FROM material_library_records WHERE source_database_path=? AND source_kind='motorcad_database'", (source_path,))
            conn.executemany(
                """
                INSERT OR REPLACE INTO material_library_records(
                    id,name,kind,material_type,source_kind,source_database_path,source_database_hash,
                    motorcad_version,payload_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            conn.execute(
                """
                INSERT INTO material_databases(path,kind,file_hash,material_count,source,last_scanned_at,metadata_json)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,file_hash=excluded.file_hash,
                    material_count=excluded.material_count,source=excluded.source,last_scanned_at=excluded.last_scanned_at,
                    metadata_json=excluded.metadata_json
                """,
                (source_path, self._database_kind(materials), digest, len(materials), source, now, self.db.dumps({"motorcad_version": self.motorcad_version})),
            )
        return {"path": source_path, "file_hash": digest, "material_count": len(materials), "kind": self._database_kind(materials), "source": source}

    @staticmethod
    def _database_kind(materials: list[dict[str, Any]]) -> str:
        kinds = {row.get("kind") for row in materials}
        return next(iter(kinds)) if len(kinds) == 1 else "mixed"

    def scan_and_import(self) -> dict[str, Any]:
        candidates = self.discover_databases()
        imported = []
        errors = []
        for row in candidates:
            if not row.get("readable"):
                continue
            try:
                imported.append(self.import_database(row["path"], source=row.get("source") or "discovery"))
            except Exception as exc:
                errors.append({"path": row.get("path"), "error": str(exc)})
        return {"candidates": candidates, "imported": imported, "errors": errors, "ok": bool(imported) and not errors, "diagnostics": dict(self._last_discovery_diagnostics or {})}

    def status(self) -> dict[str, Any]:
        databases = self.db.query_all("SELECT * FROM material_databases ORDER BY last_scanned_at DESC")
        total = self.db.query_one("SELECT COUNT(*) AS n FROM material_library_records") or {"n": 0}
        custom = self.db.query_one("SELECT COUNT(*) AS n FROM material_library_records WHERE source_kind='studio_custom'") or {"n": 0}
        discovered = self.discover_databases()
        return {"motorcad_version": self.motorcad_version, "records": int(total["n"]), "custom_records": int(custom["n"]), "databases": [self._decode_database(row) for row in databases], "discovered": discovered, "discovery": dict(self._last_discovery_diagnostics or {})}

    def list_records(self, query: str = "", kind: str = "", material_type: str = "", limit: int = 500) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if query:
            clauses.append("LOWER(name) LIKE ?")
            params.append(f"%{query.lower()}%")
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if material_type:
            clauses.append("material_type=?")
            params.append(material_type)
        params.append(max(1, min(int(limit), 5000)))
        rows = self.db.query_all(
            f"SELECT * FROM material_library_records WHERE {' AND '.join(clauses)} ORDER BY material_type,name LIMIT ?",
            tuple(params),
        )
        return [self._decode_record(row, compact=True) for row in rows]

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM material_library_records WHERE id=?", (record_id,))
        return self._decode_record(row, compact=False) if row else None

    def create_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("材料名称不能为空")
        kind = str(payload.get("kind") or "solid").lower()
        if kind not in {"solid", "fluid"}:
            raise ValueError("kind 仅支持 solid 或 fluid")
        material_type = "Fluid" if kind == "fluid" else str(payload.get("material_type") or "General")
        if kind == "solid" and material_type not in {"General", "Magnet", "Steel"}:
            raise ValueError("固体材料类型仅支持 General、Magnet、Steel")
        properties = dict(payload.get("properties") or {})
        properties["Type"] = "Fixed_Fluid" if kind == "fluid" else "Fixed_Solid"
        if kind == "solid":
            properties["Solid Type"] = material_type
        record_id = f"MAT-CUSTOM-{uuid.uuid4().hex[:16]}"
        now = _now()
        source_path = str(payload.get("source_database_path") or "").strip() or None
        source_hash = str(payload.get("source_database_hash") or "").strip() or None
        source_version = str(payload.get("motorcad_version") or self.motorcad_version)
        material = {"name": name, "kind": kind, "material_type": material_type, "properties": properties, "raw_entries": [{"key": key, "value": value} for key, value in properties.items()], "summary": summarize_properties(properties)}
        self.db.execute(
            "INSERT INTO material_library_records(id,name,kind,material_type,source_kind,source_database_path,source_database_hash,motorcad_version,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (record_id, name, kind, material_type, "studio_custom", source_path, source_hash, source_version, self.db.dumps(material), now, now),
        )
        return self.get_record(record_id) or {}

    def update_record(self, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_record(record_id)
        if not current:
            raise KeyError(record_id)
        name = str(payload.get("name", current["name"]) or "").strip()
        if not name:
            raise ValueError("材料名称不能为空")
        kind = str(payload.get("kind", current["kind"]) or "solid").lower()
        if kind not in {"solid", "fluid"}:
            raise ValueError("kind 仅支持 solid 或 fluid")
        material_type = "Fluid" if kind == "fluid" else str(payload.get("material_type", current["material_type"]) or "General")
        if kind == "solid" and material_type not in {"General", "Magnet", "Steel"}:
            raise ValueError("固体材料类型仅支持 General、Magnet、Steel")
        properties = dict(payload.get("properties", current.get("properties") or {}))
        properties["Type"] = "Fixed_Fluid" if kind == "fluid" else "Fixed_Solid"
        if kind == "solid":
            properties["Solid Type"] = material_type
        else:
            properties.pop("Solid Type", None)
        material = {"name": name, "kind": kind, "material_type": material_type, "properties": properties, "raw_entries": [{"key": key, "value": value} for key, value in properties.items()], "summary": summarize_properties(properties)}
        # Imported Motor-CAD rows are immutable snapshots. Editing one creates a
        # Studio-managed copy so a later rescan can never overwrite user changes.
        if current.get("source_kind") != "studio_custom":
            return self.create_record({
                "name": name,
                "kind": kind,
                "material_type": material_type,
                "properties": properties,
                "source_database_path": current.get("source_database_path"),
                "source_database_hash": current.get("source_database_hash"),
                "motorcad_version": current.get("motorcad_version") or self.motorcad_version,
            })
        self.db.execute(
            "UPDATE material_library_records SET name=?,kind=?,material_type=?,payload_json=?,updated_at=? WHERE id=?",
            (name, kind, material_type, self.db.dumps(material), _now(), record_id),
        )
        return self.get_record(record_id) or {}

    def clone_record(self, record_id: str, name: str | None = None) -> dict[str, Any]:
        current = self.get_record(record_id)
        if not current:
            raise KeyError(record_id)
        return self.create_record({
            "name": name or f"{current['name']} - Studio",
            "kind": current["kind"],
            "material_type": current["material_type"],
            "properties": current.get("properties") or {},
            "source_database_path": current.get("source_database_path"),
            "source_database_hash": current.get("source_database_hash"),
            "motorcad_version": current.get("motorcad_version") or self.motorcad_version,
        })

    def delete_record(self, record_id: str) -> bool:
        row = self.db.query_one("SELECT id FROM material_library_records WHERE id=?", (record_id,))
        if not row:
            return False
        self.db.execute("DELETE FROM material_library_records WHERE id=?", (record_id,))
        return True

    def export_managed(self, kind: str = "solid", filename: str | None = None) -> dict[str, Any]:
        if kind not in {"solid", "fluid"}:
            raise ValueError("kind 仅支持 solid 或 fluid")
        records = [self.get_record(row["id"]) for row in self.list_records(kind=kind, limit=5000)]
        records = [row for row in records if row]
        # A managed database must not contain duplicate section names. When an
        # imported snapshot and a Studio override share a name, the Studio row wins.
        by_name: dict[str, dict[str, Any]] = {}
        for row in records:
            key = str(row.get("name") or "").strip().casefold()
            if not key:
                continue
            if key not in by_name or row.get("source_kind") == "studio_custom":
                by_name[key] = row
        records = sorted(by_name.values(), key=lambda row: str(row.get("name") or "").casefold())
        default = "ManagedSolids.mdb" if kind == "solid" else "ManagedFluids.mdb"
        safe_name = Path(filename or default).name
        if not safe_name.lower().endswith(".mdb"):
            safe_name += ".mdb"
        path = self.managed_dir / safe_name
        path.write_text(serialize_mdb(records), encoding="utf-8")
        return {"path": str(path.resolve()), "file_hash": _file_hash(path), "material_count": len(records), "kind": kind}

    def _decode_record(self, row: dict[str, Any], *, compact: bool) -> dict[str, Any]:
        payload = self.db.loads(row.get("payload_json"), {}) or {}
        base = {
            "id": row["id"], "name": row["name"], "kind": row["kind"], "material_type": row["material_type"],
            "source_kind": row["source_kind"], "source_database_path": row.get("source_database_path"),
            "source_database_hash": row.get("source_database_hash"), "motorcad_version": row.get("motorcad_version"),
            "material_section_hash": _material_section_hash({
                "name": row.get("name"), "kind": row.get("kind"), "material_type": row.get("material_type"),
                "properties": payload.get("properties") or {},
            }),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
            "summary": payload.get("summary") or summarize_properties(payload.get("properties") or {}),
        }
        if not compact:
            base["properties"] = payload.get("properties") or {}
            base["raw_entries"] = payload.get("raw_entries") or []
        return base

    def _decode_database(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "metadata": self.db.loads(row.get("metadata_json"), {}) or {}}
