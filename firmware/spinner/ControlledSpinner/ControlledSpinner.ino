// Identified spinner only: same 18/21/19/22 phase order, 2048 steps/revolution, 10 RPM.
#include <Arduino.h>
#include <ctype.h>
#include <atomic>
#include <Wire.h>
#include <U8g2lib.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

static constexpr uint8_t PINS[] = {18, 21, 19, 22};
static constexpr uint8_t PHASES[4][4] = {{1, 0, 1, 0}, {0, 1, 1, 0}, {0, 1, 0, 1}, {1, 0, 0, 1}};
static constexpr uint32_t STEP_US = 60000000UL / 2048 / 10;
static bool held = false;
static uint8_t phase = 0;
static uint32_t lastStep = 0, holdUntil = 0, steps = 0;
// XFP1116-07AY: CH1116/SH1106-compatible 128x64 I2C OLED, SCL 26 and SDA 25.
static U8G2_SH1106_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE, 26, 25);
static QueueHandle_t lcdQueue;
static std::atomic<bool> lcdReady{false};
static const char *LCD_CODES[] = {"UNCLASSIFIED", "DAY_16", "DAY_18", "REJECT", "WAITING", "CAPTURING", "OFFLINE", "CALIBRATE"};
static const char *LCD_TEXT[] = {"Unclassified", "Day 16", "Day 18", "Reject", "Place egg", "Analyzing...", "Offline", "Save empty view"};
static std::atomic<uint8_t> displayed{0};

static bool oledResponds(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

static void displayTask(void *) {
  uint8_t code = 0, previous = 255;
  uint8_t address = 0;
  bool first = true;
  uint32_t received = millis();
  for (;;) {
    // A stopped connector must not leave a previous egg's classification on screen.
    if (xQueueReceive(lcdQueue, &code, pdMS_TO_TICKS(1000)) == pdTRUE) received = millis();
    if (static_cast<uint32_t>(millis() - received) >= 150000) code = 6;
    if (lcdReady && !oledResponds(address)) { lcdReady = false; previous = 255; }
    if (!lcdReady) {
      address = oledResponds(0x3c) ? 0x3c : oledResponds(0x3d) ? 0x3d : 0;
      if (address) {
        oled.setI2CAddress(address << 1);
        oled.setBusClock(100000);
        oled.begin();
        oled.setPowerSave(0);
        oled.setContrast(180);
        lcdReady = oledResponds(address);
        previous = 255;
      }
      if (address || first) Serial.printf("BALUT_OLED_INIT %s address=0x%02x sda=25 scl=26\n", lcdReady ? "READY" : "MISSING", address);
      first = false;
    }
    if (lcdReady && code != previous) {
      oled.clearBuffer();
      oled.setFont(u8g2_font_6x10_tr);
      oled.drawStr(6, 12, "EGGGRADE IOT");
      oled.drawHLine(0, 17, 128);
      oled.setFont(u8g2_font_helvB12_tr);
      oled.drawStr((128 - oled.getStrWidth(LCD_TEXT[code])) / 2, 41, LCD_TEXT[code]);
      oled.setFont(u8g2_font_6x10_tr);
      const char *hint = code >= 1 && code <= 3 ? "Research estimate" : code == 0 ? "Recapture / review" : "USB box display";
      oled.drawStr((128 - oled.getStrWidth(hint)) / 2, 61, hint);
      oled.sendBuffer();
      lcdReady = oledResponds(address);
      if (lcdReady) { displayed = code; previous = code; }
    }
  }
}

static void lcdStatus(const char *nonce, uint8_t code) {
  Serial.printf("BALUT_LCD_V1 %s %s label=%s\n", nonce, lcdReady ? "READY" : "MISSING", LCD_CODES[code]);
}

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
  if (strcmp(verb, "LCD") == 0) {
    char label[17];
    if (sscanf(line, "%7s %16s %16s %c", verb, nonce, label, &extra) != 3) return;
    for (uint8_t code = 0; code < sizeof(LCD_CODES) / sizeof(*LCD_CODES); ++code) {
      if (strcmp(label, LCD_CODES[code]) == 0) {
        if (lcdQueue) xQueueOverwrite(lcdQueue, &code);
        lcdStatus(nonce, code);
        return;
      }
    }
    return;
  }
  if (strcmp(verb, "LCDSTAT") == 0 && sscanf(line, "%7s %16s %c", verb, nonce, &extra) == 2) {
    lcdStatus(nonce, displayed);
    return;
  }
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
  // User wiring: SDA D25, SCL D26. Default I2C pins 21/22 already drive the spinner.
  Wire.begin(25, 26, 100000);
  Wire.setTimeOut(20);
  lcdQueue = xQueueCreate(1, sizeof(uint8_t));
  // I2C writes run on the other core so OLED refreshes do not delay motor steps.
  if (!lcdQueue || xTaskCreatePinnedToCore(displayTask, "oled", 4096, nullptr, 1, nullptr, 0) != pdPASS) Serial.println("BALUT_OLED_INIT MISSING task_failed");
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
