// Identified spinner only: same 18/21/19/22 phase order, 2048 steps/revolution, 10 RPM.
#include <Arduino.h>
#include <ctype.h>

static constexpr uint8_t PINS[] = {18, 21, 19, 22};
static constexpr uint8_t PHASES[4][4] = {{1, 0, 1, 0}, {0, 1, 1, 0}, {0, 1, 0, 1}, {1, 0, 0, 1}};
static constexpr uint32_t STEP_US = 60000000UL / 2048 / 10;
static bool held = false;
static uint8_t phase = 0;
static uint32_t lastStep = 0, holdUntil = 0, steps = 0;

static void status(const char *nonce) {
  uint64_t mac = ESP.getEfuseMac();
  const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&mac);
  Serial.printf("BALUT_MOTOR_V1 %s %s steps=%lu mac=", nonce, held ? "HELD" : "RUNNING", static_cast<unsigned long>(steps));
  for (unsigned i = 0; i < 6; ++i) Serial.printf(i ? ":%02x" : "%02x", bytes[i]);
  Serial.println();
}

static void command(char *line) {
  char verb[8], nonce[17], extra;
  unsigned duration = 0;
  if (sscanf(line, "%7s %16s", verb, nonce) != 2 || strlen(nonce) != 16) return;
  for (const char *p = nonce; *p; ++p) if (!isxdigit(static_cast<unsigned char>(*p))) return;
  if (strcmp(verb, "HOLD") == 0 && sscanf(line, "%7s %16s %u %c", verb, nonce, &duration, &extra) == 3 && duration >= 100 && duration <= 12000) {
    held = true;
    holdUntil = millis() + duration;
  } else if (strcmp(verb, "RUN") == 0 && sscanf(line, "%7s %16s %c", verb, nonce, &extra) == 2) {
    held = false;
    lastStep = micros();
  } else if (strcmp(verb, "STATUS") != 0 || sscanf(line, "%7s %16s %c", verb, nonce, &extra) != 2) {
    return;
  }
  status(nonce);
}

void setup() {
  Serial.begin(115200);
  for (uint8_t pin : PINS) { digitalWrite(pin, LOW); pinMode(pin, OUTPUT); }
  lastStep = micros();
  Serial.println("BALUT_SPINNER_READY_V1");
}

void loop() {
  static char line[80];
  static size_t used = 0;
  static bool overflow = false;
  while (Serial.available()) {
    const char next = static_cast<char>(Serial.read());
    if (next == '\n') {
      if (!overflow) { line[used] = '\0'; command(line); }
      used = 0; overflow = false;
    } else if (next != '\r') {
      if (used < sizeof(line) - 1) line[used++] = next;
      else overflow = true;
    }
  }
  if (held && static_cast<int32_t>(millis() - holdUntil) >= 0) {
    held = false;
    lastStep = micros();
    Serial.println("BALUT_SPINNER_AUTO_RESUME");
  }
  const uint32_t now = micros();
  if (!held && static_cast<uint32_t>(now - lastStep) >= STEP_US) {
    lastStep = now;
    phase = (phase + 1) % 4;
    for (unsigned i = 0; i < 4; ++i) digitalWrite(PINS[i], PHASES[phase][i]);
    ++steps;
  }
  // Keep the current coil phase while held; the candling light is not controlled here.
  delayMicroseconds(50);
}
