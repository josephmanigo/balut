#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "balut_types.h"

typedef struct {
    uint8_t min_valid_views;
    float min_confidence;
    float min_margin;
    float min_view_agreement;
    float day_16_min_hours;
    float day_16_max_hours;
    float day_18_min_hours;
    float day_18_max_hours;
} balut_thresholds_t;

typedef struct {
    uint8_t valid_views;
    float class_probabilities[3];
    float view_agreement;
    uint32_t quality_flags;
    bool recorded_age_available;
    float recorded_elapsed_hours;
} balut_aggregate_input_t;

balut_decision_t balut_decide(
    const balut_aggregate_input_t *input,
    const balut_thresholds_t *thresholds
);
