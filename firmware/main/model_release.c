#include "model_release.h"

#include <string.h>

static const char *EXPECTED_CLASSES[3] = {
    "DAY_16_LIKE",
    "DAY_18_LIKE",
    "REJECT_SUSPECT",
};

bool balut_model_manifest_validate(
    const balut_model_manifest_t *manifest,
    const char *calculated_sha256,
    size_t slot_capacity_bytes
) {
    if (manifest == NULL || calculated_sha256 == NULL || manifest->release_id == NULL ||
        manifest->sha256 == NULL || manifest->quality_gate_version == NULL ||
        manifest->threshold_version == NULL) {
        return false;
    }
    if (manifest->input_width == 0 || manifest->input_height == 0 ||
        manifest->model_size_bytes == 0 || manifest->model_size_bytes > slot_capacity_bytes) {
        return false;
    }
    if (strcmp(manifest->sha256, calculated_sha256) != 0) {
        return false;
    }
    for (size_t index = 0; index < 3; index += 1) {
        if (manifest->class_order[index] == NULL ||
            strcmp(manifest->class_order[index], EXPECTED_CLASSES[index]) != 0) {
            return false;
        }
    }
    return true;
}
