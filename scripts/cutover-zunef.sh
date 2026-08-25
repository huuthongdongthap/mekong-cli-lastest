#!/bin/bash
# Cutover env to Zunef cloud direct. Run AFTER storing token in Keychain:
#   security add-generic-password -s mekong-zunef -a $USER -w <TOKEN>
set -euo pipefail
S="$HOME/.claude/settings.json"

# Verify keychain entry exists
security find-generic-password -s mekong-zunef -w > /dev/null 2>&1 || {
  echo "ERROR: no keychain entry 'mekong-zunef'. Store token first:"
  echo "  security add-generic-password -s mekong-zunef -a \$USER -w <TOKEN>"
  exit 1
}

python3 - "$S" << 'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d['env']['ANTHROPIC_BASE_URL'] = 'https://claude-api.zunef.com/v1/ai'
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
print('env.ANTHROPIC_BASE_URL -> zunef cloud')
PY

echo "Cutover complete. Rollback: edit settings.json ANTHROPIC_BASE_URL back to http://localhost:20128"
