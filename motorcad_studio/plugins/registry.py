from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ..version import __version__

from .builtin_pm import BuiltinPMFamilyPlugin
from .builtin_induction import BuiltinInductionFamilyPlugin
from .contracts import PLUGIN_API_VERSION, MotorFamilyPlugin, PluginContractSnapshot, PluginIdentity, ProviderDescriptor


class MotorPluginContractError(RuntimeError):
    pass


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _version_key(value: str | None) -> tuple[int, ...]:
    """Best-effort numeric version key for Studio compatibility gates.

    Motor-family plugin ABI v1 intentionally avoids a packaging-library dependency.
    Non-numeric suffixes are ignored for the compatibility floor/ceiling check.
    """
    parts: list[int] = []
    for token in str(value or "0").replace("-", ".").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts or [0])


class MotorFamilyPluginRegistry:
    """Current authority for motor-family extension discovery and contract validation."""

    REQUIRED_METHODS = (
        "identity", "topology_providers", "parameter_descriptors", "capability_set",
        "visualization_providers", "native_bindings", "analysis_recipes", "result_contracts",
        "optimization_policy", "qualification_profiles", "migrations",
    )

    def __init__(self, *, studio_version: str = __version__, log_store: Any | None = None):
        self.studio_version = studio_version
        self.log_store = log_store
        self._plugins: dict[str, MotorFamilyPlugin] = {}
        self._topology_owner: dict[str, str] = {}
        self._family_plugins: dict[str, list[str]] = {}

    def _log(self, level: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if self.log_store is None:
            return
        fn = getattr(self.log_store, "plugin", None) or getattr(self.log_store, "log", None)
        if callable(fn):
            data = payload or {}
            fn(
                level=level, component="motor_plugin_registry", event_type=event_type, message=message,
                plugin_id=str(data.get("plugin_id") or "") or None,
                topology_id=str(data.get("topology_id") or "") or None,
                payload=data,
            )

    @staticmethod
    def _provider_list(values: list[Any] | None) -> list[ProviderDescriptor]:
        return [value if isinstance(value, ProviderDescriptor) else ProviderDescriptor.model_validate(value) for value in (values or [])]

    def validate(self, plugin: MotorFamilyPlugin) -> PluginContractSnapshot:
        missing = [name for name in self.REQUIRED_METHODS if not callable(getattr(plugin, name, None))]
        if missing:
            raise MotorPluginContractError("plugin missing mandatory methods: " + ", ".join(missing))
        identity = plugin.identity()
        if not isinstance(identity, PluginIdentity):
            identity = PluginIdentity.model_validate(identity)
        if identity.api_version != PLUGIN_API_VERSION:
            raise MotorPluginContractError(
                f"plugin {identity.plugin_id} API {identity.api_version} is incompatible with {PLUGIN_API_VERSION}"
            )
        studio_key = _version_key(self.studio_version)
        if identity.minimum_studio_version and studio_key < _version_key(identity.minimum_studio_version):
            raise MotorPluginContractError(
                f"plugin {identity.plugin_id} requires Studio >= {identity.minimum_studio_version}; current={self.studio_version}"
            )
        if identity.maximum_studio_version and studio_key > _version_key(identity.maximum_studio_version):
            raise MotorPluginContractError(
                f"plugin {identity.plugin_id} requires Studio <= {identity.maximum_studio_version}; current={self.studio_version}"
            )
        topologies = deepcopy(plugin.topology_providers() or {})
        if not isinstance(topologies, dict):
            raise MotorPluginContractError(f"plugin {identity.plugin_id} topology_providers must return a mapping")
        declared = set(identity.topology_ids)
        contributed = set(str(key) for key in topologies)
        if declared != contributed:
            raise MotorPluginContractError(
                f"plugin {identity.plugin_id} topology declaration mismatch: identity={sorted(declared)} providers={sorted(contributed)}"
            )
        descriptors: dict[str, dict[str, Any]] = {}
        for parameter_id, value in (plugin.parameter_descriptors() or {}).items():
            descriptor = dict(value or {})
            descriptor.setdefault("id", parameter_id)
            if str(descriptor.get("id")) != str(parameter_id):
                raise MotorPluginContractError(f"plugin {identity.plugin_id} parameter id mismatch: {parameter_id} != {descriptor.get('id')}")
            descriptors[parameter_id] = deepcopy(descriptor)
        component_method = getattr(plugin, "component_providers", None)
        components = self._provider_list(component_method() if callable(component_method) else [])
        visualization = self._provider_list(plugin.visualization_providers())
        native_bindings = self._provider_list(plugin.native_bindings())
        analyses = self._provider_list(plugin.analysis_recipes())
        results = self._provider_list(plugin.result_contracts())
        for provider_kind, providers in (
            ("component", components), ("visualization", visualization), ("native_binding", native_bindings),
            ("analysis", analyses), ("result_contract", results),
        ):
            ids = [provider.provider_id for provider in providers]
            if len(ids) != len(set(ids)):
                raise MotorPluginContractError(f"plugin {identity.plugin_id} has duplicate {provider_kind} provider_id")
            for provider in providers:
                unknown = set(provider.topology_ids) - declared
                if unknown:
                    raise MotorPluginContractError(
                        f"plugin {identity.plugin_id} {provider_kind} provider {provider.provider_id} references undeclared topologies {sorted(unknown)}"
                    )
        snapshot = PluginContractSnapshot(
            identity=identity,
            topology_providers=topologies,
            parameter_descriptors=descriptors,
            component_providers=components,
            visualization_providers=visualization,
            native_binding_providers=native_bindings,
            analysis_providers=analyses,
            result_contract_providers=results,
            optimization_policy=deepcopy(plugin.optimization_policy() or {}),
            qualification_profiles=deepcopy(plugin.qualification_profiles() or []),
            migrations=deepcopy(plugin.migrations() or []),
        )
        payload = snapshot.model_dump(mode="json", exclude={"contract_hash"})
        snapshot.contract_hash = _stable_hash(payload)
        return snapshot

    def register(self, plugin: MotorFamilyPlugin, *, replace: bool = False) -> PluginContractSnapshot:
        snapshot = self.validate(plugin)
        plugin_id = snapshot.identity.plugin_id
        if plugin_id in self._plugins and not replace:
            raise MotorPluginContractError(f"plugin already registered: {plugin_id}")
        if plugin_id in self._plugins and replace:
            # Remove the previous topology/family ownership first so replacement cannot
            # leave stale ownership for topologies removed by the new contract.
            self.unregister(plugin_id)
        for topology_id in snapshot.identity.topology_ids:
            owner = self._topology_owner.get(topology_id)
            if owner and owner != plugin_id and not replace:
                raise MotorPluginContractError(f"topology {topology_id} already owned by plugin {owner}")
        self._plugins[plugin_id] = plugin
        for topology_id in snapshot.identity.topology_ids:
            self._topology_owner[topology_id] = plugin_id
        for family_id in snapshot.identity.family_ids:
            owners = [value for value in self._family_plugins.get(family_id, []) if value != plugin_id]
            owners.append(plugin_id)
            self._family_plugins[family_id] = owners
        self._log("INFO", "MOTOR_PLUGIN_REGISTERED", f"registered motor family plugin {plugin_id}", {
            "plugin_id": plugin_id, "version": snapshot.identity.version,
            "families": snapshot.identity.family_ids, "topologies": snapshot.identity.topology_ids,
            "contract_hash": snapshot.contract_hash,
        })
        return snapshot

    def unregister(self, plugin_id: str) -> None:
        plugin = self._plugins.pop(plugin_id, None)
        if plugin is None:
            return
        identity = plugin.identity()
        for topology_id in identity.topology_ids:
            if self._topology_owner.get(topology_id) == plugin_id:
                self._topology_owner.pop(topology_id, None)
        for family_id in identity.family_ids:
            self._family_plugins[family_id] = [x for x in self._family_plugins.get(family_id, []) if x != plugin_id]
        self._log("INFO", "MOTOR_PLUGIN_UNREGISTERED", f"unregistered motor family plugin {plugin_id}", {"plugin_id": plugin_id})

    def plugin(self, plugin_id: str) -> MotorFamilyPlugin | None:
        return self._plugins.get(plugin_id)

    def plugin_for_topology(self, topology_id: str) -> MotorFamilyPlugin | None:
        owner = self._topology_owner.get(str(topology_id))
        return self._plugins.get(owner) if owner else None

    def topology_owner(self, topology_id: str) -> str | None:
        return self._topology_owner.get(str(topology_id))

    def topologies(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for plugin_id, plugin in self._plugins.items():
            for topology_id, value in (plugin.topology_providers() or {}).items():
                rows[str(topology_id)] = {**deepcopy(value), "plugin_id": plugin_id}
        return rows

    def parameter_descriptors(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for plugin in self._plugins.values():
            for parameter_id, value in (plugin.parameter_descriptors() or {}).items():
                descriptor = dict(value or {})
                descriptor.setdefault("id", parameter_id)
                if parameter_id in result:
                    raise MotorPluginContractError(f"duplicate plugin parameter descriptor: {parameter_id}")
                result[parameter_id] = descriptor
        return result

    def parameter_descriptors_for_topology(self, topology_id: str) -> dict[str, dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        if plugin is None:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for parameter_id, value in (plugin.parameter_descriptors() or {}).items():
            row = deepcopy(dict(value or {}))
            applicable = list(row.get("applicable_topologies") or [])
            if applicable and topology_id not in applicable:
                continue
            row.setdefault("id", parameter_id)
            result[str(parameter_id)] = row
        return result

    def component_providers_for_topology(self, topology_id: str) -> list[dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        method = getattr(plugin, "component_providers", None) if plugin else None
        if not callable(method):
            return []
        rows = []
        for value in method() or []:
            row = value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(dict(value or {}))
            if topology_id in list(row.get("topology_ids") or []):
                rows.append(row)
        return rows

    def native_binding_providers_for_topology(self, topology_id: str) -> list[dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        if plugin is None:
            return []
        rows = []
        for value in plugin.native_bindings() or []:
            row = value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(dict(value or {}))
            if topology_id in list(row.get("topology_ids") or []):
                rows.append(row)
        return rows

    def analysis_providers_for_topology(self, topology_id: str) -> list[dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        if plugin is None:
            return []
        rows = []
        for value in plugin.analysis_recipes() or []:
            row = value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(dict(value or {}))
            if topology_id in list(row.get("topology_ids") or []):
                rows.append(row)
        return rows

    def result_descriptors_for_topology(self, topology_id: str) -> dict[str, dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        if plugin is None:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for value in plugin.result_contracts() or []:
            row = value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(dict(value or {}))
            if topology_id not in list(row.get("topology_ids") or []):
                continue
            for output_id, definition in dict((row.get("metadata") or {}).get("outputs") or {}).items():
                result[str(output_id)] = deepcopy(dict(definition or {}))
        return result

    def material_sources_for_topology(self, topology_id: str) -> dict[str, list[str]]:
        plugin = self.plugin_for_topology(topology_id)
        method = getattr(plugin, "material_sources", None) if plugin else None
        if not callable(method):
            return {}
        return {str(key): [str(v) for v in values] for key, values in dict(method() or {}).items()}

    def project_motor_object(self, topology_id: str, *, snapshot: dict[str, Any], descriptors: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
        plugin = self.plugin_for_topology(topology_id)
        method = getattr(plugin, "project_motor_object", None) if plugin else None
        if not callable(method):
            return None
        return method(deepcopy(snapshot), deepcopy(descriptors), deepcopy(overrides or {}))

    def analysis_extensions_for_topology(self, topology_id: str) -> dict[str, dict[str, Any]]:
        plugin = self.plugin_for_topology(topology_id)
        if plugin is None:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for value in plugin.analysis_recipes() or []:
            row = value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(dict(value or {}))
            if topology_id not in list(row.get("topology_ids") or []):
                continue
            for recipe_id, extension in dict((row.get("metadata") or {}).get("recipe_extensions") or {}).items():
                target = result.setdefault(str(recipe_id), {"sections": [], "optional_outputs": [], "required_outputs": []})
                target["sections"].extend(deepcopy(list((extension or {}).get("sections") or [])))
                target["optional_outputs"].extend(str(v) for v in (extension or {}).get("optional_outputs") or [])
                target["required_outputs"].extend(str(v) for v in (extension or {}).get("required_outputs") or [])
        for target in result.values():
            target["optional_outputs"] = list(dict.fromkeys(target["optional_outputs"]))
            target["required_outputs"] = list(dict.fromkeys(target["required_outputs"]))
        return result

    def capabilities_for(self, identity: Any) -> dict[str, Any]:
        plugin = self.plugin_for_topology(identity.topology_id)
        if plugin is None:
            return {"features": {}, "native_modules": [], "evidence": {}}
        value = plugin.capability_set(identity)
        return deepcopy(value or {})

    def snapshot(self, plugin_id: str) -> PluginContractSnapshot | None:
        plugin = self._plugins.get(plugin_id)
        return self.validate(plugin) if plugin else None

    def catalog(self) -> dict[str, Any]:
        rows = []
        for plugin_id in sorted(self._plugins):
            snapshot = self.validate(self._plugins[plugin_id])
            rows.append(snapshot.model_dump(mode="json"))
        return {
            "schema_version": 1,
            "plugin_api_version": PLUGIN_API_VERSION,
            "studio_version": self.studio_version,
            "plugin_count": len(rows),
            "topology_count": len(self._topology_owner),
            "plugins": rows,
            "topology_owners": dict(sorted(self._topology_owner.items())),
        }

    @staticmethod
    def _load_object(import_path: str) -> Any:
        module_name, sep, object_name = str(import_path).partition(":")
        if not sep:
            raise MotorPluginContractError(f"plugin import must be module:Object, got {import_path}")
        module = importlib.import_module(module_name)
        return getattr(module, object_name)

    def load_configured(self, *, registry: Any, config_dir: Path) -> dict[str, Any]:
        config_dir = Path(config_dir)
        path = config_dir / "motor_family_plugins.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        rows = list((payload or {}).get("plugins") or [])
        results: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not bool(row.get("enabled", True)):
                continue
            plugin_id = str(row.get("id") or "")
            try:
                kind = str(row.get("kind") or "python")
                if kind == "builtin" and plugin_id == "builtin.pm":
                    plugin = BuiltinPMFamilyPlugin(registry, config_dir)
                elif kind == "builtin" and plugin_id == "builtin.induction":
                    plugin = BuiltinInductionFamilyPlugin(registry, config_dir)
                else:
                    factory = self._load_object(str(row.get("import") or ""))
                    plugin = factory(registry=registry, config_dir=config_dir) if callable(factory) else factory
                identity = plugin.identity()
                identity = identity if isinstance(identity, PluginIdentity) else PluginIdentity.model_validate(identity)
                if plugin_id and identity.plugin_id != plugin_id:
                    raise MotorPluginContractError(
                        f"configured plugin id {plugin_id} does not match plugin identity {identity.plugin_id}"
                    )
                snapshot = self.register(plugin)
                results.append({"plugin_id": snapshot.identity.plugin_id, "status": "LOADED", "contract_hash": snapshot.contract_hash})
            except Exception as exc:
                self._log("ERROR", "MOTOR_PLUGIN_LOAD_FAILED", f"failed to load motor plugin {plugin_id or '<unknown>'}: {exc}", {
                    "plugin_id": plugin_id, "config": row, "error_type": type(exc).__name__, "error": str(exc),
                })
                results.append({"plugin_id": plugin_id, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
        return {"config": str(path), "results": results, "catalog": self.catalog()}


def create_motor_plugin_registry(registry: Any, config_dir: Path, *, studio_version: str = __version__, log_store: Any | None = None) -> MotorFamilyPluginRegistry:
    result = MotorFamilyPluginRegistry(studio_version=studio_version, log_store=log_store)
    result.load_configured(registry=registry, config_dir=Path(config_dir))
    return result
