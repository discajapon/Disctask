#!/usr/bin/env python3
"""Read-only MCP server for Disctask: lets Claude Desktop / Claude Code read tasks and calendar events.
Read-only on purpose: the running app keeps its data in memory and would overwrite outside writes."""
import json, os, sqlite3
from mcp.server.fastmcp import FastMCP

DB = os.path.join(os.environ.get('DISCTASK_DATA') or os.path.expanduser('~/.local/share/disctask'),
                  'localstorage', 'file__0.localstorage')
mcp = FastMCP('disctask')

def load(key, empty):
    try:  # mode=ro: never touch the app's live database
        row = sqlite3.connect(f'file:{DB}?mode=ro', uri=True).execute(
            'select value from ItemTable where key=?', (key,)).fetchone()
        v = row[0]
        return json.loads(v.decode('utf-16le') if isinstance(v, bytes) else v)
    except Exception:  # no db yet / key missing / unreadable
        return empty

@mcp.tool()
def list_tasks(date: str = '') -> dict:
    """Tasks as {YYYY-MM-DD: [{text, done}]}. Pass date (YYYY-MM-DD) for a single day."""
    db = load('disctask', {})
    return {date: db.get(date, [])} if date else db

@mcp.tool()
def list_events(date: str = '') -> list:
    """Calendar events {id, date, start, end, title, color, desc}; start/end are minutes since 00:00.
    Pass date (YYYY-MM-DD) to filter to one day."""
    ev = load('disctask-cal', [])
    return [e for e in ev if e.get('date') == date] if date else ev

if __name__ == '__main__':
    mcp.run()  # stdio
