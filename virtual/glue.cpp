// SPDX-License-Identifier: EUPL-1.2
// The virtual WLED's own side of the link: what WLED's effect engine calls that, on a device, is
// hardware or the rest of the firmware. Ours, not WLED's code.
#include "wled.h"
#include "fontmanager.h"
#include <memory>

// --- the globals the engine reads, defined (globals.h declares them) -----------------------
#undef WLED_GLOBAL
#undef _INIT
#undef _INIT_N
#define WLED_GLOBAL
#define _INIT(x) = x
#define VIRTUAL_UNPACK(...) __VA_ARGS__
#define _INIT_N(x) VIRTUAL_UNPACK x
#include "globals.h"
WS2812FX strip;
MemFS LittleFS;
VirtualDNSServer dnsServer;
VirtualWiFi WiFi;
VirtualSerial Serial;
std::vector<CRGBPalette16> customPalettes;
std::vector<UsermodPalette> usermodPalettes;

// --- time and randomness: the API sets the clock; a fixed seed keeps runs repeatable --------
namespace virtualwled {
uint32_t now_ms = 0;
uint32_t rng = 0x12345678u;
std::vector<uint32_t> frame;      // what the LEDs show, 0xWWRRGGBB
std::vector<Usermod*>& usermods() { static std::vector<Usermod*> v; return v; }
void register_usermod(Usermod* m) { usermods().push_back(m); }
}  // namespace virtualwled
// The clock runs a second ahead of the time the API asks for: WLED's service() skips a frame
// within MIN_FRAME_DELAY of the last one shown (at 0 at boot), so time 0 would show nothing. The
// effects still see the asked-for time: boot sets strip.timebase to take the second off again.
constexpr uint32_t kClockStart = 1000;
uint32_t millis() { return virtualwled::now_ms + kClockStart; }
uint32_t micros() { return millis() * 1000u; }
uint32_t wled_preview_rng() { virtualwled::rng = virtualwled::rng * 1664525u + 1013904223u; return virtualwled::rng; }

// --- the bus: keeps the pixels where a device would send them to the LEDs ------------------
class VirtualBus : public Bus {
 public:
  // one frame for all buses, in LED order: each bus keeps its LEDs at its start
  VirtualBus(uint16_t start, uint16_t len, bool rgbw) : Bus(rgbw ? TYPE_SK6812_RGBW : TYPE_WS2812_RGB, start, RGBW_MODE_MANUAL_ONLY, len) {
    if (virtualwled::frame.size() < size_t(start) + len) virtualwled::frame.resize(size_t(start) + len, 0);
    _valid = true;          // a bus counts only when valid (finalizeInit checks isOk())
    _hasRgb = true;         // its capabilities, as WLED's own drivers set them: without RGB a
    _hasWhite = rgbw;       // segment is on/off only, and refuses black as its first colour
    _hasCCT = false;
  }
  void setPixelColor(unsigned pix, uint32_t c) override { if (pix < getLength()) virtualwled::frame[getStart() + pix] = c; }
  uint32_t getPixelColor(unsigned pix) const override { return pix < getLength() ? virtualwled::frame[getStart() + pix] : 0; }
  void show() override {}
};

int16_t Bus::_cct = -1;
int8_t Bus::_cctBlend = 0;
uint8_t Bus::_gAWM = 255;
size_t BusConfig::memUsage() const { return 0; }
namespace BusManager {
std::vector<std::unique_ptr<Bus>> busses;
uint16_t _gMilliAmpsUsed = 0, _gMilliAmpsMax = 0;
bool _useABL = false;
void initializeABL() {}
uint8_t getI(uint8_t, const uint8_t*, uint8_t) { return 0; }
void removeAll() { busses.clear(); virtualwled::frame.clear(); }
int add(const BusConfig& bc, bool) {
  busses.push_back(std::make_unique<VirtualBus>(bc.start, bc.count, Bus::hasWhite(bc.type)));
  return int(busses.size()) - 1;
}
void setPixelColor(unsigned pix, uint32_t c) {
  for (auto& b : busses)
    if (pix >= b->getStart() && pix < b->getStart() + b->getLength()) { b->setPixelColor(pix - b->getStart(), c); return; }
}
void show() {}
bool canAllShow() { return true; }
void setSegmentCCT(int16_t, bool) {}
}  // namespace BusManager

// --- sound: the "mic" the API feeds; without it, effects use WLED's own simulation -----------
namespace virtualwled {
float level = -1;                 // < 0: no mic
static float volume_smth = 0, volume_raw = 0, major_peak = 440, magnitude = 0;
static uint8_t fft[16] = {0}, sample_peak = 0, max_vol = 31, bin_num = 8;
static void* ptrs[8] = {&volume_smth, &volume_raw, fft, &sample_peak, &major_peak, &magnitude, &max_vol, &bin_num};
static um_types_t types[8] = {UMT_FLOAT, UMT_FLOAT, UMT_BYTE_ARR, UMT_BYTE, UMT_FLOAT, UMT_FLOAT, UMT_BYTE, UMT_BYTE};
static um_data_t sound = [] { um_data_t d; d.u_size = 8; d.u_type = types; d.u_data = ptrs; return d; }();
}  // namespace virtualwled
bool UsermodManager::getUMData(um_data_t** data, uint8_t mod_id) {
  using namespace virtualwled;
  if (level < 0 || (mod_id != USERMOD_ID_AUDIOREACTIVE && mod_id != USERMOD_ID_RESERVED)) return false;
  volume_smth = volume_raw = level;
  magnitude = level * 4;
  sample_peak = level > 200 ? 1 : 0;
  for (int i = 0; i < 16; i++)
    fft[i] = uint8_t(fminf(255.f, level * (1.2f - i / 20.f) * (0.85f + 0.15f * sinf(now_ms / 150.f + i))));
  *data = &sound;
  return true;
}

