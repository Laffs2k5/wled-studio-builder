// SPDX-License-Identifier: EUPL-1.2
// The preview runtime: the stand-in WLED API (wled.h) and a C API for JavaScript.
#include "wled.h"

#include <cmath>
#include <cstdlib>
#include <cstring>

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#define EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define EXPORT extern "C"
#endif

WS2812FX strip;
SegmentRuntime SEGENV_;

namespace {
struct EffectEntry { mode_ptr fn; std::string metadata; };
std::vector<EffectEntry>& effects() { static std::vector<EffectEntry> v; return v; }
std::vector<Usermod*>& usermods() { static std::vector<Usermod*> v; return v; }
Segment seg;
int current = -1;
uint32_t rng = 0x12345678u;
std::string scratch;

std::string name_of(const std::string& md) { return md.substr(0, md.find('@')); }
}  // namespace

void preview::register_usermod(Usermod* m) { usermods().push_back(m); }

bool SegmentRuntime::allocateData(size_t len) {
  if (data && dataSize >= len) { memset(data, 0, len); return true; }
  deallocateData();
  data = static_cast<uint8_t*>(calloc(len, 1));
  dataSize = data ? len : 0;
  return data != nullptr;
}
void SegmentRuntime::deallocateData() { free(data); data = nullptr; dataSize = 0; }

uint16_t Segment::vLength() { return uint16_t(seg.pixels.size()); }
void Segment::setPixelColor(int i, uint32_t c) { if (i >= 0 && size_t(i) < pixels.size()) pixels[i] = c; }
uint32_t Segment::getPixelColor(int i) const { return (i >= 0 && size_t(i) < pixels.size()) ? pixels[i] : 0; }
void Segment::fill(uint32_t c) { for (auto& p : pixels) p = c; }
void Segment::fade_out(uint8_t rate) {
  // towards the background colour; WLED's exact curve differs (approximation)
  uint32_t bg = colors[1];
  uint8_t keep = 255 - ((255 - rate) / 2 + 1) / 1;
  for (auto& p : pixels) p = color_blend(bg, p, keep);
}
void Segment::fadeToBlackBy(uint8_t amount) { for (auto& p : pixels) p = color_blend(p, 0, amount); }
uint32_t Segment::color_from_palette(uint16_t i, bool mapping, bool, uint8_t mcol, uint8_t pbri) const {
  uint32_t c;
  if (palette == 0) {
    c = colors[mcol < 3 ? mcol : 0];  // WLED's default palette is effect-specific; the colour slot is a fair stand-in
  } else {
    uint16_t pos = mapping && !pixels.empty() ? uint16_t(i * 255 / pixels.size()) : i;
    c = color_wheel(uint8_t(pos + palette * 37));
  }
  return pbri == 255 ? c : color_blend(0, c, pbri);
}

uint8_t WS2812FX::getModeCount() const { return uint8_t(effects().size()); }
uint8_t WS2812FX::addEffect(uint8_t id, mode_ptr fn, const char* metadata) {
  // as WLED: an id below the count replaces nothing here; anything else appends at the end
  if (id < effects().size()) return 255;
  if (effects().size() >= 255) return 255;
  effects().push_back({fn, metadata ? metadata : ""});
  return uint8_t(effects().size() - 1);
}

