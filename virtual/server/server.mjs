// SPDX-License-Identifier: EUPL-1.2
/**
 * The virtual WLED device: a WLED twin (virtual/build.sh) behind WLED's HTTP JSON API and
 * websocket, so wled-studio (or anything that talks to WLED) can use it as a device.
 *
 *     VIRTUAL_DIR=<twin> node virtual/server/server.mjs
 *
 * WLED's own code does the work: state in and out, presets, playlists, transitions, the effects,
 * the settings PIN (device.cpp). This server is the web server's part: routes, the upload form,
 * the websocket, the files kept between restarts. It uses Node's standard library only.
 *
 * Environment:
 *   VIRTUAL_DIR   the twin: virtual.mjs, virtual.wasm and twin.json (required)
 *   PORT, HOST    where to listen (8080, 0.0.0.0)
 *   LEDS          LEDs per output, comma-separated ("30"); e.g. "124,126" for two outputs
 *   RGBW          1 for RGBW LEDs (default), 0 for RGB
 *   NAME          the device's name ("Virtual WLED")
 *   BOOT_PRESET   the preset to apply at boot (0: none)
 *   PIN_FILE      a file holding the settings PIN (none: no PIN). A file, so the PIN stays out of
 *                 the environment and the logs.
 *   DATA_DIR      where the device's files (presets.json, palettes) are kept between restarts
 *                 (none: in memory only)
 *
 * What it doesn't do: the network side of WLED (sync, realtime input, MQTT, Alexa), its settings
 * pages and web UI (it has a small page of its own at /), and firmware updates (a twin runs the
 * firmware it was built from).
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";

const env = process.env;
const dir = env.VIRTUAL_DIR;
if (!dir) {
  console.error("VIRTUAL_DIR: the folder of a built twin (virtual/build.sh)");
  process.exit(2);
}
const cfg = {
  port: Number(env.PORT || 8080),
  host: env.HOST || "0.0.0.0",
  leds: (env.LEDS || "30").replace(/\s/g, ""),
  rgbw: env.RGBW !== "0",
  name: env.NAME || "Virtual WLED",
  bootPreset: Number(env.BOOT_PRESET || 0),
  pin: env.PIN_FILE ? fs.readFileSync(env.PIN_FILE, "utf8").trim() : "",
  dataDir: env.DATA_DIR || "",
};
if (!/^\d+(,\d+)*$/.test(cfg.leds)) {
  console.error(`LEDS: LEDs per output, comma-separated, e.g. 124,126 (got ${cfg.leds})`);
  process.exit(2);
}
const twin = (() => {
  try { return JSON.parse(fs.readFileSync(path.join(dir, "twin.json"), "utf8")); } catch { return {}; }
})();

// --- the twin --------------------------------------------------------------------------------
const M = await (await import(path.resolve(dir, "virtual.mjs"))).default();
const text = (p) => (p ? M.UTF8ToString(p) : null);
function withString(s, f) {
  const p = M.stringToNewUTF8(s);
  try { return f(p); } finally { M._free(p); }
}
const lenPtr = M._malloc(4);
const fileRead = (name) => withString(name, (p) => {
  const d = M._virtual_file_read(p, lenPtr);
  return d ? Buffer.from(M.HEAPU8.subarray(d, d + M.HEAP32[lenPtr >> 2])) : null;
});
function fileWrite(name, data) {
  const buf = M._malloc(Math.max(1, data.length));
  M.HEAPU8.set(data, buf);
  try { return withString(name, (p) => M._virtual_file_write(p, buf, data.length)); } finally { M._free(buf); }
}
const fileList = () => text(M._virtual_file_list()).split("\n").filter(Boolean);

// the device's files from the last run, before boot: presets, palettes
const safeName = (n) => /^\/?[A-Za-z0-9._-]{1,64}$/.test(n) && !n.includes("..");
if (cfg.dataDir) {
  fs.mkdirSync(cfg.dataDir, { recursive: true });
  for (const f of fs.readdirSync(cfg.dataDir)) {
    if (safeName(f) && !f.endsWith(".tmp")) fileWrite("/" + f, fs.readFileSync(path.join(cfg.dataDir, f)));
  }
}
withString(cfg.pin, (p) => M._virtual_set_pin(p));
const t0 = Date.now();
const now = () => Date.now() - t0;
const leds = withString(cfg.leds, (p) => M._virtual_device_boot(p, cfg.rgbw ? 1 : 0, cfg.bootPreset));

// --- WLED's answers ----------------------------------------------------------------------------
const BUSY = { error: 3 };          // ERR_NOBUF: the JSON buffer is in use
const json = (what) => text(M._virtual_json(what));
const palettes = JSON.parse(text(M._virtual_palette_names()));
function info() {
  const fw = JSON.parse(text(M._virtual_info()) || "{}");
  return {
    ver: twin.ver || "", vid: fw.vid, cn: "", release: twin.release || "", repo: twin.repo || "",
    leds: fw.leds, str: false, name: cfg.name, udpport: 21324, simplifiedui: false,
    live: false, liveseg: -1, lm: "", lip: "", ws: sockets.size,
    fxcount: fw.fxcount, palcount: fw.palcount, cpalcount: fw.cpalcount, cpalmax: fw.cpalmax, maps: [{ id: 0 }],
    wifi: { bssid: "", rssi: 0, signal: 100, channel: 0, ap: false }, fs: fw.fs, ndc: -1,
    arch: "virtual", core: "wasm", clock: 0, flash: 0, lwip: 0, freeheap: 200000,
    uptime: Math.floor(now() / 1000), time: new Date().toISOString(), opt: 0,
    brand: "WLED", product: "Virtual WLED", mac: "000000000000", ip: "",
    // the usermods' part of info: the sound usermod reports itself; the twin simulates its sound
    u: (twin.flags || []).includes("-DUSERMOD_AUDIOREACTIVE") ? { AudioReactive: ["simulated"] } : {},
    virtual: { firmware: twin.firmware || "", wled: twin.wled || "", flags: twin.flags || [], outputs: cfg.leds.split(",").map(Number) },
  };
}

// --- HTTP ---------------------------------------------------------------------------------------
function send(res, code, body, type = "application/json") {
  const data = typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body);
  res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" });
  res.end(data);
}
const page = (res, code, title, sub) =>
  send(res, code, `<!doctype html><html><body><h2>${title}</h2>${sub}</body></html>`, "text/html");
const readBody = (req, limit = 1 << 20) => new Promise((resolve, reject) => {
  const parts = [];
  let n = 0;
  req.on("data", (c) => { n += c.length; if (n > limit) { reject(new Error("too large")); req.destroy(); } else parts.push(c); });
  req.on("end", () => resolve(Buffer.concat(parts)));
  req.on("error", reject);
});

/** The parts of a multipart/form-data body: [{name, filename, data}]. */
function multipart(body, contentType) {
  const m = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType || "");
  if (!m) return [];
  const sep = Buffer.from("--" + (m[1] || m[2]));
  const out = [];
  let at = body.indexOf(sep);
  while (at >= 0) {
    const start = at + sep.length;
    if (body.subarray(start, start + 2).toString() === "--") break;
    const next = body.indexOf(sep, start);
    if (next < 0) break;
    const part = body.subarray(start + 2, next - 2);        // past CRLF, before CRLF
    const headEnd = part.indexOf("\r\n\r\n");
    if (headEnd >= 0) {
      const head = part.subarray(0, headEnd).toString();
      const disp = /content-disposition:[^\r\n]*/i.exec(head)?.[0] || "";
      out.push({
        name: /\bname="([^"]*)"/i.exec(disp)?.[1] || "",
        filename: /\bfilename="([^"]*)"/i.exec(disp)?.[1] || "",
        data: part.subarray(headEnd + 4),
      });
    }
    at = next;
  }
  return out;
}

