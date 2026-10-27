# Base image updated by Renovate, update versionCompatibility on Debian base bump
ARG BUILD_FROM=ghcr.io/home-assistant/base-debian:trixie-2026.10.1@sha256:e222afd25b64e5e62ac2f155b6f73e930a91967d039e0d22384abb9ef6d47e59
FROM $BUILD_FROM

# Install mosquitto + auth plugin
WORKDIR /usr/src
ARG MOSQUITTO_VERSION=2.1.2
ARG MOSQUITTO_AUTH_VERSION=3.0.0
COPY patches/0001-Fix-builtin-websockets-dropping-the-session-on-an-empty-data-frame.patch /usr/src
RUN apt-get update \
    && apt-get install -qy --no-install-recommends \
        nginx \
        pwgen \
        build-essential \
        git \
        openssl \
        patch \
        libssl-dev \
        libc-ares2 \
        libc-ares-dev \
        libcjson1 \
        libcjson-dev \
        libsqlite3-dev \
        xsltproc \
        docbook-xsl \
        golang-go \
    \
    # Compile and install mosquitto
    && git clone --depth 1 -b "v${MOSQUITTO_VERSION}" \
       https://github.com/eclipse/mosquitto \
    \
    && cd mosquitto \
    # RKf: Mosquitto rejects SUBSCRIBE when the packet id is 0. Some clients send that.
    && grep -q 'if(mid == 0){' src/handle_subscribe.c \
    && sed -i '/if(mid == 0){/,/^[[:space:]]*}/{s|^|// RKf |}' src/handle_subscribe.c \
    && ! grep -E -q '^[[:space:]]*if\(mid == 0\)\{' src/handle_subscribe.c \
    && grep -q '// RKf' src/handle_subscribe.c \
    && patch -p1 < /usr/src/0001-Fix-builtin-websockets-dropping-the-session-on-an-empty-data-frame.patch \
    # Disable editline used by mosquitto_ctrl
    && sed -i 's/^WITH_EDITLINE=yes/#WITH_EDITLINE=yes/' config.mk \
    # Disable REST API
    && sed -i 's/^WITH_HTTP_API=yes/#WITH_HTTP_API=yes/' config.mk \
    && make WITH_WEBSOCKETS=yes WITH_SRV=yes \
    && make install \
    && cd .. \
    # Compile and install mosquitto-go-auth
    && git clone --depth 1 -b "${MOSQUITTO_AUTH_VERSION}" \
       https://github.com/iegomez/mosquitto-go-auth \
    \
    && cd mosquitto-go-auth \
    && sed -i 's/-I\/usr\/local\/include/-I\/usr\/include/' Makefile \
    && sed -i 's/LDFLAGS := .*$/& -Wl,-unresolved-symbols=ignore-all/' Makefile \
    # Fix nil pointer dereference panic in ttlcache
    && sed -i 's/return present, item.Value()/if item == nil { return false, false }\n\treturn true, item.Value()/' cache/cache.go \
    && make \
    && mkdir -p /usr/share/mosquitto \
    && cp -f go-auth.so /usr/share/mosquitto \
    && cp -f pw /usr/local/bin \
    \
    && apt-get purge -y --auto-remove \
        build-essential \
        git \
        patch \
        libssl-dev \
        libc-ares-dev \
        libcjson-dev \
        libsqlite3-dev \
        xsltproc \
        docbook-xsl \
        golang-go \
    && apt-get clean \
    && rm -fr \
        /etc/logrotate.d \
        /etc/mosquitto/* \
        /etc/nginx/* \
        /usr/share/nginx \
        /usr/src/mosquitto \
        /usr/src/mosquitto-go-auth \
        /usr/src/*.patch \
        /var/lib/nginx/html \
        /var/www \
        /var/lib/apt/lists/* \
	/root/.cache \
	/root/go

# Copy rootfs
COPY rootfs /

HEALTHCHECK --start-period=30s --start-interval=5s --interval=30s \
    CMD bash -c '</dev/tcp/127.0.0.1/1883' || exit 1

WORKDIR /

LABEL \
    org.opencontainers.image.title="Home Assistant App: Mosquitto broker" \
    org.opencontainers.image.description="An Open Source MQTT broker" \
    org.opencontainers.image.source="https://github.com/home-assistant/app-mosquitto" \
    org.opencontainers.image.licenses="Apache License 2.0"
