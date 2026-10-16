idf_component_register(
  SRCS
    "app_main.c"
    "safety_controller.c"
    "inspection_state_machine.c"
    "decision_policy.c"
    "hardware_outputs.c"
    "model_release.c"
  INCLUDE_DIRS "include"
  REQUIRES driver esp_event esp_timer nvs_flash
)