function cfgJson() {
  const saved = fileRead("/cfg.json");
  if (saved) return saved;
  // a twin has no WLED config code: the part of cfg.json that describes it
  const outs = cfg.leds.split(",").map(Number);
  let start = 0;
  return JSON.stringify({
    id: { name: cfg.name },
    hw: { led: { total: leds, ins: outs.map((len) => { const o = { start, len, type: cfg.rgbw ? 30 : 22 }; start += len; return o; }) } },
    def: { ps: cfg.bootPreset, on: true, bri: 128 },
    ota: { lock: false, "lock-wifi": false, "pin-req": false, aota: false, "same-subnet": false },
  });
}

async function postState(req, res, url) {
  let body;
  try { body = (await readBody(req)).toString("utf8"); } catch { return send(res, 413, { error: 9 }); }
  const r = withString(body || "{}", (p) => M._virtual_post_state(p));
  if (r === -1) return send(res, 400, { error: 9 });
  if (r === -2) return send(res, 200, BUSY);
  if (r === 1) return answerState(res, url);
  return send(res, 200, { success: true });
}
function answerState(res, url) {
  const state = json(0);
  if (state === null) return send(res, 200, BUSY);
  if (url === "/json/state") return send(res, 200, state);
  return send(res, 200, `{"state":${state},"info":${JSON.stringify(info())}}`);
}

