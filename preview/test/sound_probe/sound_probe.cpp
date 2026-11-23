// SPDX-License-Identifier: EUPL-1.2
// Test effects for the preview shim. The sound probe lights a bar as long as the volume
// (u_data[0], 0-255) says, from AudioReactive's data or WLED's sound simulation. The counter keeps
// state in its segment data across frames.
#include "wled.h"

namespace {
void mode_probe(void) {
  um_data_t* um = nullptr;
  if (!UsermodManager::getUMData(&um, USERMOD_ID_AUDIOREACTIVE)) um = simulateSound(SEGMENT.soundSim);
  const float volume = *(float*)um->u_data[0];
  const unsigned lit = unsigned(volume * SEGLEN / 255.0f + 0.5f);
  for (unsigned i = 0; i < SEGLEN; i++) SEGMENT.setPixelColor(i, i < lit ? SEGCOLOR(0) : 0);
}
const char kData[] PROGMEM = "Sound probe@;!;;1v";

// keeps a frame counter in its data: lights as many LEDs as frames it has run
void mode_counter(void) {
  if (!SEGENV.allocateData(sizeof(uint32_t))) return;
  uint32_t* n = reinterpret_cast<uint32_t*>(SEGENV.data);
  (*n)++;
  for (unsigned i = 0; i < SEGLEN; i++) SEGMENT.setPixelColor(i, i < *n ? SEGCOLOR(0) : 0);
}
const char kCounterData[] PROGMEM = "Counter@;!;;1";
}  // namespace

class SoundProbe : public Usermod {
 public:
  void setup() override {
    strip.addEffect(1, &mode_probe, kData);
    strip.addEffect(2, &mode_counter, kCounterData);
  }
  void loop() override {}
};
static SoundProbe sound_probe;
REGISTER_USERMOD(sound_probe);
