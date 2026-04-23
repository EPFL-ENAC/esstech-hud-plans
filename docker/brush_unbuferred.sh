#!/usr/bin/env bash

script -qefc "/external/bin/brush $*" /dev/null \
  | stdbuf -o0 tr '\r' '\n'
