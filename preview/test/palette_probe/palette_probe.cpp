// SPDX-License-Identifier: EUPL-1.2
// A probe for the preview's colours: effects that paint what WLED's colour API returns, so a test
// can compare the preview with WLED's own data. Not a real effect.
#include "wled.h"

namespace {
// LED k shows palette entry k: color_from_palette at index k * 16, "moving" (wrapping), which hits
// an entry exactly; unmapped; mcol 255 so palette 0 shows the effect's default palette too
void mode_entries() {
  for (unsigned i = 0; i < SEGLEN; i++) SEGMENT.setPixelColor(i, SEGMENT.color_from_palette(i * 16, false, true, 255));
}
// the same, not moving: WLED then remaps the index so the palette doesn't wrap, and blends
void mode_entries_still() {
  for (unsigned i = 0; i < SEGLEN; i++) SEGMENT.setPixelColor(i, SEGMENT.color_from_palette(i * 16, false, false, 255));
}
const char kStillData[] PROGMEM = "Entries still@;;!;1";
const char kEntriesData[] PROGMEM = "Entries@;;!;1";
// the same with a default palette in the metadata, as built-in effects declare one
const char kEntriesPal11Data[] PROGMEM = "Entries pal 11@;;!;1;pal=11";
// fade_out towards colour 2 from a lit strip, once per frame
void mode_fade() {
  if (SEGENV.call == 0) SEGMENT.fill(SEGCOLOR(0));
  SEGMENT.fade_out(128);
}
const char kFadeData[] PROGMEM = "Fade@;!,!;;1";
}  // namespace

class PaletteProbe : public Usermod {
 public:
  void setup() override {
    strip.addEffect(1, &mode_entries, kEntriesData);
    strip.addEffect(2, &mode_entries, kEntriesPal11Data);
    strip.addEffect(3, &mode_fade, kFadeData);
    strip.addEffect(4, &mode_entries_still, kStillData);
  }
  void loop() override {}
};
static PaletteProbe palette_probe;
REGISTER_USERMOD(palette_probe);
