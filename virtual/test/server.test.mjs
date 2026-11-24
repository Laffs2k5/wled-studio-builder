// SPDX-License-Identifier: EUPL-1.2
// The virtual device server against a built twin: WLED's API as a client sees it.
//   VIRTUAL_DIR=<twin> node --test virtual/test/server.test.mjs
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const dir = process.env.VIRTUAL_DIR;
const server = new URL("../server/server.mjs", import.meta.url).pathname;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "virtual-server-"));
const pinFile = path.join(tmp, "pin");
const dataDir = path.join(tmp, "data");
fs.writeFileSync(pinFile, "4321\n");
const PORT = 18000 + Math.floor(Math.random() * 1000);
const B = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let proc;

async function start() {
  proc = spawn(process.execPath, [server], {
    env: { ...process.env, VIRTUAL_DIR: dir, PORT: String(PORT), HOST: "127.0.0.1", LEDS: "12,8", NAME: "Test twin",
           PIN_FILE: pinFile, DATA_DIR: dataDir },
    stdio: ["ignore", "pipe", "inherit"],
  });
  await new Promise((resolve, reject) => {
    proc.stdout.on("data", (d) => { if (String(d).includes("virtual WLED")) resolve(); });
    proc.on("exit", (c) => reject(new Error(`server exited ${c}`)));
  });
}
async function stop() {
  const done = new Promise((r) => proc.on("exit", r));
  proc.kill("SIGTERM");
  await done;
}
const get = async (p) => (await fetch(B + p)).json();
const post = async (p, body) => fetch(B + p, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) });
function upload(name, content) {
  const form = new FormData();
  form.append("data", new Blob([content]), name);
  return fetch(B + "/upload", { method: "POST", body: form });
}

before(async () => {
  if (!dir) return;
  await start();
});
after(async () => {
  if (proc && proc.exitCode === null) await stop();
  fs.rmSync(tmp, { recursive: true, force: true });
});

test("info: the twin's firmware, the outputs, no flashing arch", { skip: !dir && "no VIRTUAL_DIR" }, async () => {
  const i = await get("/json/info");
  assert.equal(i.name, "Test twin");
  assert.equal(i.arch, "virtual");
  assert.equal(i.leds.count, 20);
  assert.deepEqual(i.virtual.outputs, [12, 8]);
  assert.ok(i.vid > 0 && i.fxcount > 100 && i.palcount > 50);
  const [eff, fxdata, pal] = await Promise.all([get("/json/eff"), get("/json/fxdata"), get("/json/pal")]);
  assert.equal(eff.length, i.fxcount);
  assert.equal(fxdata.length, eff.length);
  assert.equal(pal.length, i.palcount);
  assert.equal(eff[0], "Solid");
});

test("state: boots orange at 128; changes go through WLED's own code", { skip: !dir && "no VIRTUAL_DIR" }, async () => {
  const s = await get("/json/state");
  assert.equal(s.on, true);
  assert.equal(s.bri, 128);
  assert.deepEqual(s.seg[0].col[0].slice(0, 3), [255, 160, 0]);
  const r = await (await post("/json/state", { bri: 40, seg: [{ id: 0, fx: 9, sx: 200 }], v: true })).json();
  assert.equal(r.bri, 40);
  assert.equal(r.seg[0].fx, 9);
  assert.deepEqual(await (await post("/json/state", { bri: 41 })).json(), { success: true });
  // WLED's increment syntax, parsed by its getVal
  assert.equal((await (await post("/json/state", { bri: "~10", v: true })).json()).bri, 51);
  const bad = await post("/json/state", "nope");
  assert.equal(bad.status, 400);
  assert.deepEqual(await bad.json(), { error: 9 });
});

test("the PIN guards uploads; presets and playlists run as on WLED", { skip: !dir && "no VIRTUAL_DIR" }, async () => {
  const presets = {
    0: {}, 21: { n: "Calm", on: true, bri: 60, seg: [{ id: 0, fx: 0 }] },
    22: { n: "Fire", on: true, bri: 90, seg: [{ id: 0, fx: 66 }] },
    30: { n: "Both", playlist: { ps: [21, 22], dur: [5, 5], transition: [0, 0], repeat: 0 } },
  };
  assert.equal((await upload("presets.json", JSON.stringify(presets))).status, 401);
  await post("/json/state", { pin: "0000" });                    // wrong: still locked
  assert.equal((await upload("presets.json", "{}")).status, 401);
  await sleep(3100);                                              // WLED ignores a PIN check within 3 s
  await post("/json/state", { pin: "4321" });
  assert.equal((await upload("/presets.json", JSON.stringify(presets))).status, 200);
  assert.deepEqual(Object.keys(await get("/presets.json")).sort(), ["0", "21", "22", "30"]);
  await post("/json/state", { ps: 30 });
  await sleep(200);
  let s = await get("/json/state");
  assert.equal(s.pl, 30);
  assert.equal(s.ps, 21);
  await sleep(700);
  s = await get("/json/state");
  assert.equal(s.ps, 22);
  assert.equal(s.seg[0].fx, 66);
  // picking an effect by hand ends the playlist (json.cpp)
  assert.equal((await (await post("/json/state", { seg: [{ id: 0, fx: 0 }], v: true })).json()).pl, -1);
  // WLED saves a preset itself
  await post("/json/state", { psave: 40, n: "Saved here" });
  await sleep(100);
  assert.equal((await get("/presets.json"))["40"].n, "Saved here");
  // secrets aren't served; the lock locks
  assert.equal((await fetch(B + "/wsec.json")).status, 404);
  await fetch(B + "/settings/lock");
  assert.equal((await upload("presets.json", "{}")).status, 401);
  // no firmware updates on a twin
  const form = new FormData();
  form.append("update", new Blob([new Uint8Array([0xe9, 0, 0])]), "firmware.bin");
  assert.equal((await fetch(B + "/update", { method: "POST", body: form })).status, 401);
});

test("the websocket: greeting, pushes, commands, the live view", { skip: !dir && "no VIRTUAL_DIR" }, async () => {
  const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`);
  ws.binaryType = "arraybuffer";
  const texts = [], frames = [];
  ws.onmessage = (e) => (typeof e.data === "string" ? texts : frames).push(e.data);
  await new Promise((r) => (ws.onopen = r));
  await sleep(100);
  assert.ok(JSON.parse(texts[0]).state && JSON.parse(texts[0]).info);
  ws.send('{"lv":true}');
  await sleep(300);
  const f = new Uint8Array(frames.at(-1));
  assert.equal(String.fromCharCode(f[0]), "L");
  assert.equal(f[1], 1);
  assert.equal(f.length, 2 + 20 * 3);
  await post("/json/state", { bri: 99 });
  // WLED pushes at most once a second (led.cpp, INTERFACE_UPDATE_COOLDOWN)
  for (let i = 0; i < 30 && !texts.some((t) => JSON.parse(t).state.bri === 99); i++) await sleep(100);
  assert.ok(texts.some((t) => JSON.parse(t).state.bri === 99), "a state change is pushed");
  ws.send('{"bri":98,"v":true}');
  await sleep(200);
  assert.equal(JSON.parse(texts.at(-1)).state.bri, 98);
  ws.close();
});

test("the device's files outlast a restart", { skip: !dir && "no VIRTUAL_DIR" }, async () => {
  await sleep(1200);                    // the server saves changed files once a second
  await stop();
  assert.ok(fs.existsSync(path.join(dataDir, "presets.json")));
  await start();
  const p = await get("/presets.json");
  assert.equal(p["22"].n, "Fire");
  assert.equal(p["40"].n, "Saved here");
});
