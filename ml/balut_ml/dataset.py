from __future__ import annotations

import hashlib
import json
import warnings as image_warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .release import file_sha256


AppearanceLabel = Literal["DAY_16_LIKE", "DAY_18_LIKE", "REJECT_SUSPECT"]
Partition = Literal["train", "validation", "prospective_test"]


class DatasetFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    frame_id: str = Field(min_length=8)
    inspection_id: str = Field(min_length=8)
    physical_egg_id: str = Field(min_length=3)
    batch_id: str = Field(min_length=3)
    image_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_index: int = Field(ge=0, le=7)
    angle_degrees: float = Field(ge=0, lt=360)
    label: AppearanceLabel
    label_authority: str = Field(min_length=3)
    partition: Partition
    recorded_elapsed_hours: float | None = Field(default=None, ge=0)
    reviewer_disposition_ids: list[str] = Field(default_factory=list)
    unresolved: bool = False
    is_augmented: bool = False
    parent_frame_id: str | None = None

    @field_validator("label_authority")
    @classmethod
    def reject_labels_require_review_authority(cls, value: str) -> str:
        banned = {"public_reject", "public_bulok", "filename_guess", "model_prediction"}
        if value.lower() in banned:
            raise ValueError("public or inferred labels cannot become supervised ground truth")
        return value


@dataclass
class AuditReport:
    valid: bool
    manifest_sha256: str
    row_count: int
    physical_egg_count: int
    inspection_count: int
    class_counts: dict[str, int]
    partition_counts: dict[str, int]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "manifest_sha256": self.manifest_sha256,
            "row_count": self.row_count,
            "physical_egg_count": self.physical_egg_count,
            "inspection_count": self.inspection_count,
            "class_counts": self.class_counts,
            "partition_counts": self.partition_counts,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def canonical_manifest_hash(rows: Iterable[DatasetFrame]) -> str:
    canonical = [row.model_dump(mode="json") for row in rows]
    canonical.sort(key=lambda row: str(row["frame_id"]))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: Path) -> Iterator[DatasetFrame]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield DatasetFrame.model_validate_json(line)
            except ValidationError as error:
                raise ValueError(f"invalid manifest row {line_number}: {error}") from error


