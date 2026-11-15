"""MCP client: launches the ClaimGuard server over stdio (subprocess, same interpreter) or connects over streamable HTTP
(CG_MCP_URL, e.g. the Container Apps sidecar). LLM keys and other secrets are removed from the child's environment."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "claimguard_mcp_server.py"
_SECRET_PREFIXES = ("OPENAI", "AZURE_OPENAI", "CG_RECEIPT", "GH_", "GITHUB", "AWS", "ANTHROPIC", "CG_API_KEY")


def server_params() -> StdioServerParameters:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_SECRET_PREFIXES)}
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


@asynccontextmanager
async def stdio_session():
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def http_session(url: str, token: str | None = None):
    from mcp.client.streamable_http import streamablehttp_client
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def mcp_session():
    url = os.environ.get("CG_MCP_URL")
    if url:
        async with http_session(url, os.environ.get("CG_MCP_TOKEN")) as s:
            yield s
    else:
        async with stdio_session() as s:
            yield s
