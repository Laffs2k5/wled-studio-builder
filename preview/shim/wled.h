// SPDX-License-Identifier: EUPL-1.2
// A stand-in for WLED's wled.h, for previewing effects in the browser.
//
// It implements the part of WLED's usermod and effect API that effect code uses
// (Usermod, REGISTER_USERMOD, strip.addEffect, SEGMENT, SEGENV, SEGLEN, colours),
// so an effect usermod written for WLED compiles unchanged to WebAssembly. This
// is our own implementation of that interface, not WLED's code.
//
// Colours come in two modes:
// - approximate (the default): our own stand-ins for fades, palettes and the colour wheel;
// - exact (PREVIEW_WLED_COLORS, when build.sh is given a WLED checkout): WLED's own colour and
//   palette code, generated from that checkout by wled_colors.py, compiles in instead.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string>
#include <vector>

#define PROGMEM
#define F(x) (x)
#define FPSTR(x) (x)

class String {
 public:
  String() = default;
  String(const char* s) : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  String(int v) : s_(std::to_string(v)) {}
  String(unsigned v) : s_(std::to_string(v)) {}
  String(long v) : s_(std::to_string(v)) {}
  String(unsigned long v) : s_(std::to_string(v)) {}
  const char* c_str() const { return s_.c_str(); }
  size_t length() const { return s_.size(); }
  const std::string& str() const { return s_; }
  String& operator+=(const String& o) { s_ += o.s_; return *this; }
  friend String operator+(const String& a, const String& b) { return String(a.s_ + b.s_); }
  friend String operator+(const char* a, const String& b) { return String(std::string(a) + b.s_); }
  friend String operator+(const String& a, const char* b) { return String(a.s_ + b); }
  bool operator==(const String& o) const { return s_ == o.s_; }

 private:
  std::string s_;
};

// JSON: usermods add to /json/info; in the preview that goes nowhere.
struct JsonArray { template <typename T> void add(const T&) {} };
struct JsonObject {
  JsonObject operator[](const char*) { return JsonObject(); }
  bool isNull() const { return true; }
  JsonObject createNestedObject(const char*) { return JsonObject(); }
  JsonArray createNestedArray(const char*) { return JsonArray(); }
  template <typename T> JsonObject& operator=(const T&) { return *this; }
};

#ifdef PREVIEW_WLED_COLORS
// WLED's colour types, macros and functions, from the checkout (generated: see wled_colors.py)
#include "wled_colors_prelude.h"
#include "colors.h"
#else
// colours: WLED packs them as 0xWWRRGGBB
#define RGBW32(r, g, b, w) ((uint32_t(w) << 24) | (uint32_t(r) << 16) | (uint32_t(g) << 8) | uint32_t(b))
#define R(c) (uint8_t((c) >> 16))
#define G(c) (uint8_t((c) >> 8))
#define B(c) (uint8_t(c))
#define W(c) (uint8_t((c) >> 24))
#endif

struct SegmentRuntime {
  uint32_t call = 0, step = 0;
  uint16_t aux0 = 0, aux1 = 0;
  uint8_t* data = nullptr;
  size_t dataSize = 0;
  bool allocateData(size_t len);
  void deallocateData();
};

struct Segment {
  uint16_t start = 0, stop = 0;
  uint8_t speed = 128, intensity = 128, custom1 = 128, custom2 = 128, custom3 = 16;
  bool check1 = false, check2 = false, check3 = false;
  uint8_t palette = 0;
  uint8_t soundSim = 0;
  uint32_t colors[3] = {RGBW32(255, 160, 0, 0), 0, 0};
  mutable std::vector<uint32_t> pixels;   // mutable: WLED's drawing methods are const
  bool _isRGB = true;
  uint8_t _default_palette = 6;           // palette 0 shows this one (the effect's "pal=" default)

  static uint16_t vLength();
  unsigned length() const { return vLength(); }
  unsigned rawLength() const { return vLength(); }
  bool isActive() const { return true; }
  static uint32_t getCurrentColor(unsigned i);
  void setPixelColor(int i, uint32_t c);
  void setPixelColor(int i, uint8_t r, uint8_t g, uint8_t b, uint8_t w = 0) { setPixelColor(i, RGBW32(r, g, b, w)); }
  uint32_t getPixelColor(int i) const;
  void setPixelColorRaw(unsigned i, uint32_t c) const;
  uint32_t getPixelColorRaw(unsigned i) const;
  // as WLED declares them; in exact mode the bodies are WLED's own
  void fill(uint32_t c) const;
  void fade_out(uint8_t rate) const;
  void fadeToBlackBy(uint8_t fadeBy) const;
  void fadeToSecondaryBy(uint8_t fadeBy) const;
  void blur(uint8_t blur_amount, bool smear = false) const;
  uint32_t color_wheel(uint8_t pos) const;
  uint32_t color_from_palette(uint16_t i, bool mapping, bool moving, uint8_t mcol, uint8_t pbri = 255) const;
#ifdef PREVIEW_WLED_COLORS
  void loadPalette(CRGBPalette16& targetPalette, uint8_t pal);
  static CRGBPalette16 _currentPalette;
  static CRGBPalette16 _randomPalette;
#endif
};
extern uint8_t paletteBlend;   // WLED's global: how palettes blend and wrap (0, as WLED's default)

