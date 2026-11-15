"""Server-side policy engine: every MCP tools/call is re-validated against contract.json limits (defence in depth: the
client-side hook can be bypassed by any other MCP client). Refusals are counted and exposed at registry://tools."""
from __future__ import annotations

import functools
import json
import time

from .config import load_contract


class ServerPolicy:
    def __init__(self) -> None:
        self.limits = load_contract()["tool_arg_limits"]
        self.counters: dict[str, int] = {}
        self.refusals: list[dict] = []

    def _check(self, tool: str, args: dict) -> str | None:
        for key in ("query", "text"):
            v = args.get(key)
            if isinstance(v, str) and len(v) > (600 if key == "text" else self.limits["query_max_chars"]):
                return f"{key} longer than allowed"
        k = args.get("k")
        lim = self.limits.get(f"{tool}.k_max")
        if k is not None and lim is not None and int(k) > lim:
            return f"k={k} exceeds {tool}.k_max={lim}"
        if tool == "get_imr_case" and args.get("include_outcome"):
            return "include_outcome is not available to agents over MCP (the drafting agents must not see the case decision)"
        return None

    def guard(self, tool: str):
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                self.counters[tool] = self.counters.get(tool, 0) + 1
                reason = self._check(tool, kw)
                if reason:
                    self.refusals.append({"ts": round(time.time(), 3), "tool": tool, "reason": reason})
                    return json.dumps({"error": f"refused by server policy: {reason}"})
                return fn(*a, **kw)
            return wrapper
        return deco
