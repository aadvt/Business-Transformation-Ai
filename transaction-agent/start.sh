#!/usr/bin/env bash
# Railway start command, shared by both services deployed from this repo.
# Which app actually runs is picked by the SERVICE_ROLE variable set per
# Railway service ("api" or "voice") — see README's "Deployment" section.
set -euo pipefail

if [ "${SERVICE_ROLE:-api}" = "voice" ]; then
    exec uvicorn voice.adapter:app --host 0.0.0.0 --port "${PORT:-8100}"
else
    exec uvicorn api:app --host 0.0.0.0 --port "${PORT:-8000}"
fi
