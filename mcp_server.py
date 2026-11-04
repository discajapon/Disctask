#!/usr/bin/env python3
"""MCP server for Disctask: lets Claude Desktop / Claude Code read and edit tasks and calendar events.
Reads the app's db read-only. Writes never touch it (the running app keeps its data in memory and would
overwrite them): they are appended to inbox.jsonl, which disctask.py drains and the page applies."""
import json, os, re, sqlite3
from mcp.server.fastmcp import FastMCP

DIR = os.environ.get('DISCTASK_DATA') or os.path.expanduser('~/.local/share/disctask')
DB = os.path.join(DIR, 'localstorage', 'file__0.localstorage')
INBOX = os.path.join(DIR, 'inbox.jsonl')
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

def send(**op):
    with open(INBOX, 'a') as f:
        f.write(json.dumps(op) + '\n')
    return 'queued: the app applies it within a second (on next launch if it is closed)'

def check_date(d):
    if not (re.fullmatch(r'\d{4}-\d\d-\d\d', d) and d <= '2040-12-31'):  # same ceiling as the app
        raise ValueError('date must be YYYY-MM-DD, up to 2040-12-31')

def check_task(date, index):
    check_date(date)
    if not 0 <= index < len(load('disctask', {}).get(date, [])):
        raise ValueError(f'no task #{index} on {date}; list_tasks shows the indexes (0-based)')

def check_event(id):
    if not any(e.get('id') == id for e in load('disctask-cal', [])):
        raise ValueError(f'no event with id {id}; list_events shows the ids')

@mcp.tool()
def add_task(date: str, text: str, done: bool = False) -> str:
    """Add a task to a day (YYYY-MM-DD). It goes at the end of that day's list."""
    check_date(date)
    return send(op='add_task', date=date, text=text, done=done)

@mcp.tool()
def update_task(date: str, index: int, text: str | None = None, done: bool | None = None) -> str:
    """Change the text and/or done flag of the task at 0-based position index of a day."""
    check_task(date, index)
    return send(op='update_task', date=date, index=index, text=text, done=done)

@mcp.tool()
def delete_task(date: str, index: int) -> str:
    """Delete the task at 0-based position index of a day (later tasks shift up)."""
    check_task(date, index)
    return send(op='delete_task', date=date, index=index)

@mcp.tool()
def add_event(date: str, start: int, end: int, title: str = '', color: str = '', desc: str = '') -> str:
    """Add a calendar event. start/end are minutes since 00:00 (end > start, max 1440). Empty color = app default."""
    check_date(date)
    return send(op='add_event', event=dict(date=date, start=start, end=end, title=title, color=color, desc=desc))

@mcp.tool()
def update_event(id: str, date: str | None = None, start: int | None = None, end: int | None = None,
                 title: str | None = None, color: str | None = None, desc: str | None = None) -> str:
    """Change any fields of the event with this id (from list_events); omitted fields stay as they are."""
    check_event(id)
    if date is not None: check_date(date)
    f = dict(date=date, start=start, end=end, title=title, color=color, desc=desc)
    return send(op='update_event', id=id, fields={k: v for k, v in f.items() if v is not None})

@mcp.tool()
def delete_event(id: str) -> str:
    """Delete the event with this id (from list_events)."""
    check_event(id)
    return send(op='delete_event', id=id)

if __name__ == '__main__':
    mcp.run()  # stdio
