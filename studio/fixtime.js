// Preloaded into Node (NODE_OPTIONS=--require) so WLED's UI build stamps a fixed
// WEB_BUILD_TIME instead of the current time. Only Date.now() is pinned.
const t = Number(process.env.WLED_STUDIO_WEB_BUILD_TIME);
if (Number.isFinite(t) && t > 0) {
  Date.now = () => t * 1000;
}
