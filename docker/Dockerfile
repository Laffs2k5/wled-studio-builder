# wled-studio builder: reproduces pinned WLED builds (studio/build.py).
#
# Pinned: the base image by digest, Node and PlatformIO by version. The ESP32
# toolchain itself is downloaded by PlatformIO at build time, at the versions
# WLED's platformio.ini pins.
#
# Runs as an unprivileged user. Needs outbound HTTPS to github.com,
# raw.githubusercontent.com, objects.githubusercontent.com, the PlatformIO
# registry (api.registry.platformio.org, dl.registry.platformio.org) and
# registry.npmjs.org. Nothing else.
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

LABEL org.opencontainers.image.title="wled-studio-builder" \
      org.opencontainers.image.description="Reproducible, verifiable WLED firmware builds"

ARG NODE_VERSION=22.23.5
ARG PLATFORMIO_VERSION=6.2.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 python3-venv xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node from the official tarball, checked against sha256s hard-coded here (taken
# from nodejs.org's SHASUMS256.txt on 2026-11-22), so a substituted download on
# the same server would still fail.
ARG TARGETARCH
ARG NODE_SHA256_X64=cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8
ARG NODE_SHA256_ARM64=2babb9eb5264860d540849f4b064a6fbdebcdc323657d9d382ce23d313fd5e09
RUN set -eu; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) arch=x64;   sum="$NODE_SHA256_X64" ;; \
      arm64) arch=arm64; sum="$NODE_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-unknown}" >&2; exit 1 ;; \
    esac; \
    cd /tmp; \
    f="node-v${NODE_VERSION}-linux-${arch}.tar.xz"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/${f}"; \
    echo "${sum}  ${f}" | sha256sum -c -; \
    tar -xJf "$f" -C /usr/local --strip-components=1; \
    rm -f "$f"; \
    node --version

RUN useradd --create-home --uid 10001 builder
USER builder
WORKDIR /home/builder

RUN python3 -m venv /home/builder/venv \
 && /home/builder/venv/bin/pip install --no-cache-dir platformio==${PLATFORMIO_VERSION}
ENV PATH=/home/builder/venv/bin:$PATH
# WLED's UI build needs no npm install scripts; don't run 66 packages' scripts
ENV NPM_CONFIG_IGNORE_SCRIPTS=true \
    WLED_STUDIO_CONTAINER=1

# The bundled pins are a default; mount your own and pass its path to use others.
COPY --chown=builder:builder pins/ /home/builder/studio-src/pins/
COPY --chown=builder:builder studio/ /home/builder/studio-src/studio/
COPY --chown=builder:builder tests/ /home/builder/studio-src/tests/

# Both volumes must be writable by uid 10001 (chown them on the host first).
# /work holds the WLED checkout and PlatformIO's packages (a volume, reused
# between runs); /out receives firmware.bin, firmware.elf and build-report.json.
VOLUME ["/work", "/out"]
ENTRYPOINT ["/home/builder/venv/bin/python", "/home/builder/studio-src/studio/build.py"]
CMD ["/home/builder/studio-src/pins/quinled-16.0.1.json", "--target", "dig-next-2", "--check", "--work", "/work", "--out", "/out"]
