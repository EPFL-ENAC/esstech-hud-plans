#!/usr/bin/env bash
set -euo pipefail

# script executes a command string through a shell. Quote each argument for Bash.
printf -v brush_command '%q ' /external/bin/brush "$@"
SHELL=/bin/bash script -qefc "$brush_command" /dev/null \
  | stdbuf -o0 tr '\r' '\n'
