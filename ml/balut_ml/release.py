from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EXPECTED_CLASS_ORDER = ["DAY_16_LIKE", "DAY_18_LIKE", "REJECT_SUSPECT"]


class QuantizationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dtype: Literal["int8"] = "int8"
    scheme: Literal["symmetric"] = "symmetric"
    input_scale: float = Field(gt=0)
    input_zero_point: int = Field(ge=-128, le=127)


class ModelReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_width: int = Field(gt=0)
    input_height: int = Field(gt=0)
    color_order: Literal["RGB"] = "RGB"
    normalization: str
    class_order: list[str]
    quantization: QuantizationSpec
    quality_gate_version: str
    aggregate_threshold_version: str
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    firmware_compatibility_min: str
    firmware_compatibility_max: str
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    rollback_model_id: str | None = None

    @field_validator("class_order")
    @classmethod
    def class_order_is_frozen(cls, value: list[str]) -> list[str]:
        if value != EXPECTED_CLASS_ORDER:
            raise ValueError(f"class order must be exactly {EXPECTED_CLASS_ORDER}")
        return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_release_manifest(manifest: ModelReleaseManifest, path: Path) -> None:
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_release_artifact(manifest: ModelReleaseManifest, model_path: Path) -> bool:
    return model_path.is_file() and file_sha256(model_path) == manifest.model_sha256
