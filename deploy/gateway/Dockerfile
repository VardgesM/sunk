FROM caddy:2-alpine
# Match the previous certificate owner and use high ports without Linux capabilities.
RUN setcap -r /usr/bin/caddy && mkdir -p /data /config \
    && chown -R 1000:1000 /data /config
USER 1000:1000
