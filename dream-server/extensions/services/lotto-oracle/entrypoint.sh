#!/bin/sh
# Dream Server — lotto-oracle entrypoint
#
# Bind-mounted /data inherits owner from the host (typically root after a
# fresh `docker compose up`). The app runs as UID 1000 (dreamer) and
# writes the SQLite store under /data, so we chown /data on every start
# before dropping privileges.

set -e

if [ "$(id -u)" = "0" ]; then
    chown -R dreamer:dreamer /data || true
    exec gosu dreamer:dreamer "$@"
fi

exec "$@"

