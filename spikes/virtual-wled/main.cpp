// SPDX-License-Identifier: EUPL-1.2
// spike: the globals and a frame loop, to see what the effect code calls at link time
#include "wled.h"
#undef WLED_GLOBAL
#undef _INIT
#define WLED_GLOBAL
#define _INIT(x) = x
#define briS 128   // the default brightness (a WLED_GLOBAL in wled.h)
#include "globals.h"
WS2812FX strip;
byte paletteBlend = 0;
time_t localTime = 0;
bool useAMPM = false;
FakeFS WLED_FS;
static uint32_t now_ms = 0, rng = 0x12345678u;
uint32_t millis() { return now_ms; }
uint32_t micros() { return now_ms * 1000u; }
uint32_t wled_preview_rng() { rng = rng * 1664525u + 1013904223u; return rng; }
#include <chrono>
#include <cstdio>
extern std::vector<uint32_t> g_frame;
int main(int argc, char** argv) {
  uint8_t pins[1] = {2};
  busConfigs.emplace_back(TYPE_SK6812_RGBW, pins, 0, 280);
  NeoGammaWLEDMethod::calcGammaTable(2.2f);   // as WLED does when it loads its config (gamma 2.2, the default)
  strip.setTransition(0);
  strip.finalizeInit();
  strip.makeAutoSegments();   // as WLED::beginStrip(): segment 0 over the whole strip
  strip.setBrightness(255);
  strip.getSegment(0).setColor(0, 0xFFA000);   // WLED's default orange
  printf("effects: %d, LEDs: %d\n", strip.getModeCount(), strip.getLengthTotal());
  int fx = argc > 1 ? atoi(argv[1]) : 9;
  strip.getSegment(0).setMode(fx, true);
  auto t0 = std::chrono::steady_clock::now();
  const int frames = 500;
  for (int i = 0; i < frames; i++) {
    now_ms += 25;
    strip.service();
    if (argc > 2) { for (size_t k = 0; k < g_frame.size(); k++) printf("%08x%c", g_frame[k], k + 1 < g_frame.size() ? ' ' : '\n'); continue; }
    if (i == 100 || i == 101 || i == 499) {
      printf("frame %d:", i);
      for (int k = 0; k < 8; k++) printf(" %08x", g_frame[k * 35]);
      printf("\n");
    }
  }
  double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  printf("effect %d: %.3f ms per frame (280 LEDs)\n", fx, ms / frames);
  return 0;
}
