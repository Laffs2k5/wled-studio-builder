// SPDX-License-Identifier: EUPL-1.2
#pragma once
// spike: the Arduino basics effect code uses
#include <cstdint>
#include <cmath>
#include <cstring>
#include <cstdlib>
#include <string>
#include <type_traits>
#include <functional>
class String {
 public:
  String() = default;
  String(const char* s) : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  String(int v) : s_(std::to_string(v)) {}
  String(unsigned v) : s_(std::to_string(v)) {}
  String(long v) : s_(std::to_string(v)) {}
  String(unsigned long v) : s_(std::to_string(v)) {}
  String(float v, int = 2) : s_(std::to_string(v)) {}
  const char* c_str() const { return s_.c_str(); }
  size_t length() const { return s_.size(); }
  char operator[](size_t i) const { return s_[i]; }
  String& operator+=(const String& o) { s_ += o.s_; return *this; }
  bool concat(const char* s) { s_ += s; return true; }
  bool concat(char c) { s_ += c; return true; }
  bool concat(const char* s, unsigned n) { s_.append(s, n); return true; }
  friend String operator+(const String& a, const String& b) { return String(a.s_ + b.s_); }
  bool operator==(const String& o) const { return s_ == o.s_; }
  bool operator==(const char* o) const { return s_ == o; }
  int indexOf(char c) const { auto p = s_.find(c); return p == std::string::npos ? -1 : int(p); }
  String substring(size_t a, size_t b = std::string::npos) const { return String(s_.substr(a, b == std::string::npos ? b : b - a)); }
  long toInt() const { return atol(s_.c_str()); }
 private:
  std::string s_;
};
class StringSumHelper : public String { public: using String::String; };   // ArduinoJson names it
class Print { public: virtual ~Print() = default; virtual size_t write(uint8_t) = 0; size_t print(const char* s) { size_t n = 0; while (*s) n += write(uint8_t(*s++)); return n; } };
class IPAddress { public: IPAddress(uint8_t a = 0, uint8_t b = 0, uint8_t c = 0, uint8_t d = 0) : v{a, b, c, d} {} uint8_t operator[](int i) const { return v[i]; } private: uint8_t v[4]; };
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_SPIRAM 4
#define MALLOC_CAP_DEFAULT 8
inline void* heap_caps_malloc(size_t n, uint32_t) { return malloc(n); }
inline void* heap_caps_calloc(size_t n, size_t m, uint32_t) { return calloc(n, m); }
inline void* heap_caps_realloc(void* p, size_t n, uint32_t) { return realloc(p, n); }
inline void* heap_caps_malloc_prefer(size_t n, size_t, ...) { return malloc(n); }
inline void* heap_caps_realloc_prefer(void* p, size_t n, size_t, ...) { return realloc(p, n); }
inline void* heap_caps_calloc_prefer(size_t n, size_t m, size_t, ...) { return calloc(n, m); }
inline void heap_caps_free(void* p) { free(p); }
inline size_t heap_caps_get_free_size(uint32_t) { return 200000; }
inline size_t heap_caps_get_largest_free_block(uint32_t) { return 100000; }
extern uint32_t wled_preview_rng();
#define REG_READ(x) wled_preview_rng()
#define WDEV_RND_REG 0
#define LEDC_SPEED_MODE_MAX 2
#define LEDC_CHANNEL_MAX 8
typedef unsigned int uint;
#define strncmp_P strncmp
#define sprintf_P sprintf
#define pgm_read_byte_near(a) (*(const uint8_t*)(a))
#ifndef M_TWOPI
#define M_TWOPI 6.283185307179586
#endif
#define radians(d) ((d) * 0.017453292519943295)
#define degrees(r) ((r) * 57.29577951308232)
// by value: decltype(a < b ? a : b) would be a reference to a parameter, dangling once returned
template <typename T, typename U> typename std::common_type<T, U>::type min(T a, U b) { return a < b ? a : b; }
template <typename T, typename U> typename std::common_type<T, U>::type max(T a, U b) { return a > b ? a : b; }
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))   // as Arduino
inline long map(long x, long in_min, long in_max, long out_min, long out_max) {
  return in_max == in_min ? out_min : (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}
class EspalexaDevice; struct e131_packet_t;
class AsyncWebServerRequest; class AsyncClient;
#define bitRead(v, b) (((v) >> (b)) & 1)
#define bitSet(v, b) ((v) |= (1UL << (b)))
#define bitClear(v, b) ((v) &= ~(1UL << (b)))
#define bitWrite(v, b, x) ((x) ? bitSet(v, b) : bitClear(v, b))
#define strcpy_P strcpy
#define strcat_P strcat
#ifndef HALF_PI
#define HALF_PI 1.5707963267948966
#endif
inline void yield() {}
inline void delay(unsigned long) {}
// no file system in the browser: every file is missing (LED maps, custom palettes)
class File {
 public:
  explicit operator bool() const { return false; }
  size_t size() const { return 0; } size_t read(uint8_t*, size_t) { return 0; } int read() { return -1; }
  bool seek(size_t) { return false; } size_t position() const { return 0; } int available() { return 0; }
  bool find(const char*) { return false; } void close() {} const char* name() const { return ""; }
  size_t readBytesUntil(char, char*, size_t) { return 0; }
};
struct FakeFS { File open(const char*, const char* = "r") { return File(); } bool exists(const char*) { return false; } };
extern FakeFS WLED_FS;
