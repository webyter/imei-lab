#!/usr/bin/env bash
# Start the IMEI Lab webapp.
#   ./run.sh              -> http://127.0.0.1:8000
#   ./run.sh 9000         -> custom port
#   HOST=0.0.0.0 ./run.sh -> expose on the network
set -euo pipefail
cd "$(dirname "$0")"
exec python3 imei_server.py --host "${HOST:-127.0.0.1}" --port "${1:-${PORT:-8000}}"
