// SPDX-License-Identifier: EUPL-1.2
// spike: the virtual device's own side: a bus that keeps the pixels, and stand-ins for the rest
#include "wled.h"
#include "fontmanager.h"
#include <memory>

std::vector<uint32_t> g_frame;   // what the "LEDs" show, 0xWWRRGGBB

class PreviewBus : public Bus {
 public:
  PreviewBus(uint16_t len) : Bus(TYPE_SK6812_RGBW, 0, RGBW_MODE_MANUAL_ONLY, len) { g_frame.assign(len, 0); _valid = true; }
  void setPixelColor(unsigned pix, uint32_t c) override { if (pix < g_frame.size()) g_frame[pix] = c; }
  uint32_t getPixelColor(unsigned pix) const override { return pix < g_frame.size() ? g_frame[pix] : 0; }
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
void removeAll() { busses.clear(); }
int add(const BusConfig& bc, bool) { busses.push_back(std::make_unique<PreviewBus>(bc.count)); return int(busses.size()) - 1; }
void setPixelColor(unsigned pix, uint32_t c) { if (!busses.empty()) busses[0]->setPixelColor(pix, c); }
void show() {}
void setSegmentCCT(int16_t, bool) {}
}  // namespace BusManager

bool FontManager::loadFont(uint8_t, const char*, bool) { return false; }
uint8_t FontManager::getGlyphWidth(uint32_t) { return 0; }
void FontManager::drawCharacter(uint32_t, int16_t, int16_t, uint32_t, uint32_t, int8_t) {}
bool UsermodManager::getUMData(um_data_t**, uint8_t) { return false; }   // no mic: effects simulate
void* allocate_buffer(size_t size, uint32_t) { return calloc(size, 1); }
void* d_malloc(size_t size) { return malloc(size); }
std::vector<CRGBPalette16> customPalettes;
std::vector<UsermodPalette> usermodPalettes;
bool gammaCorrectCol = false;
void enumerateLedmaps() {}
