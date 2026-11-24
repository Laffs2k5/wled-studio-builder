// SPDX-License-Identifier: EUPL-1.2
#pragma once
#include <cstring>
#include <cstdint>
#define pgm_read_byte(a) (*(const uint8_t*)(a))
#define pgm_read_word(a) (*(const uint16_t*)(a))
#define pgm_read_dword(a) (*(const uint32_t*)(a))
#define memcpy_P memcpy