uint8_t sin8_t(uint8_t theta) { return uint8_t(lround(127.5 + 127.5 * sin(theta * 2 * M_PI / 256.0))); }
uint8_t cos8_t(uint8_t theta) { return sin8_t(uint8_t(theta + 64)); }
uint8_t scale8(uint8_t i, uint8_t scale) { return uint8_t((uint16_t(i) * (1 + uint16_t(scale))) >> 8); }
uint8_t qadd8(uint8_t a, uint8_t b) { unsigned t = a + b; return t > 255 ? 255 : uint8_t(t); }
uint8_t qsub8(uint8_t a, uint8_t b) { return a > b ? uint8_t(a - b) : 0; }
uint8_t beatsin8_t(uint16_t bpm, uint8_t low, uint8_t high, uint32_t timebase, uint8_t phase) {
  uint8_t beat = uint8_t(((strip.now - timebase) * bpm * 256 / 60000) & 0xFF);
  return uint8_t(low + scale8(sin8_t(uint8_t(beat + phase)), uint8_t(high - low)));
}
uint8_t hw_random8() { rng = rng * 1664525u + 1013904223u; return uint8_t(rng >> 24); }
uint8_t hw_random8(uint8_t lim) { return uint8_t((uint16_t(hw_random8()) * lim) >> 8); }
uint16_t hw_random16() { rng = rng * 1664525u + 1013904223u; return uint16_t(rng >> 16); }
uint16_t hw_random16(uint16_t lim) { return uint16_t((uint32_t(hw_random16()) * lim) >> 16); }
uint32_t color_blend(uint32_t a, uint32_t b, uint8_t blend) {
  auto mix = [blend](uint8_t x, uint8_t y) { return uint8_t((x * (255 - blend) + y * blend) / 255); };
  return RGBW32(mix(R(a), R(b)), mix(G(a), G(b)), mix(B(a), B(b)), mix(W(a), W(b)));
}
uint32_t color_wheel(uint8_t pos) {
  pos = 255 - pos;
  if (pos < 85) return RGBW32(255 - pos * 3, 0, pos * 3, 0);
  if (pos < 170) { pos -= 85; return RGBW32(0, pos * 3, 255 - pos * 3, 0); }
  pos -= 170;
  return RGBW32(pos * 3, 255 - pos * 3, 0, 0);
}

// --- the C API for JavaScript ---------------------------------------------------

EXPORT void preview_setup(int length) {
  seg.pixels.assign(length > 0 ? length : 1, 0);
  seg.stop = uint16_t(seg.pixels.size());
  strip._currentSegment = &seg;
  if (effects().empty()) {
    effects().push_back({[] { SEGMENT.fill(SEGCOLOR(0)); }, "Solid"});
    for (Usermod* m : usermods()) m->setup();
  }
}

// effects are numbered by their id; reserved placeholders ("RSVD") are listed too, as on the device
EXPORT int preview_effect_count() { return int(effects().size()); }
EXPORT const char* preview_effect_name(int id) {
  scratch = (id >= 0 && size_t(id) < effects().size()) ? name_of(effects()[id].metadata) : "";
  return scratch.c_str();
}
EXPORT const char* preview_effect_metadata(int id) {
  scratch = (id >= 0 && size_t(id) < effects().size()) ? effects()[id].metadata : "";
  auto at = scratch.find('@');
  scratch = at == std::string::npos ? "" : scratch.substr(at + 1);
  return scratch.c_str();
}
EXPORT int preview_select(int id) {
  if (id < 0 || size_t(id) >= effects().size()) return -1;
  current = id;
  SEGENV_.call = 0; SEGENV_.step = 0; SEGENV_.aux0 = 0; SEGENV_.aux1 = 0;
  SEGENV_.deallocateData();
  seg.fill(0);
  return id;
}
EXPORT void preview_set(int key, int value) {
  uint8_t v = uint8_t(value);
  switch (key) {
    case 0: seg.speed = v; break;      case 1: seg.intensity = v; break;
    case 2: seg.custom1 = v; break;    case 3: seg.custom2 = v; break;
    case 4: seg.custom3 = v & 31; break;
    case 5: seg.check1 = value; break; case 6: seg.check2 = value; break; case 7: seg.check3 = value; break;
    case 8: seg.palette = v; break;
    case 9: case 10: case 11: seg.colors[key - 9] = uint32_t(value); break;
  }
}
EXPORT int preview_length() { return int(seg.pixels.size()); }
// runs one frame at time now_ms; returns the pixels (0xWWRRGGBB per LED)
EXPORT uint32_t* preview_frame(uint32_t now_ms) {
  if (current < 0) return seg.pixels.data();
  strip.now = now_ms;
  strip._currentSegment = &seg;
  effects()[current].fn();
  SEGENV_.call++;
  return seg.pixels.data();
}