async function upload(req, res) {
  let body;
  try { body = await readBody(req, 4 << 20); } catch { return send(res, 413, "Too large", "text/plain"); }
  if (!M._virtual_unlocked()) return page(res, 401, "Access Denied", "Please unlock settings using PIN code!");
  const file = multipart(body, req.headers["content-type"]).find((p) => p.filename);
  if (!file) return send(res, 400, "No file", "text/plain");
  const name = "/" + path.posix.basename(file.filename.replace(/\\/g, "/"));
  if (!safeName(name) || name.includes("sec")) return send(res, 400, "Bad file name", "text/plain");
  fileWrite(name, file.data);
  if (name === "/cfg.json") return send(res, 200, "Config restore ok.\nRebooting...", "text/plain");
  return send(res, 200, "File Uploaded!", "text/plain");
}

async function handle(req, res) {
  const u = new URL(req.url, "http://virtual");
  const p = u.pathname.replace(/\/+$/, "") || "/";
  const get = req.method === "GET" || req.method === "HEAD";
  if (req.method === "OPTIONS") return send(res, 204, "");
  if (get) {
    switch (p) {
      case "/": return send(res, 200, HOME, "text/html");
      case "/version": return send(res, 200, String(JSON.parse(text(M._virtual_info())).vid), "text/plain");
      case "/json/info": return send(res, 200, info());
      case "/json/state": return answerState(res, p);
      case "/json/si": return answerState(res, p);
      case "/json/eff": return send(res, 200, json(1) ?? BUSY);
      case "/json/fxdata": return send(res, 200, json(2) ?? BUSY);
      case "/json/pal": return send(res, 200, palettes);
      case "/json": {
        const state = json(0);
        if (state === null) return send(res, 200, BUSY);
        return send(res, 200, `{"state":${state},"info":${JSON.stringify(info())},"effects":${json(1)},"palettes":${JSON.stringify(palettes)}}`);
      }
      case "/cfg.json": return send(res, 200, cfgJson());
      case "/settings/lock":
        M._virtual_lock();
        return page(res, 200, cfg.pin ? "Settings locked" : "No PIN set", "Redirecting...");
      case "/update":
        if (!M._virtual_unlocked()) return page(res, 401, "Access Denied", "Please unlock settings using PIN code!");
        if (u.searchParams.has("revert")) return page(res, 500, "Rollback failed!", "A virtual device has no other firmware to go back to.");
        return page(res, 200, "WLED Software Update", "A virtual device runs the firmware it was built from.");
    }
    if (p.startsWith("/json/")) return send(res, 501, { error: 4 });
    // WLED serves any file from its file system, except the secrets (file.cpp, handleFileRead)
    if (!p.includes("sec") && safeName(p)) {
      const f = fileRead(p);
      if (f) return send(res, 200, f, p.endsWith(".json") ? "application/json" : "application/octet-stream");
    }
    return send(res, 404, "Not Found", "text/plain");
  }
  if (req.method === "POST") {
    if (p === "/json/state" || p === "/json/si" || p === "/json") return postState(req, res, p);
    if (p === "/json/cfg") return send(res, 501, { error: 4 });   // a twin has no WLED config code
    if (p === "/upload") return upload(req, res);
    if (p === "/update") {
      req.resume();
      if (!M._virtual_unlocked()) return page(res, 401, "Access Denied", "Please unlock settings using PIN code!");
      return page(res, 500, "Update failed!", "A virtual device runs the firmware it was built from: build another twin.");
    }
  }
  return send(res, 405, "Method Not Allowed", "text/plain");
}

