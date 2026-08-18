from __future__ import annotations

from pydantic import BaseModel, Field


class MotorIdentity(BaseModel):
    """Stable engineering identity for one immutable motor snapshot.

    ``native_motor_type`` is the Motor-CAD model family (BPM/BPMOR/IM/...).
    ``family_id`` is the physical family used by Studio (rfpm/afpm/induction/...).
    ``topology_id`` is the concrete topology (rfpm_spm/rfpm_ipm/afpm_ssdr/...).
    Templates remain presets/origins and are deliberately not used as the type system.
    """

    native_motor_type: str = Field(min_length=1, max_length=40)
    family_id: str = Field(min_length=1, max_length=80)
    topology_id: str = Field(min_length=1, max_length=120)
    template_id: str = Field(default="", max_length=200)
    system_template_id: str = Field(default="", max_length=200)
    source_kind: str = Field(default="template", max_length=80)
    source_reference: str = Field(default="", max_length=500)
    geometry_mode: str = Field(default="dimensions", max_length=80)
