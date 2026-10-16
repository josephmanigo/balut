#include <assert.h>
#include <stdio.h>

#include "decision_policy.h"
#include "safety_controller.h"

static const balut_thresholds_t THRESHOLDS = {
    .min_valid_views = 6,
    .min_confidence = 0.82F,
    .min_margin = 0.15F,
    .min_view_agreement = 0.625F,
    .day_16_min_hours = 372.0F,
    .day_16_max_hours = 396.0F,
    .day_18_min_hours = 420.0F,
    .day_18_max_hours = 444.0F,
};

static void test_safety_requires_fresh_acknowledgement(void) {
    balut_safety_state_t state;
    balut_safety_init(&state);
    balut_safety_inputs_t good = {
        .lid_closed = true,
        .emergency_stop_released = true,
        .temperature_valid = true,
        .led_temperature_c = 30.0F,
        .watchdog_healthy = true,
        .driver_healthy = true,
    };
    balut_safety_evaluate(&state, &good, 45.0F);
    assert(!balut_safety_can_energize(&state));
    assert(!balut_safety_acknowledge(&state, &good, 45.0F, false));
    assert(balut_safety_acknowledge(&state, &good, 45.0F, true));
    assert(balut_safety_can_energize(&state));

    good.lid_closed = false;
    balut_safety_evaluate(&state, &good, 45.0F);
    assert(!balut_safety_can_energize(&state));
    good.lid_closed = true;
    balut_safety_evaluate(&state, &good, 45.0F);
    assert(!balut_safety_can_energize(&state));
}

static void test_decision_abstains_on_age_mismatch(void) {
    balut_aggregate_input_t input = {
        .valid_views = 8,
        .class_probabilities = {0.91F, 0.05F, 0.04F},
        .view_agreement = 0.875F,
        .quality_flags = BALUT_FLAG_NONE,
        .recorded_age_available = true,
        .recorded_elapsed_hours = 432.0F,
    };
    const balut_decision_t decision = balut_decide(&input, &THRESHOLDS);
    assert(decision.outcome == BALUT_OUTCOME_REVIEW_RECAPTURE);
    assert((decision.flags & BALUT_FLAG_AGE_APPEARANCE_MISMATCH) != 0);
}

static void test_reject_has_only_model_suspect_flag(void) {
    balut_aggregate_input_t input = {
        .valid_views = 8,
        .class_probabilities = {0.03F, 0.04F, 0.93F},
        .view_agreement = 0.875F,
        .quality_flags = BALUT_FLAG_NONE,
        .recorded_age_available = false,
    };
    const balut_decision_t decision = balut_decide(&input, &THRESHOLDS);
    assert(decision.outcome == BALUT_OUTCOME_REJECT_SUSPECT);
    assert(decision.flags == BALUT_FLAG_MODEL_REJECT_SUSPECT);
}

int main(void) {
    test_safety_requires_fresh_acknowledgement();
    test_decision_abstains_on_age_mismatch();
    test_reject_has_only_model_suspect_flag();
    puts("firmware host logic tests passed");
    return 0;
}