// --- the websocket: WLED's /ws (state pushes, commands, the live view) -------------------------
const sockets = new Set();
let liveSocket = null;      // WLED serves its live view to one client: the last to ask

function frame(op, payload) {
  const n = payload.length;
  const head = n < 126 ? Buffer.from([0x80 | op, n])
    : n < 65536 ? Buffer.from([0x80 | op, 126, n >> 8, n & 255])
      : (() => { const b = Buffer.alloc(10); b[0] = 0x80 | op; b[1] = 127; b.writeBigUInt64BE(BigInt(n), 2); return b; })();
  return Buffer.concat([head, payload]);
}
const wsSend = (s, data) => { if (!s.destroyed) s.write(frame(typeof data === "string" ? 1 : 2, typeof data === "string" ? Buffer.from(data) : data)); };
function stateAndInfo() {
  const state = json(0);
  return state === null ? null : `{"state":${state},"info":${JSON.stringify(info())}}`;
}
function onMessage(s, msg) {
  let obj;
  try { obj = JSON.parse(msg); } catch { return; }
  if (!obj || typeof obj !== "object") return;
  if ("lv" in obj) {
    if (obj.lv) liveSocket = s;
    else if (liveSocket === s) liveSocket = null;
    return;
  }
  const r = withString(msg, (p) => M._virtual_post_state(p));
  if (r === 1) { const si = stateAndInfo(); if (si) wsSend(s, si); }
}

function upgrade(req, socket) {
  const key = req.headers["sec-websocket-key"];
  if (new URL(req.url, "http://virtual").pathname !== "/ws" || !key) { socket.destroy(); return; }
  const accept = crypto.createHash("sha1").update(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
  socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
    `Sec-WebSocket-Accept: ${accept}\r\n\r\n`);
  socket.setNoDelay(true);
  sockets.add(socket);
  let buf = Buffer.alloc(0);
  let pieces = [];
  socket.on("data", (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const fin = buf[0] & 0x80, op = buf[0] & 0x0f, masked = buf[1] & 0x80;
      let len = buf[1] & 0x7f, at = 2;
      if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); at = 4; }
      else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); at = 10; }
      if (len > 1 << 20) { socket.destroy(); return; }
      const mask = masked ? buf.subarray(at, at + 4) : null;
      if (masked) at += 4;
      if (buf.length < at + len) return;
      const payload = Buffer.from(buf.subarray(at, at + len));
      if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];
      buf = buf.subarray(at + len);
      if (op === 8) { socket.end(frame(8, Buffer.alloc(0))); return; }
      if (op === 9) { socket.write(frame(10, payload)); continue; }
      if (op === 10) continue;
      pieces.push(payload);
      if (fin) { const msg = Buffer.concat(pieces).toString("utf8"); pieces = []; onMessage(socket, msg); }
    }
  });
  const gone = () => { sockets.delete(socket); if (liveSocket === socket) liveSocket = null; };
  socket.on("close", gone);
  socket.on("error", gone);
  const si = stateAndInfo();     // WLED greets a new client with its state and info
  if (si) wsSend(socket, si);
}

