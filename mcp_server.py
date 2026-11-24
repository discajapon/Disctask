#!/usr/bin/env python3
"""MCP local de Disctask (stdio, para Claude Desktop y Claude Code): puente al MCP remoto del VPS, que es la única verdad.
Mismas herramientas y mismos datos que `disctask-remote` (las pide al VPS y reenvía cada llamada tal cual).
Token y URL en ~/.config/disctask/sync.env (600). Sin conexión las herramientas fallan con un error claro; la app de
escritorio sí sigue funcionando sin internet con su caché y su cola de cambios."""
import json, os, urllib.error, urllib.request
from pathlib import Path
import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

ENV = Path(os.environ.get('DISCTASK_ENV', Path.home() / '.config/disctask/sync.env'))
CACHE = Path.home() / '.cache/disctask/tools.json'  # lista de herramientas para arrancar aunque el VPS no responda


def env():
    return dict(l.strip().split('=', 1) for l in open(ENV) if '=' in l)


def remoto(method, params=None):
    e = env()
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).encode()
    req = urllib.request.Request(e['DISCTASK_URL'].rstrip('/') + '/mcp', data=body, headers={
        'Authorization': 'Bearer ' + e['DISCTASK_MCP_TOKEN'], 'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream'})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    if 'error' in r: raise RuntimeError(r['error'].get('message', r['error']))
    return r['result']


server = Server('disctask')


@server.list_tools()
async def list_tools():
    try:
        tools = (await anyio.to_thread.run_sync(remoto, 'tools/list'))['tools']
        CACHE.parent.mkdir(parents=True, exist_ok=True); CACHE.write_text(json.dumps(tools))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        tools = json.loads(CACHE.read_text()) if CACHE.exists() else []
    return [types.Tool.model_validate(t) for t in tools]


@server.call_tool(validate_input=False)  # valida el VPS, que es quien conoce el esquema real
async def call_tool(name, arguments):
    try:
        r = await anyio.to_thread.run_sync(remoto, 'tools/call', {'name': name, 'arguments': arguments})
    except (OSError, urllib.error.URLError) as e:
        return types.CallToolResult(isError=True, content=[types.TextContent(
            type='text', text=f'sin conexión con el VPS de Disctask ({e}); la app de escritorio guarda los cambios sin conexión')])
    return types.CallToolResult.model_validate(r)


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == '__main__':
    anyio.run(main)
