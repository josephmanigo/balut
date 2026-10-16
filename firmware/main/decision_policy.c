#include "decision_policy.h"

#include <stddef.h>

static uint8_t top_index(const float probabilities[3]) {
    uint8_t best = 0;
    for (uint8_t index = 1; index < 3; index += 1) {
        if (probabilities[index] > probabilities[best]) {
            best = index;
        }
    }
    return best;
}

static float second_probability(const float probabilities[3], uint8_t best) {
    float second = 0.0F;
    for (uint8_t index = 0; index < 3; index += 1) {
        if (index != best && probabilities[index] > second) {
            second = probabilities[index];
        }
    }
    return second;
}

static bool age_matches(const balut_aggregate_input_t *input, const balut_thresholds_t *thresholds, uint8_t best) {
    if (!input->recorded_age_available || best == 2) {
        return true;
    }
    if (best == 0) {
        return input->recorded_elapsed_hours >= thresholds->day_16_min_hours &&
               input->recorded_elapsed_hours <= thresholds->day_16_max_hours;
    }
    return input->recorded_elapsed_hours >= thresholds->day_18_min_hours &&
           input->recorded_elapsed_hours <= thresholds->day_18_max_hours;
}

balut_decision_t balut_decide(
    const balut_aggregate_input_t *input,
    const balut_thresholds_t *thresholds
) {
    balut_decision_t decision = {
        .outcome = BALUT_OUTCOME_REVIEW_RECAPTURE,
        .confidence = 0.0F,
        .class_margin = 0.0F,
        .view_agreement = 0.0F,
        .valid_views = 0,
        .flags = BALUT_FLAG_DEVICE_FAULT,
    };
    if (input == NULL || thresholds == NULL) {
        return decision;
    }

    decision.valid_views = input->valid_views;
    decision.view_agreement = input->view_agreement;
    decision.flags = input->quality_flags;
    const uint8_t best = top_index(input->class_probabilities);
    decision.confidence = input->class_probabilities[best];
    decision.class_margin = decision.confidence - second_probability(input->class_probabilities, best);

    if (input->valid_views < thresholds->min_valid_views) {
        decision.flags |= BALUT_FLAG_INCOMPLETE_ROTATION;
        return decision;
    }
    if (decision.confidence < thresholds->min_confidence || decision.class_margin < thresholds->min_margin) {
        decision.flags |= BALUT_FLAG_LOW_CONFIDENCE;
        return decision;
    }
    if (input->view_agreement < thresholds->min_view_agreement) {
        decision.flags |= BALUT_FLAG_VIEW_DISAGREEMENT;
        return decision;
    }
    if (!age_matches(input, thresholds, best)) {
        decision.flags |= BALUT_FLAG_AGE_APPEARANCE_MISMATCH;
        return decision;
    }

    if (best == 0) {
        decision.outcome = BALUT_OUTCOME_DAY_16_LIKE;
    } else if (best == 1) {
        decision.outcome = BALUT_OUTCOME_DAY_18_LIKE;
    } else {
        decision.outcome = BALUT_OUTCOME_REJECT_SUSPECT;
        decision.flags |= BALUT_FLAG_MODEL_REJECT_SUSPECT;
    }
    return decision;
}
