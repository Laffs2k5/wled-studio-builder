// SPDX-License-Identifier: EUPL-1.2
// The virtual WLED's wled.h: what WLED's effect engine needs, without the device.
//
// WLED's own wled.h pulls in the whole device (Wi-Fi, the web server, MQTT, file system). The
// effect engine (FX.cpp, FX_fcn.cpp, …), compiled unchanged from a checkout, includes this one
// instead: the Arduino basics (stub/), WLED's effect-side headers, and the globals the engine
// reads (globals.h, generated from WLED's wled.h by virtual_wled.py). Board flags such as
// USERMOD_AUDIOREACTIVE come from the build (the firmware's own compile command).
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#ifndef ARDUINO_ARCH_ESP32
#define ARDUINO_ARCH_ESP32
#endif
#ifndef ESP32
#define ESP32
#endif
// a virtual device has no network, remote, file editor or OTA: WLED's own switches turn their code
// off (none of them touches the effect engine, so the effect list is unchanged)
#define WLED_DISABLE_MQTT
#define WLED_DISABLE_ALEXA
#define WLED_DISABLE_HUESYNC
#define WLED_DISABLE_OTA
#define WLED_DISABLE_ADALIGHT
#define WLED_DISABLE_LOXONE
#define WLED_DISABLE_WEBSOCKETS
#define WLED_DISABLE_INFRARED
#define WLED_DISABLE_ESPNOW
#define WLED_DISABLE_FILESYSTEM_EDITOR
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
#define ARDUINOJSON_ENABLE_ARDUINO_STRING 1   // as on a device (ARDUINO is defined there)
#include "src/dependencies/json/ArduinoJson-v6.h"
#ifndef __time_t_defined
#define __time_t_defined   // the libc has time_t
#endif
#include "src/dependencies/time/TimeLib.h"
#include "src/dependencies/toki/Toki.h"
#include "const.h"
#include "colors.h"
#include "fcn_declare.h"
#include "pin_manager.h"
#include "bus_manager.h"
#include "FX.h"
#include "globals.h"
extern WS2812FX strip;

// Usermods register into a plain list: WLED's linker-section array has no WebAssembly equivalent.
namespace virtualwled { void register_usermod(Usermod* m); }
struct VirtualUsermodRegistrar { explicit VirtualUsermodRegistrar(Usermod* m) { virtualwled::register_usermod(m); } };
#undef REGISTER_USERMOD
#define REGISTER_USERMOD(x) static VirtualUsermodRegistrar _virtual_usermod_##x(&(x))
