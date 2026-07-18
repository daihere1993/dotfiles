#!/bin/bash
set -euo pipefail

test_directory=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

for test_file in "$test_directory"/test-*.sh; do
  echo "Running $(basename "$test_file")"
  bash "$test_file"
done
