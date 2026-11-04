"""Runs mcp_server.py over stdio against a throwaway localStorage db: python3 tests/test_mcp.py"""
import asyncio, json, os, sqlite3, sys, tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
d = tempfile.mkdtemp(); os.makedirs(d + '/localstorage')
c = sqlite3.connect(d + '/localstorage/file__0.localstorage')
c.execute('create table ItemTable (key text unique on conflict replace, value blob not null)')
c.execute('insert into ItemTable values (?,?)', ('disctask', json.dumps({'2026-01-02': [{'text': 'á', 'done': True}]}).encode('utf-16le')))
c.execute('insert into ItemTable values (?,?)', ('disctask-cal', json.dumps([{'id': 'a', 'date': '2026-01-02', 'start': 60, 'end': 120, 'title': 'x'}]).encode('utf-16le')))
c.commit()

async def main():
    p = StdioServerParameters(command=sys.executable, args=[root + '/mcp_server.py'], env={**os.environ, 'DISCTASK_DATA': d})
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        t = await s.call_tool('list_tasks', {'date': '2026-01-02'})
        assert json.loads(t.content[0].text) == {'2026-01-02': [{'text': 'á', 'done': True}]}, t
        e = await s.call_tool('list_events', {'date': '2000-01-01'})
        assert not e.content, e
        e = await s.call_tool('list_events', {})
        assert json.loads(e.content[0].text)['title'] == 'x', e
        await s.call_tool('add_task', {'date': '2026-01-03', 'text': 'n'})
        await s.call_tool('update_task', {'date': '2026-01-02', 'index': 0, 'done': False})
        await s.call_tool('delete_task', {'date': '2026-01-02', 'index': 0})
        await s.call_tool('add_event', {'date': '2026-01-03', 'start': 0, 'end': 30, 'title': 'y'})
        await s.call_tool('update_event', {'id': 'a', 'title': 'z'})
        await s.call_tool('delete_event', {'id': 'a'})
        for name, args in [('add_task', {'date': 'mañana', 'text': 'x'}), ('delete_task', {'date': '2026-01-02', 'index': 5}),
                           ('update_event', {'id': 'nope', 'title': 'x'}), ('delete_event', {'id': 'nope'})]:
            assert (await s.call_tool(name, args)).isError, name  # rejected, nothing queued
    ops = [json.loads(l) for l in open(d + '/inbox.jsonl')]
    assert [o['op'] for o in ops] == ['add_task', 'update_task', 'delete_task', 'add_event', 'update_event', 'delete_event'], ops
    assert ops[4]['fields'] == {'title': 'z'} and ops[1]['text'] is None, ops
asyncio.run(main()); print('ok')
