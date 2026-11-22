// SPDX-License-Identifier: EUPL-1.2
// studio_example_fx: a minimal example of an own effect for wled-studio builds.
//
// It shows the fixed-id registration: the effect always gets the same effect
// id, independent of how many effects WLED itself has, so presets that store
// the id keep working across builds. WLED's addEffect() appends at the end of
// the list whatever id is asked for, so the usermod first pads the list with
// hidden placeholders ("RSVD", which WLED's UI and setMode() skip) up to the
// chosen id. If WLED already has that many effects, nothing is registered and
// the reason is reported in /json/info.
#include "wled.h"

namespace {

constexpr uint8_t kCometId = 254;  // the top of WLED's 0-254 effect id space

// Placeholder for padding. The name must contain "RSVD" (hidden by WLED's UI and
// skipped by setMode) and must not be empty (/json/eff drops empty names).
const char kPadName[] PROGMEM = "RSVD";

// Solid colour, as WLED's own fallback (its mode_static isn't exported).
void fill_solid(void) { SEGMENT.fill(SEGCOLOR(0)); }
void mode_pad(void) { fill_solid(); }

// "Studio Comet": a head that runs along the segment, leaving a fading tail.
// Speed sets the pace, intensity the tail length; colours from the palette.
void mode_studio_comet(void) {
  const unsigned len = SEGLEN;
  if (len <= 1) { fill_solid(); return; }
  const uint32_t period = 256U * (300U - SEGMENT.speed);     // ms for one pass, roughly
  const unsigned pos = (uint32_t)((strip.now % period) * len / period);
  SEGMENT.fade_out(255 - SEGMENT.intensity);
  SEGMENT.setPixelColor(pos, SEGMENT.color_from_palette(pos, true, false, 0));
}
const char kCometData[] PROGMEM = "Studio Comet@Speed,Tail;!;!;1;sx=128,ix=200";

}  // namespace

class StudioExampleFx : public Usermod {
 public:
  void setup() override {
    if (strip.getModeCount() > kCometId) {
      status_ = "not registered: WLED already uses id " + String(kCometId);
      return;
    }
    while (strip.getModeCount() < kCometId) {
      if (strip.addEffect(strip.getModeCount(), &mode_pad, kPadName) == 255) {
        status_ = "not registered: padding failed";
        return;
      }
    }
    const uint8_t id = strip.addEffect(kCometId, &mode_studio_comet, kCometData);
    status_ = (id == kCometId) ? "Studio Comet = " + String(id)
                               : "unexpected id " + String(id);
  }

  void addToJsonInfo(JsonObject& root) override {
    JsonObject user = root["u"];
    if (user.isNull()) user = root.createNestedObject("u");
    JsonArray arr = user.createNestedArray(F("Studio FX"));
    arr.add(status_);
  }

  void loop() override {}

 private:
  String status_ = "not set up";
};

static StudioExampleFx studio_example_fx;
REGISTER_USERMOD(studio_example_fx);
