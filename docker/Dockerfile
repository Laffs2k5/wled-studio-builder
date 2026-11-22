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

ARG NODE_VERSION=22.23.5
ARG PLATFORMIO_VERSION=6.2.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 python3-venv xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node from the official tarball, pinned by version (checked against SHASUMS256)
RUN set -eu; arch=x64; \
    cd /tmp; \
    curl -fsSLO https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz; \
    curl -fsSLO https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt; \
    grep " node-v${NODE_VERSION}-linux-${arch}.tar.xz\$" SHASUMS256.txt | sha256sum -c -; \
    tar -xJf node-v${NODE_VERSION}-linux-${arch}.tar.xz -C /usr/local --strip-components=1; \
    rm -f node-v*.tar.xz SHASUMS256.txt; \
    node --version

RUN useradd --create-home --uid 10001 builder
USER builder
WORKDIR /home/builder

RUN python3 -m venv /home/builder/venv \
 && /home/builder/venv/bin/pip install --no-cache-dir platformio==${PLATFORMIO_VERSION}
ENV PATH=/home/builder/venv/bin:$PATH

COPY --chown=builder:builder pins/ /home/builder/studio-src/pins/
COPY --chown=builder:builder studio/ /home/builder/studio-src/studio/

# /work holds the WLED checkout and PlatformIO's packages (a volume, reused
# between runs); /out receives firmware.bin, firmware.elf and build-report.json.
VOLUME ["/work", "/out"]
ENTRYPOINT ["/home/builder/venv/bin/python", "/home/builder/studio-src/studio/build.py"]
CMD ["/home/builder/studio-src/pins/quinled-dig-next-2-16.0.1.json", "--work", "/work", "--out", "/out"]
