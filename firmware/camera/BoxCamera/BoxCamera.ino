// AI-Thinker ESP32-CAM USB snapshots. Motor and illumination belong to the separate board.
// Camera pin mapping: Espressif arduino-esp32 CameraWebServer, CAMERA_MODEL_AI_THINKER.
#include <Arduino.h>
#include "esp_camera.h"
#include "esp_rom_crc.h"
#include "img_converters.h"

static bool cameraReady = false;
static constexpr unsigned long USB_BAUD = 921600;

static bool jpegData(camera_fb_t *frame, uint8_t **data, size_t *length) {
  if (!frame) return false;
  if (frame->format == PIXFORMAT_JPEG) {
    *data = frame->buf;
    *length = frame->len;
  } else {
    if (frame->format != PIXFORMAT_RGB565 || frame->len != frame->width * frame->height * 2) return false;
    if (!frame2jpg(frame, 90, data, length)) return false;
  }
  return *data && *length > 4 && (*data)[0] == 0xff && (*data)[1] == 0xd8;
}

static void captureUsb() {
  if (!cameraReady) {
    Serial.println("BALUT_ERROR Camera unavailable");
    return;
  }
  camera_fb_t *frame = esp_camera_fb_get();
  uint8_t *jpeg = nullptr;
  size_t length = 0;
  if (!jpegData(frame, &jpeg, &length)) {
    if (frame && frame->format != PIXFORMAT_JPEG) free(jpeg);
    if (frame) esp_camera_fb_return(frame);
    Serial.println("BALUT_ERROR Capture failed");
    return;
  }
  uint32_t checksum = esp_rom_crc32_le(0, jpeg, length);
  Serial.printf("BALUT_JPEG %u %08lx\n", static_cast<unsigned>(length), static_cast<unsigned long>(checksum));
  Serial.write(jpeg, length);
  Serial.write('\n');
  Serial.flush();
  if (frame->format != PIXFORMAT_JPEG) free(jpeg);
  esp_camera_fb_return(frame);
}

void setup() {
  Serial.begin(USB_BAUD);
  Serial.println("\nBalut USB camera: camera only, no motor or light control.");
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5;
  config.pin_d1 = 18;
  config.pin_d2 = 19;
  config.pin_d3 = 21;
  config.pin_d4 = 36;
  config.pin_d5 = 39;
  config.pin_d6 = 34;
  config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sccb_sda = 26;
  config.pin_sccb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;
  // GC2145 on the original ESP32 needs the driver's low-speed byte sampling.
  config.xclk_freq_hz = 10000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t error = esp_camera_init(&config);
  if (error == ESP_ERR_NOT_SUPPORTED) {
    Serial.println("Native JPEG unavailable; using RGB565 capture and JPEG conversion.");
    config.pixel_format = PIXFORMAT_RGB565;
    // GC2145 SVGA samples the full sensor; VGA uses a narrower center window.
    config.frame_size = FRAMESIZE_SVGA;
    config.fb_count = 1;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    error = esp_camera_init(&config);
  }
  if (error != ESP_OK) {
    Serial.printf("Camera initialization failed: 0x%x\n", error);
    return;
  }
  sensor_t *sensor = esp_camera_sensor_get();
  Serial.printf("Sensor PID: 0x%04x; PSRAM: %s; frame format: %d\n", sensor->id.PID, psramFound() ? "present" : "absent", config.pixel_format);
  // Discard startup frames while the sensor's exposure settles.
  for (int i = 0; i < 6; ++i) {
    camera_fb_t *warmup = esp_camera_fb_get();
    if (!warmup) {
      Serial.println("Camera warmup failed.");
      return;
    }
    esp_camera_fb_return(warmup);
    delay(30);
  }
  // Fail before serving if the sensor cannot produce an actual JPEG.
  camera_fb_t *test = esp_camera_fb_get();
  uint8_t *testJpeg = nullptr;
  size_t testLength = 0;
  cameraReady = jpegData(test, &testJpeg, &testLength);
  if (test && test->format != PIXFORMAT_JPEG) free(testJpeg);
  if (test) esp_camera_fb_return(test);
  if (!cameraReady) {
    Serial.println("Camera self-check failed; no image server started.");
    return;
  }
  Serial.println("BALUT_USB_READY");
}

void loop() {
  static char command[16];
  static size_t used = 0;
  while (Serial.available()) {
    char next = static_cast<char>(Serial.read());
    if (next == '\n') {
      command[used] = '\0';
      if (strcmp(command, "CAPTURE") == 0) {
        captureUsb();
      }
      used = 0;
    } else if (next != '\r' && used < sizeof(command) - 1) {
      command[used++] = next;
    }
  }
  delay(10);
}
