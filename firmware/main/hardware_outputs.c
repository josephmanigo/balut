#include "hardware_outputs.h"

#include "board_config.h"
#include "driver/gpio.h"

static bool motor_enabled = false;
static bool candle_enabled = false;

static void configure_gate_if_present(gpio_num_t pin) {
    if (pin == GPIO_NUM_NC) {
        return;
    }
    gpio_set_level(pin, BALUT_GATE_DISABLED_LEVEL);
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&config);
    gpio_set_level(pin, BALUT_GATE_DISABLED_LEVEL);
}

void balut_outputs_init_off(void) {
    motor_enabled = false;
    candle_enabled = false;
    configure_gate_if_present(BALUT_PIN_MOTOR_GATE);
    configure_gate_if_present(BALUT_PIN_CANDLE_GATE);
}

void balut_outputs_force_off(void) {
    motor_enabled = false;
    candle_enabled = false;
    if (BALUT_PIN_MOTOR_GATE != GPIO_NUM_NC) {
        gpio_set_level(BALUT_PIN_MOTOR_GATE, BALUT_GATE_DISABLED_LEVEL);
    }
    if (BALUT_PIN_CANDLE_GATE != GPIO_NUM_NC) {
        gpio_set_level(BALUT_PIN_CANDLE_GATE, BALUT_GATE_DISABLED_LEVEL);
    }
}

static bool request_gate(gpio_num_t pin, bool enable, bool safety_allows, bool *state) {
    if (!enable) {
        if (pin != GPIO_NUM_NC) {
            gpio_set_level(pin, BALUT_GATE_DISABLED_LEVEL);
        }
        *state = false;
        return true;
    }
#if BALUT_HARDWARE_ENERGIZING_BUILD
    if (pin != GPIO_NUM_NC && safety_allows) {
        gpio_set_level(pin, BALUT_GATE_ENABLED_LEVEL);
        *state = true;
        return true;
    }
#else
    (void)pin;
    (void)safety_allows;
#endif
    *state = false;
    return false;
}

bool balut_outputs_request_motor(bool enable, bool safety_allows) {
    if (enable && candle_enabled) {
        return false;
    }
    return request_gate(BALUT_PIN_MOTOR_GATE, enable, safety_allows, &motor_enabled);
}

bool balut_outputs_request_candle(bool enable, bool safety_allows) {
    if (enable && motor_enabled) {
        return false;
    }
    return request_gate(BALUT_PIN_CANDLE_GATE, enable, safety_allows, &candle_enabled);
}

bool balut_outputs_are_off(void) {
    return !motor_enabled && !candle_enabled;
}
