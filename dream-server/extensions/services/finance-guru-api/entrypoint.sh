#!/bin/sh
# Dream Server — finance-guru-api entrypoint
#
# Bind-mounted /data inherits its owner from the host filesystem
# (typically root after a fresh `docker compose up`). The application
# runs as UID 1000 (dreamer) and writes its SQLite paper-trade ledger
# under /data, so we must chown /data on every start before dropping
# privileges.
#
# We deliberately keep this in a separate script (rather than inline in
# CMD) so a future operator can `docker exec` into the container without
# having to re-create the chown by hand.

set -e

if [ "$(id -u)" = "0" ]; then
    chown -R dreamer:dreamer /data || true
    exec gosu dreamer:dreamer "$@"
fi

exec "$@"

