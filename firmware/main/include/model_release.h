#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    const char *release_id;
    const char *sha256;
    uint16_t input_width;
    uint16_t input_height;
    const char *color_order;
    const char *class_order[3];
    const char *quality_gate_version;
    const char *threshold_version;
    const char *firmware_min;
    const char *firmware_max;
    size_t model_size_bytes;
} balut_model_manifest_t;

bool balut_model_manifest_validate(
    const balut_model_manifest_t *manifest,
    const char *calculated_sha256,
    size_t slot_capacity_bytes
);
