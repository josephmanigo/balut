#pragma once

#include "driver/gpio.h"

/*
 * Board-specific wiring is intentionally unassigned. GPIO_NUM_NC means no
 * physical output will be configured by this scaffold.
 */
#define BALUT_PIN_MOTOR_GATE GPIO_NUM_NC
#define BALUT_PIN_CANDLE_GATE GPIO_NUM_NC
#define BALUT_PIN_SHELL_LIGHT_GATE GPIO_NUM_NC
#define BALUT_PIN_LID_SENSE GPIO_NUM_NC
#define BALUT_PIN_ESTOP_SENSE GPIO_NUM_NC
#define BALUT_PIN_EGG_PRESENT GPIO_NUM_NC
#define BALUT_PIN_HALL_HOME GPIO_NUM_NC

/* Must remain 0 until schematic and bench approval. */
#define BALUT_HARDWARE_ENERGIZING_BUILD 0

#if BALUT_HARDWARE_ENERGIZING_BUILD && \
    (BALUT_PIN_MOTOR_GATE == GPIO_NUM_NC || BALUT_PIN_CANDLE_GATE == GPIO_NUM_NC)
#error "Energizing build requires explicit, reviewed gate pin assignments."
#endif

/* External gate command convention: 0 = disabled, 1 = enable requested. */
#define BALUT_GATE_DISABLED_LEVEL 0
#define BALUT_GATE_ENABLED_LEVEL 1
