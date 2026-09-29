#!/bin/sh
set -eu

exec python3 -m projectos.acceptance_host "$@"
