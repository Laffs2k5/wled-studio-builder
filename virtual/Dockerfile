# The virtual WLED device: a twin of a WLED firmware (virtual/build.sh: WLED's own code, compiled
# to WebAssembly) behind WLED's HTTP JSON API and websocket (virtual/server).
#
#   docker build -f virtual/Dockerfile -t wled-virtual .
#   docker run --rm -p 8082:8080 -e LEDS=124,126 wled-virtual
#
# The twin is of the firmware the pins file describes (default: QuinLED's 16.0.1), built with that
# board's effect flags. With your own usermods (custom effects), add them as a named build context:
# one usermod (a folder of .cpp files), or a folder of usermod folders:
#
#   docker build -f virtual/Dockerfile --build-context usermods=../wled-studio-effects .
#
# Pinned: the base image by digest, Node by version and sha256, Emscripten by version, WLED by
# commit (from the pins file). The build needs outbound HTTPS to github.com, nodejs.org and
# Emscripten's download servers (storage.googleapis.com); the running device needs no network.

# --- usermods: none unless a build context named "usermods" replaces this stage ----------------
FROM scratch AS usermods

# --- the twin ---------------------------------------------------------------------------------
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS twin
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 xz-utils \
 && rm -rf /var/lib/apt/lists/*
ARG EMSDK_VERSION=7.0.1
RUN git clone --depth 1 https://github.com/emscripten-core/emsdk.git /emsdk \
 && /emsdk/emsdk install "$EMSDK_VERSION" \
 && /emsdk/emsdk activate "$EMSDK_VERSION" \
 && rm -rf /emsdk/downloads
SHELL ["/bin/bash", "-c"]
ARG PINS=pins/quinled-16.0.1.json
COPY pins/ /src/pins/
RUN set -eu; \
    read -r repo commit < <(python3 -c 'import json, sys; w = json.load(open(sys.argv[1]))["wled"]; print(w["repo"], w["commit"])' "/src/$PINS"); \
    git init -q /wled; \
    git -C /wled fetch -q --depth 1 "$repo" "$commit"; \
    git -C /wled checkout -q FETCH_HEAD
COPY virtual/ /src/virtual/
COPY preview/ /src/preview/
COPY --from=usermods / /usermods/
# the Dig-Next-2's flags that shape the effect engine (the gate takes them from the build)
ARG VIRTUAL_FLAGS="-DUSERMOD_AUDIOREACTIVE -DWLED_PS_DONT_REPLACE_FX -DWLED_ENABLE_GIF -DBOARD_HAS_PSRAM"
ARG TWIN_NAME="QuinLED Dig-Next-2, WLED 16.0.1"
RUN set -eu; \
    source /emsdk/emsdk_env.sh > /dev/null 2>&1; \
    mods=(); \
    if compgen -G "/usermods/*.cpp" > /dev/null; then mods=(/usermods); \
    else for d in /usermods/*/; do [ -d "$d" ] && compgen -G "$d*.cpp" > /dev/null && mods+=("${d%/}"); done; fi; \
    VIRTUAL_FLAGS="$VIRTUAL_FLAGS" TWIN_NAME="$TWIN_NAME" bash /src/virtual/build.sh /out /wled "${mods[@]}"; \
    mkdir /twin && cp /out/virtual.mjs /out/virtual.wasm /out/twin.json /twin/

# --- the device ---------------------------------------------------------------------------------
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
LABEL org.opencontainers.image.title="wled-virtual" \
      org.opencontainers.image.description="A virtual WLED device: WLED's own code, compiled to WebAssembly, behind WLED's API"
# Node from the official tarball, checked against sha256s hard-coded here (as docker/Dockerfile);
# only its binary is kept, and the tools that fetched it go again in the same layer
ARG NODE_VERSION=22.23.5
ARG TARGETARCH
ARG NODE_SHA256_X64=cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8
ARG NODE_SHA256_ARM64=2babb9eb5264860d540849f4b064a6fbdebcdc323657d9d382ce23d313fd5e09
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) arch=x64;   sum="$NODE_SHA256_X64" ;; \
      arm64) arch=arm64; sum="$NODE_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-unknown}" >&2; exit 1 ;; \
    esac; \
    cd /tmp; \
    f="node-v${NODE_VERSION}-linux-${arch}.tar.xz"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/${f}"; \
    echo "${sum}  ${f}" | sha256sum -c -; \
    tar -xJf "$f" -C /usr/local --strip-components=1 --wildcards '*/bin/node'; \
    rm -f "$f"; \
    apt-get purge -y curl xz-utils; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    node --version
RUN useradd --uid 10001 --no-create-home --home-dir /nonexistent device \
 && mkdir /data && chown device:device /data
COPY --from=twin /twin/ /twin/
COPY virtual/server/server.mjs /app/server.mjs
USER device
# DATA_DIR keeps the device's files (presets, palettes) between restarts: mount a volume there,
# writable by uid 10001. The settings PIN, if any, comes from a file (PIN_FILE): a secret.
ENV VIRTUAL_DIR=/twin DATA_DIR=/data PORT=8080 HOST=0.0.0.0
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["node", "-e", "fetch('http://127.0.0.1:8080/json/info').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
ENTRYPOINT ["node", "/app/server.mjs"]
