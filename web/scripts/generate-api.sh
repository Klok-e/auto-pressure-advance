#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
schema_file="$(mktemp)"
trap 'rm -f "$schema_file"' EXIT
python_cmd="${API_PYTHON:-../.venv/bin/python}"
python_cmd="$(cd "$(dirname "$python_cmd")" && pwd -P)/$(basename "$python_cmd")"
PYTHONPATH=../services/api "$python_cmd" -c 'import json; from app import app; print(json.dumps(app.openapi()))' > "$schema_file"
./node_modules/.bin/openapi-typescript "$schema_file" -o src/app/api.generated.ts