// --- the rest: no fonts, no files, plain memory ----------------------------------------------
bool FontManager::loadFont(uint8_t, const char*, bool) { return false; }
uint8_t FontManager::getGlyphWidth(uint32_t) { return 0; }
void FontManager::drawCharacter(uint32_t, int16_t, int16_t, uint32_t, uint32_t, int8_t) {}
void* allocate_buffer(size_t size, uint32_t) { return calloc(size, 1); }
void* d_malloc(size_t size) { return malloc(size); }
void* p_malloc(size_t size) { return malloc(size); }

// WLED's JSON buffer lock, single-threaded: the same contract (no buffer or held: refuse; else
// take it and clear the document) without the ESP32's mutex
bool requestJSONBufferLock(uint8_t moduleID) {
  if (pDoc == nullptr || jsonBufferLock) return false;
  jsonBufferLock = moduleID ? moduleID : 255;
  pDoc->clear();
  return true;
}
void releaseJSONBufferLock() { jsonBufferLock = 0; }
void enumerateLedmaps() {}

// --- the network: a virtual device has none. WLED's sync (UDP notifier), realtime input, the
// HTTP API in JSON ("win"), NTP. Its websocket push is the device server's: it counts pushes.
namespace virtualwled { uint32_t ws_pushes = 0; }
void sendDataWs(AsyncWebSocketClient*) { virtualwled::ws_pushes++; }
void notify(byte, bool) {}
void sendSysInfoUDP() {}
void realtimeLock(uint32_t timeoutMs, byte mode) {
  if (!realtimeMode && !realtimeOverride) {
    if (useMainSegmentOnly) {
      Segment& main = strip.getMainSegment();
      main.clear();
      main.freeze = true;
      if (bri == 0)
        for (size_t i = 0; i < strip.getSegmentsNum(); i++) strip.getSegment(i).freeze = true;
    } else {
      strip.fill(BLACK);
    }
    if (briT == 0) strip.setBrightness(briLast, true);
  }
  if (realtimeTimeout != UINT32_MAX)
    realtimeTimeout = (timeoutMs == 255001 || timeoutMs == 65000) ? UINT32_MAX : millis() + timeoutMs;
  realtimeMode = mode;
  if (!realtimeOverride && arlsForceMaxBri) strip.setBrightness(255, true);
}
void exitRealtime() {
  if (!realtimeMode) return;
  if (realtimeOverride == REALTIME_OVERRIDE_ONCE) realtimeOverride = REALTIME_OVERRIDE_NONE;
  strip.setBrightness(bri, true);
  realtimeTimeout = 0;
  realtimeMode = REALTIME_MODE_INACTIVE;
  if (useMainSegmentOnly) {
    strip.getMainSegment().freeze = false;
    strip.trigger();
  } else {
    strip.show();
  }
  updateInterfaces(CALL_MODE_WS_SEND);
}
void setTimeFromAPI(uint32_t) {}
bool handleSet(AsyncWebServerRequest*, const String&, bool) { return false; }

// UsermodManager (WLED's um_manager.cpp): the state hooks, over the registered usermods
void UsermodManager::addToJsonState(JsonObject& obj) { for (Usermod* m : virtualwled::usermods()) m->addToJsonState(obj); }
void UsermodManager::readFromJsonState(JsonObject& obj) { for (Usermod* m : virtualwled::usermods()) m->readFromJsonState(obj); }
void UsermodManager::onStateChange(uint8_t mode) { for (Usermod* m : virtualwled::usermods()) m->onStateChange(mode); }

// Usermod's one out-of-line method (WLED's um_manager.cpp; it carries the class's vtable). It
// writes settings-page script; a virtual device has no settings page.
void Usermod::appendConfigData(Print&) {}

#ifdef WLED_ENABLE_GIF
// the Image effect's loader (WLED's image_loader.cpp): a virtual device has no image files
byte renderImageToSegment(Segment&) { return 1; }   // IMAGE_ERROR_NO_NAME (image_loader.cpp)
void endImagePlayback(Segment*) {}
#endif

#if defined(__has_feature)
#if __has_feature(address_sanitizer)
// A SANITIZE=1 build reports every memory error and carries on: WLED's own code has some (e.g. a
// palette read past its end, harmless on a device), and the tests compare against the firmware
// without our usermods, so they need all of them, not the first.
extern "C" const char* __asan_default_options() { return "halt_on_error=0:detect_leaks=0"; }
#endif
#endif
