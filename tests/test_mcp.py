"""El MCP local (stdio) es un puente al remoto: mismas herramientas y mismos datos. python3 tests/test_mcp.py
Levanta el servidor real en un puerto local con una base temporal."""
import asyncio, json, os, subprocess, sys, tempfile, time, urllib.request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
tmp = tempfile.mkdtemp()
D, M, URL = 'd' * 30, 'm' * 30, 'http://127.0.0.1:8797'
open(tmp + '/sync.env', 'w').write(f'DISCTASK_URL={URL}\nDISCTASK_DEVICE_TOKEN={D}\nDISCTASK_MCP_TOKEN={M}\n')
srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--port', '8797', '--log-level', 'warning'], cwd=root + '/server',
                       env={**os.environ, 'DISCTASK_DEVICE_TOKEN': D, 'DISCTASK_MCP_TOKEN': M, 'DISCTASK_DB': tmp + '/s.db'})


def remote(name, args):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}).encode()
    r = urllib.request.Request(URL + '/mcp', data=body, headers={'Authorization': 'Bearer ' + M, 'Content-Type': 'application/json',
                                                                   'Accept': 'application/json, text/event-stream'})
    return json.load(urllib.request.urlopen(r))['result']


async def main():
    p = StdioServerParameters(command=sys.executable, args=[root + '/mcp_server.py'], env={**os.environ, 'DISCTASK_ENV': tmp + '/sync.env'})
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = {t.name for t in (await s.list_tools()).tools}
        assert {'list_tasks', 'add_task', 'update_task', 'complete_task', 'delete_task', 'today_summary'} <= names, names
        id = (await s.call_tool('add_task', {'date': '2026-01-02', 'text': 'á', 'note': 'n'})).content[0].text
        await s.call_tool('complete_task', {'id': id})
        local = (await s.call_tool('list_tasks', {'date': '2026-01-02'})).model_dump(exclude_none=True)
        rem = remote('list_tasks', {'date': '2026-01-02'})
        assert local['content'] == rem['content'] and local.get('structuredContent') == rem.get('structuredContent'), (local, rem)
        assert '"á"' in rem['content'][0]['text'] and '"done": true' in rem['content'][0]['text'], rem
        bad = await s.call_tool('add_task', {'date': 'mañana', 'text': 'x'})
        assert bad.isError, bad
    print('ok')

try:
    for _ in range(50):
        try: urllib.request.urlopen(URL + '/api/health'); break
        except OSError: time.sleep(0.2)
    asyncio.run(main())
finally:
    srv.terminate()
