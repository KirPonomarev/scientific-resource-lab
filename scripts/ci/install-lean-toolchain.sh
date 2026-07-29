#!/usr/bin/env bash
set -euo pipefail

TOOLCHAIN="${SRL_A09_LEAN_TOOLCHAIN:-leanprover/lean4:v4.32.2}"
ELAN_HOME="${ELAN_HOME:-$HOME/.elan}"

curl -fsSL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh
sh /tmp/elan-init.sh -y --default-toolchain "$TOOLCHAIN"

export PATH="$ELAN_HOME/bin:$PATH"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$ELAN_HOME/bin" >> "$GITHUB_PATH"
fi

lean --version
lake --version
