// SPDX-License-Identifier: EUPL-1.2
// The virtual WLED as a device: WLED's loop, its JSON state API and its files, for the device
// server (virtual/server). Ours, not WLED's code: it calls WLED's own functions (json.cpp's
// deserializeState and serializeState, presets.cpp, playlist.cpp, led.cpp) the way WLED's web
// server and loop do.
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
std::vector<Usermod*>& usermods();
}  // namespace virtualwled
using namespace virtualwled;

static std::string out;            // the last JSON answer
static std::vector<uint8_t> live;  // the last live-view frame

/** Boot as WLED does with a saved config: one bus per length (in order, as the LED settings
 *  list them), then WLED::beginStrip: its automatic segment, the boot brightness, the boot
 *  preset or the default orange, the default transition. `lengths` is a comma-separated list,
 *  e.g. "124,126". */
EXPORT int virtual_device_boot(const char* lengths, int rgbw, int boot_preset) {
  if (pDoc == nullptr) pDoc = new DynamicJsonDocument(2 * JSON_BUFFER_SIZE);   // wled.cpp, with PSRAM
  NeoGammaWLEDMethod::calcGammaTable(gammaCorrectVal);
  BusManager::removeAll();
  uint8_t pins[1] = {2};
  uint16_t start = 0;
  for (const char* p = lengths; p && *p;) {
    int n = atoi(p);
    if (n > 0) {
      busConfigs.emplace_back(rgbw ? TYPE_SK6812_RGBW : TYPE_WS2812_RGB, pins, start, uint16_t(n));
      start += n;
    }
    p = strchr(p, ',');
    if (p) p++;
  }
  if (busConfigs.empty()) busConfigs.emplace_back(rgbw ? TYPE_SK6812_RGBW : TYPE_WS2812_RGB, pins, 0, uint16_t(30));
  static bool started = false;
  if (!started) {
    for (Usermod* m : usermods()) m->setup();
    started = true;
  }
  // WLED::beginStrip, without its relay and button
  strip.setTransition(0);
  strip.finalizeInit();
  strip.makeAutoSegments();
  strip.setBrightness(0);
  offMode = false;
  bri = 0;
  if (turnOnAtBoot) bri = briS;
  else briLast = briS;
  colorUpdated(CALL_MODE_INIT);
  bootPreset = uint8_t(boot_preset);
  if (bootPreset > 0) {
    applyPreset(bootPreset, CALL_MODE_INIT);
  } else {
    colPri[0] = R(DEFAULT_COLOR);
    colPri[1] = G(DEFAULT_COLOR);
    colPri[2] = B(DEFAULT_COLOR);
    colPri[3] = W(DEFAULT_COLOR);
  }
  strip.setTransition(transitionDelayDefault);
  colorUpdated(CALL_MODE_INIT);
  return strip.getLengthTotal();
}

/** One pass of WLED's loop (WLED::loop) at `ms`: transitions, usermods, nightlight, playlists,
 *  presets, and a frame when one is due. */
EXPORT void virtual_loop(uint32_t ms) {
  now_ms = ms;
  handleTransitions();
  for (Usermod* m : usermods()) m->loop();
  handleNightlight();
  if (!presetNeedsSaving()) handlePlaylist();
  handlePresets();
  if (!offMode || strip.isOffRefreshRequired() || strip.needsUpdate()) strip.service();
}

/** WLED's JSON answers, as text: 0 /json/state, 1 /json/eff, 2 /json/fxdata. nullptr when the
 *  JSON buffer is busy (WLED then answers {"error":3}). */
EXPORT const char* virtual_json(int what) {
  if (!requestJSONBufferLock(JSON_LOCK_SERVEJSON)) return nullptr;
  out.clear();
  if (what == 0) {
    JsonObject root = pDoc->to<JsonObject>();
    serializeState(root);
  } else if (what == 1) {
    JsonArray arr = pDoc->to<JsonArray>();
    serializeModeNames(arr);
  } else {
    // respondModeData: each effect with data, the part after its name's '@'
    JsonArray arr = pDoc->to<JsonArray>();
    for (size_t i = 0; i < strip.getModeCount(); i++) {
      const char* d = strip.getModeData(i);
      if (!d || !*d) continue;
      const char* at = strchr(d, '@');
      arr.add(at ? at + 1 : "");
    }
  }
  serializeJson(*pDoc, out);
  releaseJSONBufferLock();
  return out.c_str();
}

