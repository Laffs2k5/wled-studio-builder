// SPDX-License-Identifier: EUPL-1.2
// A test effect for the preview shim's sound: lights a bar as long as the volume
// (u_data[0], 0-255) says, from AudioReactive's data or WLED's sound simulation.
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
}  // namespace

class SoundProbe : public Usermod {
 public:
  void setup() override { strip.addEffect(1, &mode_probe, kData); }
};
static SoundProbe sound_probe;
REGISTER_USERMOD(sound_probe);
