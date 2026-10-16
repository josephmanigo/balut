#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    BALUT_FAULT_NONE = 0,
    BALUT_FAULT_LID_OPEN = 1U << 0,
    BALUT_FAULT_ESTOP = 1U << 1,
    BALUT_FAULT_OVERTEMPERATURE = 1U << 2,
    BALUT_FAULT_WATCHDOG = 1U << 3,
    BALUT_FAULT_DRIVER = 1U << 4,
    BALUT_FAULT_SENSOR_INVALID = 1U << 5,
} balut_fault_t;

typedef struct {
    bool lid_closed;
    bool emergency_stop_released;
    bool temperature_valid;
    float led_temperature_c;
    bool watchdog_healthy;
    bool driver_healthy;
} balut_safety_inputs_t;

typedef struct {
    bool safe_stop_latched;
    uint32_t active_faults;
    uint32_t latched_faults;
    uint32_t latch_generation;
} balut_safety_state_t;

void balut_safety_init(balut_safety_state_t *state);
uint32_t balut_safety_evaluate(
    balut_safety_state_t *state,
    const balut_safety_inputs_t *inputs,
    float max_led_temperature_c
);
bool balut_safety_can_energize(const balut_safety_state_t *state);
bool balut_safety_acknowledge(
    balut_safety_state_t *state,
    const balut_safety_inputs_t *inputs,
    float max_led_temperature_c,
    bool explicit_acknowledgement
);
