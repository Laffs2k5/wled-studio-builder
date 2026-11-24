// SPDX-License-Identifier: EUPL-1.2
// A usermod with an effect that crashes after a few frames: an integer division by zero, which an
// ESP32 also traps on. The virtual check must fail on it, naming the effect. Not a real effect.
#include "wled.h"

namespace {
volatile unsigned zero = 0;
void mode_crash() {
  if (SEGENV.call > 4) SEGENV.aux0 = uint16_t(1000u / zero);
  SEGMENT.fill(SEGCOLOR(0));
}
const char kCrashData[] PROGMEM = "Crash Probe@;!;;1";
}  // namespace

class CrashProbe : public Usermod {
 public:
  void setup() override { strip.addEffect(250, &mode_crash, kCrashData); }
  void loop() override {}
};
static CrashProbe crash_probe;
REGISTER_USERMOD(crash_probe);
