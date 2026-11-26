#!/bin/sh
set -eu
exec curl --fail-with-body --silent --show-error --request POST \
  "${SEEDVC_URL:-http://127.0.0.1:7860}/api/models/unload"
