from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

PLUGIN_API_VERSION = "1"


class PluginIdentity(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    api_version: str = PLUGIN_API_VERSION
    family_ids: list[str] = Field(default_factory=list)
    topology_ids: list[str] = Field(default_factory=list)
    minimum_studio_version: str | None = None
    maximum_studio_version: str | None = None
    source: str = "builtin"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderDescriptor(BaseModel):
    provider_id: str
    provider_kind: str
    family_ids: list[str] = Field(default_factory=list)
    topology_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginContractSnapshot(BaseModel):
    schema_version: int = 1
    identity: PluginIdentity
    topology_providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    parameter_descriptors: dict[str, dict[str, Any]] = Field(default_factory=dict)
    component_providers: list[ProviderDescriptor] = Field(default_factory=list)
    visualization_providers: list[ProviderDescriptor] = Field(default_factory=list)
    native_binding_providers: list[ProviderDescriptor] = Field(default_factory=list)
    analysis_providers: list[ProviderDescriptor] = Field(default_factory=list)
    result_contract_providers: list[ProviderDescriptor] = Field(default_factory=list)
    optimization_policy: dict[str, Any] = Field(default_factory=dict)
    qualification_profiles: list[dict[str, Any]] = Field(default_factory=list)
    migrations: list[dict[str, Any]] = Field(default_factory=list)
    contract_hash: str = ""


@runtime_checkable
class MotorFamilyPlugin(Protocol):
    """Stable, implementation-neutral Motor Family Plugin Contract v1.

    Plugins intentionally exchange JSON-like payloads at this boundary. Studio turns
    them into typed Domain objects after registration, avoiding a circular dependency
    and keeping third-party plugin ABI independent of internal package layout.
    """

    def identity(self) -> PluginIdentity | dict[str, Any]: ...
    def topology_providers(self) -> dict[str, dict[str, Any]]: ...
    def parameter_descriptors(self) -> dict[str, dict[str, Any]]: ...
    def capability_set(self, identity: Any) -> dict[str, Any]: ...
    # component_providers and project_motor_object are optional V0.75-B extension points;
    # they remain optional so Plugin Contract v1 stays source-compatible with V0.75-A plugins.
    def component_providers(self) -> list[ProviderDescriptor | dict[str, Any]]: ...
    def visualization_providers(self) -> list[ProviderDescriptor | dict[str, Any]]: ...
    def native_bindings(self) -> list[ProviderDescriptor | dict[str, Any]]: ...
    def analysis_recipes(self) -> list[ProviderDescriptor | dict[str, Any]]: ...
    def result_contracts(self) -> list[ProviderDescriptor | dict[str, Any]]: ...
    def optimization_policy(self) -> dict[str, Any]: ...
    def qualification_profiles(self) -> list[dict[str, Any]]: ...
    def migrations(self) -> list[dict[str, Any]]: ...
