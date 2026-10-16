#pragma once

#include <stdbool.h>

void balut_outputs_init_off(void);
void balut_outputs_force_off(void);
bool balut_outputs_request_motor(bool enable, bool safety_allows);
bool balut_outputs_request_candle(bool enable, bool safety_allows);
bool balut_outputs_are_off(void);
