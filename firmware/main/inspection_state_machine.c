#include "inspection_state_machine.h"

#include <stddef.h>

static bool transition_allowed(balut_state_t current, balut_state_t next) {
    if (next == BALUT_STATE_SAFE_STOP) {
        return true;
    }

    switch (current) {
        case BALUT_STATE_BOOT_SELF_TEST:
            return next == BALUT_STATE_LID_OPEN || next == BALUT_STATE_READY;
        case BALUT_STATE_LID_OPEN:
            return next == BALUT_STATE_READY;
        case BALUT_STATE_READY:
            return next == BALUT_STATE_SHELL_CAPTURE || next == BALUT_STATE_CANDLE_CAPTURE;
        case BALUT_STATE_SHELL_CAPTURE:
            return next == BALUT_STATE_CANDLE_CAPTURE;
        case BALUT_STATE_CANDLE_CAPTURE:
            return next == BALUT_STATE_CANDLE_CAPTURE || next == BALUT_STATE_QUALITY_CHECK;
        case BALUT_STATE_QUALITY_CHECK:
            return next == BALUT_STATE_INFERENCE || next == BALUT_STATE_RESULT;
        case BALUT_STATE_INFERENCE:
            return next == BALUT_STATE_AGGREGATE;
        case BALUT_STATE_AGGREGATE:
            return next == BALUT_STATE_RESULT;
        case BALUT_STATE_RESULT:
            return next == BALUT_STATE_UPLOAD_PENDING;
        case BALUT_STATE_UPLOAD_PENDING:
            return next == BALUT_STATE_READY;
        case BALUT_STATE_SAFE_STOP:
            return next == BALUT_STATE_READY;
        default:
            return false;
    }
}

void balut_inspection_init(balut_inspection_machine_t *machine) {
    if (machine == NULL) {
        return;
    }
    machine->current = BALUT_STATE_BOOT_SELF_TEST;
    machine->capture_index = 0;
    machine->result_persisted = false;
}

bool balut_inspection_transition(balut_inspection_machine_t *machine, balut_state_t next) {
    if (machine == NULL || !transition_allowed(machine->current, next)) {
        return false;
    }

    if (machine->current == BALUT_STATE_SAFE_STOP && next == BALUT_STATE_READY) {
        machine->capture_index = 0;
        machine->result_persisted = false;
    }
    if (next == BALUT_STATE_CANDLE_CAPTURE && machine->capture_index < 8) {
        machine->capture_index += 1;
    }
    if (next == BALUT_STATE_RESULT) {
        machine->result_persisted = false;
    }
    machine->current = next;
    return true;
}

void balut_inspection_force_safe_stop(balut_inspection_machine_t *machine) {
    if (machine == NULL) {
        return;
    }
    machine->current = BALUT_STATE_SAFE_STOP;
    machine->result_persisted = false;
}
