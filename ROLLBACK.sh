#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
  printf '%s\n' 'Usage: ROLLBACK.sh EXISTING_TARGET_COPY_DIRECTORY' >&2
  exit 2
fi
FILES=(app.py core.py proxy_capture.py)
HASHES=(b18ccc142b4c01ded1f590670795ba6a7fc6f65b3c4fe8b2577f1cd6c08f3624 1dda7f14fa8bc337effc36df73493e9a49701625c30e1d4603258735c4006d2a eb826aa1b0e85afc59783ad5b4e4ccb9d2946f8c45c2c6167c3c98daa4aed068)
for i in 0 1 2; do
  SRC="$HERE/evidence/v7/${FILES[$i]}"
  test "$(sha256sum "$SRC" | cut -d ' ' -f 1)" = "${HASHES[$i]}"
  cp -- "$SRC" "$1/${FILES[$i]}"
  test "$(sha256sum "$1/${FILES[$i]}" | cut -d ' ' -f 1)" = "${HASHES[$i]}"
done
printf '%s\n' 'ROLLBACK_OK: v7 app/core/proxy SHA256 restored'
