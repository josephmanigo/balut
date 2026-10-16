from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from .domain import (
    Authority,
    ClassProbabilities,
    InspectionIngest,
    MachineFlag,
    SimulatorRunRequest,
    SimulatorScenario,
    ViewAssessment,
)


def _probabilities(scenario: SimulatorScenario, index: int) -> ClassProbabilities:
    wobble = ((index % 3) - 1) * 0.01
    if scenario == SimulatorScenario.DAY_16:
        day_16 = 0.89 + wobble
        day_18 = 0.07 - wobble / 2
        reject = 1 - day_16 - day_18
    elif scenario in {SimulatorScenario.DAY_18, SimulatorScenario.AGE_MISMATCH}:
        day_18 = 0.88 + wobble
        day_16 = 0.08 - wobble / 2
        reject = 1 - day_16 - day_18
    elif scenario == SimulatorScenario.REJECT:
        reject = 0.87 + wobble
        day_16 = 0.07 - wobble / 2
        day_18 = 1 - day_16 - reject
    elif scenario == SimulatorScenario.LOW_CONFIDENCE:
        rotations = [
            (0.40, 0.34, 0.26),
            (0.37, 0.38, 0.25),
            (0.38, 0.31, 0.31),
        ]
        day_16, day_18, reject = rotations[index % len(rotations)]
    else:
        day_16, day_18, reject = 0.84, 0.10, 0.06
    return ClassProbabilities(
        day_16_like=round(day_16, 4),
        day_18_like=round(day_18, 4),
        reject_suspect=round(reject, 4),
    )


def build_simulated_ingest(request: SimulatorRunRequest) -> InspectionIngest:
    inspection_id = f"SIM-{uuid4()}"
    egg_id = request.egg_id or f"SIM-EGG-{uuid4().hex[:8].upper()}"
    views: list[ViewAssessment] = []
    for index in range(8):
        invalid = request.scenario == SimulatorScenario.BAD_CAPTURE and index < 4
        flags = [MachineFlag.IMAGE_TOO_DARK] if invalid else []
        descriptor = f"{inspection_id}:{index}:{request.scenario.value}:synthetic-no-image"
        views.append(
            ViewAssessment(
                view_index=index,
                angle_degrees=index * 45,
                quality_valid=not invalid,
                probabilities=_probabilities(request.scenario, index),
                flags=flags,
                image_sha256=hashlib.sha256(descriptor.encode()).hexdigest(),
                capture_ms=92 + index * 3,
                inference_ms=410 + index * 7,
            )
        )

    elapsed = request.recorded_elapsed_hours
    if request.scenario == SimulatorScenario.DAY_18 and elapsed == 384.0:
        elapsed = 432.0
    if request.scenario == SimulatorScenario.AGE_MISMATCH:
        elapsed = 384.0

    return InspectionIngest(
        inspection_id=inspection_id,
        device_id="SIM-ESP32-S3-01",
        batch_id="SIM-BATCH-001",
        egg_id=egg_id,
        recorded_elapsed_hours=elapsed,
        model_release_id="SIMULATOR_NO_CNN",
        threshold_profile_id="simulator-v1-unvalidated",
        firmware_version="simulator-0.1.0",
        schema_version="1.0.0",
        views=views,
        device_flags=(
            [MachineFlag.DEVICE_FAULT]
            if request.scenario == SimulatorScenario.DEVICE_FAULT
            else []
        ),
        captured_at=datetime.now(timezone.utc),
        is_simulated=True,
        authority=Authority.SHADOW_ONLY,
    )
