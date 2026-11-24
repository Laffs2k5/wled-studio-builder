// SPDX-License-Identifier: EUPL-1.2
// spike: what WLED's effect code needs, without the device (network, web server, files)
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#define ARDUINO_ARCH_ESP32
#define ESP32
#define CONFIG_IDF_TARGET_ESP32
#define USERMOD_AUDIOREACTIVE
#define BOARD_HAS_PSRAM
#define PROGMEM
#define IRAM_ATTR
#define WLED_GLOBAL extern
#define _INIT(x)
#define _INIT_N(x)
#define DEBUG_PRINT(x)
#define DEBUG_PRINTLN(x)
#define DEBUG_PRINTF(...)
#define DEBUG_PRINTF_P(...)
#define F(x) (x)
#define PSTR(x) (x)
#define FPSTR(x) (x)
#define pgm_read_byte(a) (*(const uint8_t*)(a))
#define pgm_read_word(a) (*(const uint16_t*)(a))
#define pgm_read_dword(a) (*(const uint32_t*)(a))
#define memcpy_P memcpy
#define strlen_P strlen
#define strncpy_P strncpy
#define strcmp_P strcmp
typedef uint8_t byte;
typedef bool boolean;
#include <Arduino.h>
uint32_t millis();
uint32_t micros();
class String;
#include "src/dependencies/json/ArduinoJson-v6.h"
#define __time_t_defined   // the libc has time_t (musl doesn't say so)
#include "src/dependencies/time/TimeLib.h"
#include "const.h"
#include "colors.h"
#include "fcn_declare.h"
#include "pin_manager.h"
#include "bus_manager.h"
#include "FX.h"
// the globals effect code reads (wled.h's WLED_GLOBALs)
#include "globals.h"
extern WS2812FX strip;
extern byte paletteBlend;
extern time_t localTime;
extern bool useAMPM;
