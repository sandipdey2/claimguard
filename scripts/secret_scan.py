"""Pre-push secret scan: fails if any tracked/staged file looks like it carries a credential.

Checks generic token shapes (OpenAI, GitHub, Azure keys, connection strings, private keys) and, when set, the literal values
of sensitive environment variables (the values are never printed). Run: python scripts/secret_scan.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

PATTERNS = {
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "vocareum_key": r"voc-[A-Za-z0-9_\-]{20,}",
    "github_token": r"(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "azure_conn_string": r"AccountKey=[A-Za-z0-9+/=]{40,}",
    "instrumentation_key": r"InstrumentationKey=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "bearer_literal": r"Bearer [A-Za-z0-9._\-]{30,}",
}
SENSITIVE_ENV = ("OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "AZURE_OPENAI_API_KEY", "AZURE_SEARCH_API_KEY", "AZURE_CONTENT_SAFETY_KEY",
                 "AZURE_STORAGE_CONNECTION_STRING", "CG_RECEIPT_KEY", "CG_API_KEY", "CG_MCP_TOKEN", "APPLICATIONINSIGHTS_CONNECTION_STRING")
FORBIDDEN_PATHS = (r"^\.streamlit/secrets\.toml$", r"^\.env", r"^data/raw/")


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def main() -> int:
    values = [(k, v) for k in SENSITIVE_ENV if (v := os.environ.get(k)) and len(v) >= 12]
    bad: list[str] = []
    for f in files():
        if any(re.search(p, f) for p in FORBIDDEN_PATHS):
            bad.append(f"{f}: forbidden path")
            continue
        try:
            with open(f, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        text = data.decode("utf-8", "ignore")
        for name, pat in PATTERNS.items():
            if re.search(pat, text):
                bad.append(f"{f}: matches {name}")
        for k, v in values:
            if v in text:
                bad.append(f"{f}: contains the value of ${k}")
    for b in bad:
        print("SECRET-SCAN FAIL", b)
    print(f"secret scan: {'FAIL' if bad else 'PASS'} ({len(files())} files)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
