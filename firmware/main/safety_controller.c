#include "safety_controller.h"

#include <stddef.h>

static uint32_t calculate_faults(
    const balut_safety_inputs_t *inputs,
    float max_led_temperature_c
) {
    if (inputs == NULL) {
        return BALUT_FAULT_SENSOR_INVALID;
    }

    uint32_t faults = BALUT_FAULT_NONE;
    if (!inputs->lid_closed) {
        faults |= BALUT_FAULT_LID_OPEN;
    }
    if (!inputs->emergency_stop_released) {
        faults |= BALUT_FAULT_ESTOP;
    }
    if (!inputs->temperature_valid || inputs->led_temperature_c > max_led_temperature_c) {
        faults |= BALUT_FAULT_OVERTEMPERATURE;
    }
    if (!inputs->watchdog_healthy) {
        faults |= BALUT_FAULT_WATCHDOG;
    }
    if (!inputs->driver_healthy) {
        faults |= BALUT_FAULT_DRIVER;
    }
    return faults;
}

void balut_safety_init(balut_safety_state_t *state) {
    if (state == NULL) {
        return;
    }
    state->safe_stop_latched = true;
    state->active_faults = BALUT_FAULT_SENSOR_INVALID;
    state->latched_faults = BALUT_FAULT_SENSOR_INVALID;
    state->latch_generation = 1;
}

uint32_t balut_safety_evaluate(
    balut_safety_state_t *state,
    const balut_safety_inputs_t *inputs,
    float max_led_temperature_c
) {
    if (state == NULL) {
        return BALUT_FAULT_SENSOR_INVALID;
    }

    state->active_faults = calculate_faults(inputs, max_led_temperature_c);
    if (state->active_faults != BALUT_FAULT_NONE) {
        const bool newly_latched = !state->safe_stop_latched;
        state->safe_stop_latched = true;
        state->latched_faults |= state->active_faults;
        if (newly_latched) {
            state->latch_generation += 1;
        }
    }
    return state->active_faults;
}

bool balut_safety_can_energize(const balut_safety_state_t *state) {
    return state != NULL && !state->safe_stop_latched && state->active_faults == BALUT_FAULT_NONE;
}

bool balut_safety_acknowledge(
    balut_safety_state_t *state,
    const balut_safety_inputs_t *inputs,
    float max_led_temperature_c,
    bool explicit_acknowledgement
) {
    if (state == NULL || !explicit_acknowledgement) {
        return false;
    }

    const uint32_t current_faults = calculate_faults(inputs, max_led_temperature_c);
    state->active_faults = current_faults;
    if (current_faults != BALUT_FAULT_NONE) {
        state->latched_faults |= current_faults;
        state->safe_stop_latched = true;
        return false;
    }

    state->safe_stop_latched = false;
    state->latched_faults = BALUT_FAULT_NONE;
    return true;
}
