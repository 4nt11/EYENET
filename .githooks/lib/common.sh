#!/usr/bin/env bash
# Shared helpers for EYENET git hooks.

if [[ -t 1 ]]; then
  C_RESET='\033[0m'
  C_BOLD='\033[1m'
  C_GREEN='\033[32m'
  C_YELLOW='\033[33m'
  C_RED='\033[31m'
  C_CYAN='\033[36m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_CYAN=''
fi

step() {
  printf "${C_CYAN}${C_BOLD}▸ %s${C_RESET}\n" "$*"
}

ok() {
  printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"
}

warn() {
  printf "${C_YELLOW}! %s${C_RESET}\n" "$*"
}

abort() {
  printf "${C_RED}${C_BOLD}✗ %s${C_RESET}\n" "$*" >&2
  exit 1
}

# Run a tool only if installed, else abort with install hint.
require() {
  local tool="$1"
  command -v "$tool" >/dev/null 2>&1 || abort "missing tool: $tool — run: uv sync --extra dev"
}