// mode_ptr is nested, as in WLED: a usermod that names it unqualified fails there, so it fails here too
struct WS2812FX {
  typedef void (*mode_ptr)(void);
  uint32_t now = 0;
  Segment* _currentSegment = nullptr;
  uint8_t getModeCount() const;
  uint8_t addEffect(uint8_t id, mode_ptr fn, const char* metadata);
};
extern WS2812FX strip;
extern SegmentRuntime SEGENV_;

#define SEGMENT (*strip._currentSegment)
#define SEGENV SEGENV_
#define SEGLEN Segment::vLength()
#define SEGCOLOR(x) (strip._currentSegment->colors[(x)])

// a few of the integer helpers effects commonly use
uint8_t sin8_t(uint8_t theta);
uint8_t cos8_t(uint8_t theta);
#ifndef PREVIEW_WLED_COLORS   // in exact mode fastled_slim has them
uint8_t scale8(uint8_t i, uint8_t scale);
uint8_t qadd8(uint8_t a, uint8_t b);
uint8_t qsub8(uint8_t a, uint8_t b);
uint32_t color_blend(uint32_t a, uint32_t b, uint8_t blend);
#endif
uint8_t beatsin8_t(uint16_t bpm, uint8_t low = 0, uint8_t high = 255, uint32_t timebase = 0, uint8_t phase = 0);
uint8_t hw_random8();
uint8_t hw_random8(uint32_t upperlimit);
uint8_t hw_random8(uint32_t lowerlimit, uint32_t upperlimit);
uint16_t hw_random16();
uint16_t hw_random16(uint16_t lim);
template <typename T> T map(T x, T in_min, T in_max, T out_min, T out_max) {
  return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}
template <typename T, typename U> auto min(T a, U b) -> decltype(a < b ? a : b) { return a < b ? a : b; }
template <typename T, typename U> auto max(T a, U b) -> decltype(a > b ? a : b) { return a > b ? a : b; }

// Sound: the usermod data exchange WLED's sound effects use. FX.cpp's getAudioData() is static
// there, so a usermod effect asks the usermod manager for AudioReactive's data and falls back to
// WLED's sound simulation, as FX.cpp does. In the preview the data comes from preview_audio(),
// or from our own simulation when no level is set. Layout as WLED's: [0] volumeSmth (float),
// [1] volumeRaw (float), [2] fftResult (uint8_t[16]), [3] samplePeak (uint8_t), [4] FFT_MajorPeak
// (float), [5] my_magnitude (float), [6] maxVol (uint8_t), [7] binNum (uint8_t).
typedef enum { UMT_BYTE = 0, UMT_UINT16, UMT_INT16, UMT_UINT32, UMT_INT32, UMT_FLOAT, UMT_DOUBLE, UMT_BYTE_ARR,
               UMT_UINT16_ARR, UMT_INT16_ARR, UMT_UINT32_ARR, UMT_INT32_ARR, UMT_FLOAT_ARR, UMT_DOUBLE_ARR } um_types_t;
typedef struct UM_Exchange_Data {
  size_t u_size = 0;
  um_types_t* u_type = nullptr;
  void** u_data = nullptr;
} um_data_t;
#define USERMOD_ID_RESERVED 0
#define USERMOD_ID_AUDIOREACTIVE 32
namespace UsermodManager { bool getUMData(um_data_t** data, uint8_t mod_id = USERMOD_ID_RESERVED); }
um_data_t* simulateSound(uint8_t simulationId);

class Usermod {
 public:
  virtual ~Usermod() = default;
  virtual void setup() = 0;  // pure virtual, as in WLED
  virtual void loop() = 0;
  virtual void addToJsonInfo(JsonObject&) {}
  virtual uint16_t getId() { return 1; }
};

namespace preview { void register_usermod(Usermod* m); }
struct UsermodRegistrar { explicit UsermodRegistrar(Usermod* m) { preview::register_usermod(m); } };
#define REGISTER_USERMOD(x) static UsermodRegistrar _preview_registrar_##x(&(x))
