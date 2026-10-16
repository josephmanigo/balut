from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InspectionOutcome(StrEnum):
    DAY_16_LIKE = "DAY_16_LIKE"
    DAY_18_LIKE = "DAY_18_LIKE"
    REJECT_SUSPECT = "REJECT_SUSPECT"
    REVIEW_RECAPTURE = "REVIEW_RECAPTURE"


class InspectionState(StrEnum):
    CREATED = "CREATED"
    CAPTURING = "CAPTURING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    SAFE_STOPPED = "SAFE_STOPPED"
    UPLOAD_PENDING = "UPLOAD_PENDING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class HumanDisposition(StrEnum):
    CONFIRMED_DAY_16 = "CONFIRMED_DAY_16"
    CONFIRMED_DAY_18 = "CONFIRMED_DAY_18"
    CONFIRMED_REJECT_SUSPECT = "CONFIRMED_REJECT_SUSPECT"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class MachineFlag(StrEnum):
    IMAGE_TOO_DARK = "IMAGE_TOO_DARK"
    IMAGE_SATURATED = "IMAGE_SATURATED"
    IMAGE_BLURRED = "IMAGE_BLURRED"
    EGG_NOT_FOUND = "EGG_NOT_FOUND"
    INCOMPLETE_ROTATION = "INCOMPLETE_ROTATION"
    VIEW_DISAGREEMENT = "VIEW_DISAGREEMENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AGE_APPEARANCE_MISMATCH = "AGE_APPEARANCE_MISMATCH"
    DEVICE_FAULT = "DEVICE_FAULT"
    MODEL_REJECT_SUSPECT = "MODEL_REJECT_SUSPECT"


class SimulatorScenario(StrEnum):
    DAY_16 = "day16"
    DAY_18 = "day18"
    REJECT = "reject"
    LOW_CONFIDENCE = "low_confidence"
    BAD_CAPTURE = "bad_capture"
    AGE_MISMATCH = "age_mismatch"
    DEVICE_FAULT = "device_fault"


class Authority(StrEnum):
    SHADOW_ONLY = "SHADOW_ONLY"
    RESEARCH_VALIDATED = "RESEARCH_VALIDATED"


class ClassProbabilities(BaseModel):
    day_16_like: Annotated[float, Field(ge=0, le=1)]
    day_18_like: Annotated[float, Field(ge=0, le=1)]
    reject_suspect: Annotated[float, Field(ge=0, le=1)]

    @field_validator("reject_suspect")
    @classmethod
    def probabilities_must_sum(cls, value: float, info):
        values = info.data
        if "day_16_like" in values and "day_18_like" in values:
            total = values["day_16_like"] + values["day_18_like"] + value
            if abs(total - 1.0) > 0.015:
                raise ValueError("class probabilities must sum to 1.0")
        return value

    def as_outcomes(self) -> dict[InspectionOutcome, float]:
        return {
            InspectionOutcome.DAY_16_LIKE: self.day_16_like,
            InspectionOutcome.DAY_18_LIKE: self.day_18_like,
            InspectionOutcome.REJECT_SUSPECT: self.reject_suspect,
        }


class ViewAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_index: Annotated[int, Field(ge=0, le=7)]
    angle_degrees: Annotated[float, Field(ge=0, lt=360)]
    quality_valid: bool
    probabilities: ClassProbabilities
    flags: list[MachineFlag] = Field(default_factory=list)
    image_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    capture_ms: int = Field(default=0, ge=0)
    inference_ms: int = Field(default=0, ge=0)


class InspectionIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspection_id: str = Field(min_length=8, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    batch_id: str | None = Field(default=None, max_length=80)
    egg_id: str | None = Field(default=None, max_length=80)
    recorded_elapsed_hours: float | None = Field(default=None, ge=0, le=1000)
    model_release_id: str = Field(min_length=3, max_length=120)
    threshold_profile_id: str = Field(min_length=3, max_length=120)
    firmware_version: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    views: list[ViewAssessment] = Field(min_length=1, max_length=8)
    device_flags: list[MachineFlag] = Field(default_factory=list)
    captured_at: datetime
    is_simulated: bool = False
    authority: Authority = Authority.SHADOW_ONLY

    @field_validator("captured_at")
    @classmethod
    def timestamp_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone offset")
        return value.astimezone(timezone.utc)

    @field_validator("views")
    @classmethod
    def view_indexes_are_unique(cls, value: list[ViewAssessment]):
        indexes = [view.view_index for view in value]
        if len(indexes) != len(set(indexes)):
            raise ValueError("view indexes must be unique")
        return sorted(value, key=lambda view: view.view_index)


class AggregateDecision(BaseModel):
    outcome: InspectionOutcome
    state: InspectionState
    confidence: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    agreement: float = Field(ge=0, le=1)
    valid_views: int = Field(ge=0, le=8)
    expected_views: int = 8
    mean_probabilities: ClassProbabilities
    flags: list[MachineFlag]
    authority: Authority
    explanation: str


class HumanReviewCreate(BaseModel):
    reviewer_id: str = Field(min_length=2, max_length=80)
    disposition: HumanDisposition
    reason_codes: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=2000)
    blinded_to_machine_result: bool


class SimulatorRunRequest(BaseModel):
    scenario: SimulatorScenario = SimulatorScenario.DAY_16
    recorded_elapsed_hours: float | None = Field(default=384.0, ge=0, le=1000)
    egg_id: str | None = Field(default=None, max_length=80)


class StartScanRequest(BaseModel):
    device_id: str
    batch_id: str | None = None
    egg_id: str | None = None


class BatchCreate(BaseModel):
    batch_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    incubator_entry_at: datetime
    supplier: str = Field(default="", max_length=160)

    @field_validator("incubator_entry_at")
    @classmethod
    def entry_timestamp_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("incubator_entry_at must include a timezone offset")
        return value.astimezone(timezone.utc)


class EggCreate(BaseModel):
    egg_id: str = Field(min_length=3, max_length=80)
    batch_id: str = Field(min_length=3, max_length=80)
    source_label: str = Field(default="", max_length=160)


class DeviceTelemetry(BaseModel):
    device_id: str
    state: str
    lid_closed: bool
    egg_present: bool
    emergency_stop_released: bool
    temperature_c: float
    light_enabled: bool
    motor_enabled: bool
    model_release_id: str
    firmware_version: str
    recorded_at: datetime
