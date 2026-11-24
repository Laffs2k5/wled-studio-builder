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
class Print { public: virtual ~Print() = default; virtual size_t write(uint8_t) = 0; size_t print(const char* s) { size_t n = 0; while (*s) n += write(uint8_t(*s++)); return n; }
  template <typename... A> size_t printf(const char*, A...) { return 0; }
  template <typename... A> size_t printf_P(const char*, A...) { return 0; } };
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
typedef uint16_t word;
inline uint16_t makeWord(uint16_t w) { return w; }
inline uint16_t makeWord(uint8_t h, uint8_t l) { return uint16_t((h << 8) | l); }
#define word(...) makeWord(__VA_ARGS__)   // as Arduino: a type and a two-byte constructor
// the serial port: debug output nobody reads on a virtual device
struct VirtualSerial : public Print {
  size_t write(uint8_t) override { return 1; }
  template <typename T> size_t println(const T&) { return 0; }
  size_t println() { return 0; }
  template <typename T> size_t print(const T&) { return 0; }
};
extern VirtualSerial Serial;
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
#define WIFI_POWER_19_5dBm 78   // the ESP32 Wi-Fi power enum's default; a global's initialiser names it
#define snprintf_P snprintf
#define strcat_P strcat
#ifndef HALF_PI
#define HALF_PI 1.5707963267948966
#endif
inline void yield() {}
inline void delay(unsigned long) {}
// The file system: in memory, as LittleFS's API. Presets (presets.json) and custom palettes
// (palette<n>.json) live here, written and read by WLED's own code (presets.cpp, file.cpp).
#include <map>
#include <memory>
enum SeekMode { SeekSet = 0, SeekCur = 1, SeekEnd = 2 };
class File {
 public:
  File() = default;
  File(std::shared_ptr<std::string> d, std::string name, size_t pos) : d_(std::move(d)), name_(std::move(name)), pos_(pos) {}
  explicit operator bool() const { return bool(d_); }
  size_t size() const { return d_ ? d_->size() : 0; }
  size_t position() const { return pos_; }
  bool seek(size_t p) { if (!d_ || p > d_->size()) return false; pos_ = p; return true; }
  bool seek(long off, int mode) {   // Arduino's SeekMode: SeekSet, SeekCur, SeekEnd
    long base = mode == 1 ? long(pos_) : mode == 2 ? long(size()) : 0;
    return off + base >= 0 && seek(size_t(off + base));
  }
  int available() { return d_ ? int(d_->size() - pos_) : 0; }
  int peek() { return available() > 0 ? (uint8_t)(*d_)[pos_] : -1; }
  int read() { return available() > 0 ? (uint8_t)(*d_)[pos_++] : -1; }
  size_t read(uint8_t* buf, size_t n) { size_t k = 0; while (k < n && available() > 0) buf[k++] = (uint8_t)(*d_)[pos_++]; return k; }
  size_t readBytes(char* buf, size_t n) { return read(reinterpret_cast<uint8_t*>(buf), n); }
  size_t readBytesUntil(char term, char* buf, size_t n) {
    size_t k = 0;
    while (k < n && available() > 0) { char c = (*d_)[pos_++]; if (c == term) break; buf[k++] = c; }
    return k;
  }
  bool find(const char* s) {     // past the next occurrence of s, as Arduino's Stream::find
    if (!d_) return false;
    size_t at = d_->find(s, pos_);
    if (at == std::string::npos) { pos_ = d_->size(); return false; }
    pos_ = at + strlen(s);
    return true;
  }
  size_t write(uint8_t c) { return write(&c, 1); }
  size_t write(char c) { return write(uint8_t(c)); }
  size_t print(char c) { return write(uint8_t(c)); }
  size_t write(const uint8_t* b, size_t n) {
    if (!d_) return 0;
    if (pos_ > d_->size()) pos_ = d_->size();
    d_->replace(pos_, std::min(n, d_->size() - pos_), reinterpret_cast<const char*>(b), n);
    pos_ += n;
    return n;
  }
  size_t print(const char* s) { return write(reinterpret_cast<const uint8_t*>(s), strlen(s)); }
  void flush() {}
  void close() { d_.reset(); }
  const char* name() const { return name_.c_str(); }
  bool isDirectory() const { return false; }
 private:
  std::shared_ptr<std::string> d_;
  std::string name_;
  size_t pos_ = 0;
};
struct MemFS {
  std::map<std::string, std::shared_ptr<std::string>> files;
  uint32_t writes = 0;      // counts opens for writing, removes and renames: the device server saves on a change
  File open(const char* path, const char* mode = "r") {
    std::string p = path, m = mode ? mode : "r";
    auto it = files.find(p);
    if (m[0] != 'r' || m.find('+') != std::string::npos) writes++;
    if (m[0] == 'r') return it == files.end() ? File() : File(it->second, p, 0);
    if (m[0] == 'w' || it == files.end()) files[p] = std::make_shared<std::string>();
    auto d = files[p];
    return File(d, p, m[0] == 'a' ? d->size() : 0);
  }
  File open(const String& path, const char* mode = "r") { return open(path.c_str(), mode); }
  bool exists(const char* path) { return files.count(path) > 0; }
  bool exists(const String& path) { return exists(path.c_str()); }
  bool remove(const char* path) { writes++; return files.erase(path) > 0; }
  bool remove(const String& path) { return remove(path.c_str()); }
  bool rename(const char* a, const char* b) {
    auto it = files.find(a);
    if (it == files.end()) return false;
    files[b] = it->second; files.erase(it); writes++; return true;
  }
  size_t totalBytes() { return 983040; }
  size_t usedBytes() { size_t n = 0; for (auto& f : files) n += f.second->size(); return n; }
};
extern MemFS LittleFS;   // wled.h: #define WLED_FS LittleFS
#ifndef WLED_FS
#define WLED_FS LittleFS
#endif

// No network: the state code can switch WLED's access point; a virtual device has none.
class WLED { public: static WLED& instance() { static WLED w; return w; } void initAP(bool = false) {} };
struct VirtualDNSServer { void stop() {} };
extern VirtualDNSServer dnsServer;
struct VirtualWiFi { bool softAPdisconnect(bool = false) { return true; } };
extern VirtualWiFi WiFi;
