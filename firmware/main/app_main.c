#include <stdbool.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "hardware_outputs.h"
#include "inspection_state_machine.h"
#include "safety_controller.h"

static const char *TAG = "balut_box";
static balut_safety_state_t safety_state;
static balut_inspection_machine_t inspection_machine;

static void safety_task(void *context) {
    (void)context;
    /* Unassigned inputs are represented as unsafe, keeping outputs latched off. */
    balut_safety_inputs_t inputs = {
        .lid_closed = false,
        .emergency_stop_released = false,
        .temperature_valid = false,
        .led_temperature_c = 0.0F,
        .watchdog_healthy = true,
        .driver_healthy = false,
    };

    while (true) {
        const uint32_t faults = balut_safety_evaluate(&safety_state, &inputs, 45.0F);
        if (faults != BALUT_FAULT_NONE || !balut_safety_can_energize(&safety_state)) {
            balut_outputs_force_off();
            balut_inspection_force_safe_stop(&inspection_machine);
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void dormant_subsystem_task(void *context) {
    const char *name = (const char *)context;
    ESP_LOGW(TAG, "%s task is a non-energizing scaffold; hardware integration is blocked", name);
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void app_main(void) {
    balut_outputs_init_off();
    balut_safety_init(&safety_state);
    balut_inspection_init(&inspection_machine);
    balut_inspection_force_safe_stop(&inspection_machine);

    ESP_LOGW(TAG, "SHADOW firmware started: motor and candle gates are compile-time disabled");
    xTaskCreatePinnedToCore(safety_task, "safety", 4096, NULL, 20, NULL, 0);
    xTaskCreate(dormant_subsystem_task, "motor", 3072, "motor", 16, NULL);
    xTaskCreate(dormant_subsystem_task, "capture", 4096, "capture", 14, NULL);
    xTaskCreate(dormant_subsystem_task, "inference", 4096, "inference", 12, NULL);
    xTaskCreate(dormant_subsystem_task, "display", 3072, "display", 10, NULL);
    xTaskCreate(dormant_subsystem_task, "persistence", 4096, "persistence", 9, NULL);
    xTaskCreate(dormant_subsystem_task, "upload", 4096, "upload", 5, NULL);
}
