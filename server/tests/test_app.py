"""Boots the server on a throwaway db and checks auth, sync and MCP over real HTTP. Run: python3 server/tests/test_app.py"""
import asyncio, json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
D, M = 'd' * 32, 'm' * 32
here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
env = {**os.environ, 'DISCTASK_DEVICE_TOKEN': D, 'DISCTASK_MCP_TOKEN': M, 'DISCTASK_DB': tmp + '/t.db'}
srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--port', '8799', '--log-level', 'warning'],
                       cwd=os.path.join(here, '..'), env=env)
U = 'http://127.0.0.1:8799'

def req(path, token=None, body=None):
    r = urllib.request.Request(U + path, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {})})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    try: return urllib.request.build_opener(NoRedirect).open(r).status
    except urllib.error.HTTPError as e: return e.code

try:
    for _ in range(50):
        try: urllib.request.urlopen(U + '/api/health'); break
        except OSError: time.sleep(0.2)
    assert req('/api/sync', None, {}) == 401 and req('/api/sync', M, {}) == 401          # no / wrong-scope token
    assert req('/api/sync', D, {'since': 0, 'changes': {'tasks': [{'id': 'a', 'updated_at': 1, 'date': '2026-11-11', 'text': 'hi'}]}}) == 200
    assert req('/api/sync', D, {'changes': {'tasks': [{'nope': 1}]}}) == 400
    assert req('/mcp', None, {}) == 401 and req('/mcp', D, {}) == 401                      # device token cannot reach MCP
    assert req('/mcp', M, {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}) not in (301, 302, 307, 308)  # never redirects

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async def run():
        async with streamablehttp_client(U + '/mcp', headers={'Authorization': 'Bearer ' + M}) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {'list_tasks', 'add_task', 'complete_task', 'delete_task', 'restore_task', 'add_event', 'today_summary'} <= names
                call = lambda n, **a: s.call_tool(n, a)
                tid = (await call('add_task', date='2026-11-12', text='from claude')).content[0].text
                assert 'from claude' in (await call('list_tasks', date='2026-11-12')).content[0].text
                await call('complete_task', id=tid)
                await call('delete_task', id=tid)
                assert 'from claude' not in ''.join(c.text for c in (await call('list_tasks', date='2026-11-12')).content)  # empty list = no content
                await call('restore_task', id=tid)
                assert 'from claude' in (await call('list_tasks', date='2026-11-12')).content[0].text
                bad = await call('add_event', date='2026-11-12', start=100, end=50)
                assert bad.isError
                assert 'today' in (await call('today_summary')).content[0].text
    asyncio.run(run())
    # what Claude wrote is visible to a device sync
    import urllib.request as u
    r = u.Request(U + '/api/sync', data=b'{"since":0}', headers={'Authorization': 'Bearer ' + D, 'Content-Type': 'application/json'})
    assert 'from claude' in u.urlopen(r).read().decode()
    print('ok')
finally:
    srv.terminate()