// --- WLED's loop, the pushes, the live view, the files ----------------------------------------
let pushes = M._virtual_ws_pushes();
let lastLive = 0;
let fsWrites = M._virtual_file_writes();
let lastSave = 0;
function saveFiles() {
  if (!cfg.dataDir) return;
  const names = fileList();
  for (const n of names) {
    if (!safeName(n)) continue;
    const target = path.join(cfg.dataDir, n.replace(/^\//, ""));
    const data = fileRead(n);
    let old = null;
    try { old = fs.readFileSync(target); } catch { /* new file */ }
    if (old && old.equals(data)) continue;
    fs.writeFileSync(target + ".tmp", data);
    fs.renameSync(target + ".tmp", target);
  }
  for (const f of fs.readdirSync(cfg.dataDir)) {
    if (safeName(f) && !f.endsWith(".tmp") && !names.includes("/" + f)) fs.unlinkSync(path.join(cfg.dataDir, f));
  }
}
const timer = setInterval(() => {
  const t = now();
  M._virtual_loop(t >>> 0);
  const p = M._virtual_ws_pushes();
  if (p !== pushes && sockets.size) {
    const si = stateAndInfo();
    if (si) for (const s of sockets) wsSend(s, si);
  }
  pushes = p;
  if (liveSocket && t - lastLive >= 40) {     // WS_LIVE_INTERVAL
    lastLive = t;
    const d = M._virtual_live(lenPtr);
    wsSend(liveSocket, Buffer.from(M.HEAPU8.subarray(d, d + M.HEAP32[lenPtr >> 2])));
  }
  const w = M._virtual_file_writes();
  if (w !== fsWrites && t - lastSave >= 1000) {
    fsWrites = w;
    lastSave = t;
    try { saveFiles(); } catch (e) { console.error("saving the device's files:", e.message); }
  }
}, 5);

const HOME = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Virtual WLED</title><style>
:root{color-scheme:light dark;--bg:#fff;--fg:#222;--muted:#666}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--muted:#999}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif}
canvas{width:100%;height:28px;image-rendering:pixelated;border-radius:4px;background:#000}
small{color:var(--muted)}</style></head><body>
<h2 id="name">Virtual WLED</h2><p><small id="what"></small></p><canvas id="c" height="1"></canvas>
<p><small>A twin of a WLED firmware, running WLED's own code. Its API is WLED's: /json, /json/state, /presets.json, /ws.</small></p>
<script>
const c=document.getElementById("c"),x=c.getContext("2d");
fetch("/json/info").then(r=>r.json()).then(i=>{document.getElementById("name").textContent=i.name;
document.getElementById("what").textContent=(i.virtual.firmware||"WLED "+i.ver)+" · "+i.leds.count+" LEDs · outputs "+i.virtual.outputs.join(" + ");});
const ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws");ws.binaryType="arraybuffer";
ws.onopen=()=>ws.send('{"lv":true}');
ws.onmessage=e=>{if(typeof e.data==="string")return;const b=new Uint8Array(e.data);if(b[0]!==76)return;const n=(b.length-2)/3;
if(c.width!==n)c.width=n;const img=x.createImageData(n,1);for(let i=0;i<n;i++){img.data.set([b[2+3*i],b[3+3*i],b[4+3*i],255],4*i);}x.putImageData(img,0,0);};
</script></body></html>`;

const server = http.createServer((req, res) => {
  handle(req, res).catch((e) => { console.error(e); if (!res.headersSent) send(res, 500, { error: 0 }); });
});
server.on("upgrade", upgrade);
server.listen(cfg.port, cfg.host, () => {
  console.log(`virtual WLED "${cfg.name}" on ${cfg.host}:${cfg.port}: ${leds} LEDs (${cfg.leds}), ` +
    `${twin.firmware || "WLED " + (twin.ver || "?")}${cfg.pin ? ", PIN set" : ""}${cfg.dataDir ? ", files in " + cfg.dataDir : ""}`);
});
function stop() {
  clearInterval(timer);
  try { saveFiles(); } catch { /* best effort */ }
  server.close();
  for (const s of sockets) s.destroy();
  process.exit(0);
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
