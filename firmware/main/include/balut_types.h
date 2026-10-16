#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    BALUT_OUTCOME_DAY_16_LIKE = 0,
    BALUT_OUTCOME_DAY_18_LIKE,
    BALUT_OUTCOME_REJECT_SUSPECT,
    BALUT_OUTCOME_REVIEW_RECAPTURE,
} balut_outcome_t;

typedef enum {
    BALUT_STATE_BOOT_SELF_TEST = 0,
    BALUT_STATE_LID_OPEN,
    BALUT_STATE_READY,
    BALUT_STATE_SHELL_CAPTURE,
    BALUT_STATE_CANDLE_CAPTURE,
    BALUT_STATE_QUALITY_CHECK,
    BALUT_STATE_INFERENCE,
    BALUT_STATE_AGGREGATE,
    BALUT_STATE_RESULT,
    BALUT_STATE_UPLOAD_PENDING,
    BALUT_STATE_SAFE_STOP,
} balut_state_t;

typedef enum {
    BALUT_FLAG_NONE = 0,
    BALUT_FLAG_IMAGE_TOO_DARK = 1U << 0,
    BALUT_FLAG_IMAGE_SATURATED = 1U << 1,
    BALUT_FLAG_IMAGE_BLURRED = 1U << 2,
    BALUT_FLAG_EGG_NOT_FOUND = 1U << 3,
    BALUT_FLAG_INCOMPLETE_ROTATION = 1U << 4,
    BALUT_FLAG_VIEW_DISAGREEMENT = 1U << 5,
    BALUT_FLAG_LOW_CONFIDENCE = 1U << 6,
    BALUT_FLAG_AGE_APPEARANCE_MISMATCH = 1U << 7,
    BALUT_FLAG_DEVICE_FAULT = 1U << 8,
    BALUT_FLAG_MODEL_REJECT_SUSPECT = 1U << 9,
} balut_machine_flag_t;

typedef struct {
    balut_outcome_t outcome;
    float confidence;
    float class_margin;
    float view_agreement;
    uint8_t valid_views;
    uint32_t flags;
} balut_decision_t;
