#pragma once

#include <stdbool.h>

#include "balut_types.h"

typedef struct {
    balut_state_t current;
    uint8_t capture_index;
    bool result_persisted;
} balut_inspection_machine_t;

void balut_inspection_init(balut_inspection_machine_t *machine);
bool balut_inspection_transition(balut_inspection_machine_t *machine, balut_state_t next);
void balut_inspection_force_safe_stop(balut_inspection_machine_t *machine);