def audit_rows(
    rows: Iterable[DatasetFrame],
    *,
    require_batch_partition_isolation: bool = True,
    require_files: bool = False,
    manifest_root: Path | None = None,
) -> AuditReport:
    if require_files:
        from PIL import Image, ImageOps
    materialized = list(rows)
    errors: list[str] = []
    warnings: list[str] = []
    frame_ids: set[str] = set()
    egg_partitions: dict[str, set[str]] = defaultdict(set)
    batch_partitions: dict[str, set[str]] = defaultdict(set)
    source_hashes: dict[str, list[str]] = defaultdict(list)
    inspection_views: dict[str, set[int]] = defaultdict(set)
    inspection_identity: dict[str, set[tuple]] = defaultdict(set)
    frames_by_id = {row.frame_id: row for row in materialized}
    decoded_images: dict[str, tuple[str, str, str]] = {}
    class_counts: dict[str, int] = defaultdict(int)
    partition_counts: dict[str, int] = defaultdict(int)

    for row in materialized:
        if row.frame_id in frame_ids:
            errors.append(f"duplicate frame_id: {row.frame_id}")
        frame_ids.add(row.frame_id)
        egg_partitions[row.physical_egg_id].add(row.partition)
        batch_partitions[row.batch_id].add(row.partition)
        source_hashes[row.source_sha256].append(row.frame_id)
        if not row.is_augmented:
            if row.view_index in inspection_views[row.inspection_id]:
                errors.append(f"duplicate inspection view: {row.inspection_id}/{row.view_index}")
            inspection_views[row.inspection_id].add(row.view_index)
        inspection_identity[row.inspection_id].add((row.physical_egg_id, row.batch_id, row.partition, row.label, row.recorded_elapsed_hours))
        class_counts[row.label] += 1
        partition_counts[row.partition] += 1

        if row.unresolved:
            errors.append(f"unresolved frame cannot enter supervised manifest: {row.frame_id}")
        if row.is_augmented and row.partition != "train":
            errors.append(f"augmented frame outside train partition: {row.frame_id}")
        if row.is_augmented and not row.parent_frame_id:
            errors.append(f"augmented frame missing parent_frame_id: {row.frame_id}")
        if row.is_augmented and row.parent_frame_id:
            parent = frames_by_id.get(row.parent_frame_id)
            if parent is None or parent.is_augmented or parent.frame_id == row.frame_id:
                errors.append(f"augmentation parent must be an original manifest frame: {row.frame_id}")
            elif (parent.physical_egg_id, parent.batch_id, parent.inspection_id, parent.partition, parent.label, parent.view_index) != (row.physical_egg_id, row.batch_id, row.inspection_id, row.partition, row.label, row.view_index):
                errors.append(f"augmentation changes parent identity or partition: {row.frame_id}")
        if row.label in {"DAY_16_LIKE", "DAY_18_LIKE"} and row.recorded_elapsed_hours is None:
            errors.append(f"age-like label missing recorded elapsed hours: {row.frame_id}")
        if row.label == "REJECT_SUSPECT" and len(set(row.reviewer_disposition_ids)) < 2:
            warnings.append(f"reject frame lacks two reviewer disposition references: {row.frame_id}")
        if require_files:
            image_path = Path(row.image_path)
            if not image_path.is_absolute() and manifest_root is not None:
                image_path = manifest_root / image_path
                if not image_path.resolve().is_relative_to(manifest_root.resolve()):
                    errors.append(f"image path escapes manifest directory: {row.frame_id}")
                    continue
            if not image_path.is_file():
                errors.append(f"image file missing: {row.image_path}")
                continue
            try:
                if file_sha256(image_path) != row.source_sha256:
                    errors.append(f"image SHA-256 mismatch: {row.frame_id}")
                    continue
                with image_warnings.catch_warnings():
                    image_warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(image_path) as image:
                        if min(image.size) < 32 or image.width * image.height > 16_000_000:
                            raise ValueError("Image outside supported dimensions")
                        image.verify()
                    with Image.open(image_path) as image:
                        pixels = ImageOps.exif_transpose(image).convert("RGB")
                        digest = hashlib.sha256(str(pixels.size).encode() + pixels.tobytes()).hexdigest()
                identity = (row.physical_egg_id, row.partition, row.label)
                if digest in decoded_images and decoded_images[digest] != identity:
                    errors.append(f"identical decoded image has conflicting egg, partition, or label: {row.frame_id}")
                decoded_images[digest] = identity
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                errors.append(f"invalid image evidence: {row.frame_id} ({type(error).__name__})")

    for egg_id, partitions in egg_partitions.items():
        if len(partitions) > 1:
            errors.append(f"physical egg crosses partitions: {egg_id} -> {sorted(partitions)}")
    if require_batch_partition_isolation:
        for batch_id, partitions in batch_partitions.items():
            if len(partitions) > 1:
                errors.append(f"incubation batch crosses partitions: {batch_id} -> {sorted(partitions)}")
    for source_hash, matching_frames in source_hashes.items():
        if len(matching_frames) > 1:
            errors.append(f"duplicate source image hash {source_hash}: {matching_frames}")
    for inspection_id, views in inspection_views.items():
        if len(views) != 8:
            warnings.append(f"inspection does not contain exactly eight unique views: {inspection_id} ({len(views)})")
    for inspection_id, identities in inspection_identity.items():
        if len(identities) != 1:
            errors.append(f"inspection has conflicting egg, batch, partition, label, or age: {inspection_id}")

    if not materialized:
        errors.append("manifest is empty")

    return AuditReport(
        valid=not errors,
        manifest_sha256=canonical_manifest_hash(materialized),
        row_count=len(materialized),
        physical_egg_count=len(egg_partitions),
        inspection_count=len(inspection_views),
        class_counts=dict(sorted(class_counts.items())),
        partition_counts=dict(sorted(partition_counts.items())),
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )


def audit_manifest(path: Path, *, require_files: bool = True) -> AuditReport:
    rows = list(read_jsonl(path))
    return audit_rows(rows, require_files=require_files, manifest_root=path.parent)
