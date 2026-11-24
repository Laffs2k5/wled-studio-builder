// SPDX-License-Identifier: EUPL-1.2
// The virtual WLED's C API for JavaScript. The preview_* functions are the effect preview's
// (preview/shim), so the same tests run against WLED's real engine; virtual_* are its own.
#include "wled.h"
#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#define EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define EXPORT extern "C"
#endif
#include <string>

namespace virtualwled {
extern uint32_t now_ms;
extern float level;
extern std::vector<uint32_t> frame;
std::vector<Usermod*>& usermods();
static bool booted = false;
static std::string scratch;
}  // namespace virtualwled
using namespace virtualwled;

/** Boot as WLED does (WLED::beginStrip and its config load): the gamma tables, one bus of
 *  `leds` LEDs, segment 0 over all of them, the usermods. Again with another length: the strip
 *  is rebuilt. */
EXPORT int virtual_boot(int leds, int rgbw, float gamma) {
  NeoGammaWLEDMethod::calcGammaTable(gamma > 0.1f && gamma <= 3.0f ? gamma : 2.2f);
  strip.setTransition(0);
  BusManager::removeAll();
  uint8_t pins[1] = {2};
  busConfigs.emplace_back(rgbw ? TYPE_SK6812_RGBW : TYPE_WS2812_RGB, pins, 0, uint16_t(leds > 0 ? leds : 1));
  strip.finalizeInit();
  strip.makeAutoSegments(true);
  strip.setBrightness(255);
  strip.setTargetFps(FPS_UNLIMITED);   // a frame each time the API asks for one
  strip.timebase = 0UL - 1000UL;       // the effects' time (strip.now) is the API's: see millis() in glue.cpp
  bri = 255;
  if (!booted) {
    for (Usermod* m : usermods()) m->setup();
    booted = true;
  }
  strip.getSegment(0).setColor(0, RGBW32(255, 160, 0, 0));   // WLED's default orange
  return strip.getLengthTotal();
}

// --- the effect preview's API ---------------------------------------------------------------
EXPORT void preview_setup(int length) { virtual_boot(length, 1, 2.2f); }
EXPORT int preview_effect_count() { return strip.getModeCount(); }
EXPORT const char* preview_effect_name(int id) {
  scratch = (id >= 0 && id < strip.getModeCount()) ? strip.getModeData(id) : "";
  scratch = scratch.substr(0, scratch.find('@'));
  return scratch.c_str();
}
EXPORT const char* preview_effect_metadata(int id) {
  scratch = (id >= 0 && id < strip.getModeCount()) ? strip.getModeData(id) : "";
  auto at = scratch.find('@');
  scratch = at == std::string::npos ? "" : scratch.substr(at + 1);
  return scratch.c_str();
}
EXPORT int preview_select(int id) {
  if (id < 0 || id >= strip.getModeCount()) return -1;
  strip.getSegment(0).setMode(id, true);   // with the effect's defaults, as WLED's UI does
  return id;
}
EXPORT void preview_set(int key, int value) {
  Segment& seg = strip.getSegment(0);
  uint8_t v = uint8_t(value);
  switch (key) {
    case 0: seg.speed = v; break;       case 1: seg.intensity = v; break;
    case 2: seg.custom1 = v; break;     case 3: seg.custom2 = v; break;
    case 4: seg.custom3 = v & 31; break;
    case 5: seg.check1 = value; break;  case 6: seg.check2 = value; break;  case 7: seg.check3 = value; break;
    case 8: seg.setPalette(v); break;
    case 9: case 10: case 11: seg.setColor(key - 9, uint32_t(value)); break;
    case 12: seg.soundSim = v & 3; break;
  }
}
EXPORT int preview_length() { return strip.getLengthTotal(); }
static std::vector<uint32_t> shown;
/** Runs one frame at `ms`; returns the LEDs' colours as the effects made them (0xWWRRGGBB): WLED's
 *  own pixel buffer, as its live view reads it, before the bus applies brightness and gamma. */
EXPORT uint32_t* preview_frame(uint32_t ms) {
  now_ms = ms;
  strip.service();
  shown.resize(strip.getLengthTotal());
  for (size_t i = 0; i < shown.size(); i++) shown[i] = strip.getPixelColor(i);
  return shown.data();
}
/** What the bus sent to the LEDs at the last frame: after brightness and gamma, as on the strip. */
EXPORT uint32_t* virtual_output() { return frame.data(); }
EXPORT void preview_audio(float lvl) { level = lvl; }
EXPORT const char* preview_palette_names() { return JSON_palette_names; }
