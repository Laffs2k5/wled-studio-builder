// SPDX-License-Identifier: EUPL-1.2
// Preloaded into Node (NODE_OPTIONS=--require) while WLED's web UI is built
// (tools/cdata.js), to make the generated headers reproducible:
//
// - WLED_STUDIO_WEB_BUILD_TIME: pins Date.now(), so WEB_BUILD_TIME is the
//   vendor's value instead of the current time.
// - WLED_STUDIO_GZIP_OS: sets the OS byte of every gzip header (RFC 1952,
//   byte 9). Node writes 3 on Unix and 10 on Windows; the compressed data is
//   the same. Lets a Linux build match a Windows vendor build here.
const t = Number(process.env.WLED_STUDIO_WEB_BUILD_TIME);
if (Number.isFinite(t) && t > 0) {
  Date.now = () => t * 1000;
}

const os = process.env.WLED_STUDIO_GZIP_OS;
if (os !== undefined && os !== "") {
  const osByte = Number(os);
  const zlib = require("node:zlib");
  const orig = zlib.gzipSync;
  zlib.gzipSync = function (...args) {
    const buf = orig.apply(this, args);
    if (buf.length > 9 && buf[0] === 0x1f && buf[1] === 0x8b) buf[9] = osByte;
    return buf;
  };
}
