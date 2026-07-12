#!/bin/sh
# Build the two files consumed by install.sh from a checked-out release tag.
set -eu

OUTPUT_DIR="${1:-dist}"
mkdir -p "$OUTPUT_DIR"
ARCHIVE="$OUTPUT_DIR/octopulse.tar.gz"
tar --exclude='__pycache__' --exclude='*.pyc' -czf "$ARCHIVE" octopulse tools/octopulse.py skills schemas/otcopulse.schema.json README.md
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$OUTPUT_DIR" && sha256sum octopulse.tar.gz > octopulse.sha256)
else
  (cd "$OUTPUT_DIR" && shasum -a 256 octopulse.tar.gz > octopulse.sha256)
fi