/** WLED's POST /json/state: 1 applied and WLED answers with the state ("v"), 0 applied, -1 not
 *  a JSON object (WLED: 400, error 9), -2 the JSON buffer is busy (error 3). The settings PIN
 *  is the server's: it removes "pin" before calling this. */
EXPORT int virtual_post_state(const char* body) {
  if (!requestJSONBufferLock(JSON_LOCK_SERVER)) return -2;
  DeserializationError error = deserializeJson(*pDoc, body);
  JsonObject root = pDoc->as<JsonObject>();
  if (error || root.isNull()) {
    releaseJSONBufferLock();
    return -1;
  }
  bool verbose = deserializeState(root);
  releaseJSONBufferLock();
  if (verbose) interfaceUpdateCallMode = CALL_MODE_WS_SEND;   // as wled_server.cpp: a push follows
  return verbose ? 1 : 0;
}

namespace virtualwled { extern uint32_t ws_pushes; }
/** How many times WLED has pushed its state to the websocket clients (led.cpp's
 *  updateInterfaces calls sendDataWs): the server sends state and info when this changes. */
EXPORT uint32_t virtual_ws_pushes() { return ws_pushes; }

/** The live view as WLED's websocket sends it (ws.cpp, sendLiveLedsWs): 'L', version 1, then RGB
 *  per LED (white added in), every n-th LED above 1024; all black while off. */
EXPORT const uint8_t* virtual_live(int* len) {
  size_t used = strip.getLengthTotal();
  size_t n = ((used - 1) / 1024) + 1;
  live.assign(2, 0);
  live[0] = 'L';
  live[1] = 1;
  for (size_t i = 0; i < used; i += n) {
    uint32_t c = strip.getPixelColor(i);
    uint8_t w = W(c);
    live.push_back(bri ? qadd8(w, R(c)) : 0);
    live.push_back(bri ? qadd8(w, G(c)) : 0);
    live.push_back(bri ? qadd8(w, B(c)) : 0);
  }
  *len = int(live.size());
  return live.data();
}

// --- files: WLED's file system (an in-memory one) ---------------------------------------------

/** A file upload, as WLED's /upload handles one (wled_server.cpp, handleUpload): the file is
 *  written; presets.json marks the presets changed, a palette file reloads the palettes. */
EXPORT int virtual_file_write(const char* name, const uint8_t* data, int len) {
  std::string p = name[0] == '/' ? name : std::string("/") + name;
  File f = WLED_FS.open(p.c_str(), "w");
  if (!f) return -1;
  f.write(data, size_t(len));
  f.close();
  if (p == "/presets.json") presetsModifiedTime = toki.second();
  if (p.find("palette") != std::string::npos && p.size() > 5 && p.compare(p.size() - 5, 5, ".json") == 0)
    loadCustomPalettes();
  cacheInvalidate++;
  updateFSInfo();
  return len;
}

/** A file's content, or nullptr when there is no such file. */
EXPORT const char* virtual_file_read(const char* name, int* len) {
  std::string p = name[0] == '/' ? name : std::string("/") + name;
  auto it = LittleFS.files.find(p);
  if (it == LittleFS.files.end()) return nullptr;
  *len = int(it->second->size());
  return it->second->data();
}

/** The file names, one per line, and a counter that changes whenever a file is written. */
EXPORT const char* virtual_file_list() {
  out.clear();
  for (auto& [name, data] : LittleFS.files) out += name + "\n";
  return out.c_str();
}
EXPORT uint32_t virtual_file_writes() { return LittleFS.writes; }

// --- what /json/info needs that only the firmware knows --------------------------------------
EXPORT int virtual_custom_palettes() { return int(customPalettes.size()); }
EXPORT int virtual_version_id() { return VERSION; }
EXPORT int virtual_brightness() { return bri; }
