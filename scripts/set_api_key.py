from __future__ import annotations

import argparse
from ai_core.config.io import read_json, write_json
from ai_core.config.paths import RUNTIME_SECRETS_DIR
from ai_core.bootstrap.runtime_bootstrap import RuntimeBootstrap

parser = argparse.ArgumentParser()
parser.add_argument("--provider", required=True)
parser.add_argument("--key", required=True)
args = parser.parse_args()
RuntimeBootstrap().ensure_runtime_base()
path = RUNTIME_SECRETS_DIR / "local_secrets.json"
data = read_json(path, {"providers": {}})
data.setdefault("providers", {})[args.provider] = {"api_key": args.key}
write_json(path, data)
print(f"Saved key for {args.provider} into {path}")
