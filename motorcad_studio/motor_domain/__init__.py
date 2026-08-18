from .capabilities import MotorCapabilitySet
from .components import MotorAssemblySnapshot, MotorComponentSnapshot
from .identity import MotorIdentity
from .materials import MaterialAssignmentSet, MaterialReference
from .model import MotorModel
from .parameters import NativeParameterBinding, ParameterDescriptor, ParameterSet
from .registry import MotorDomainRegistry
from .snapshot import MOTOR_SNAPSHOT_SCHEMA_VERSION, MotorChange, MotorChangeSet, MotorSnapshot
from .winding import CoilDefinition, WindingModel

__all__ = [
    "MOTOR_SNAPSHOT_SCHEMA_VERSION", "MotorIdentity", "MotorSnapshot", "MotorChange", "MotorChangeSet",
    "ParameterDescriptor", "ParameterSet", "NativeParameterBinding", "MotorComponentSnapshot", "MotorAssemblySnapshot",
    "WindingModel", "CoilDefinition", "MaterialAssignmentSet", "MaterialReference", "MotorCapabilitySet", "MotorDomainRegistry", "MotorModel",
]
