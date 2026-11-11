"""Disctask server: /api (device sync) and /mcp (Claude, Streamable HTTP) over one SQLite store.
Env: DISCTASK_DEVICE_TOKEN, DISCTASK_MCP_TOKEN (both required), DISCTASK_DB, DISCTASK_TZ.
Run: uvicorn app:app --host 127.0.0.1 --port 8765  (behind the HTTPS reverse proxy)"""
import hmac, json, os, re, time, uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
import store

DEVICE_TOKEN = os.environ.get('DISCTASK_DEVICE_TOKEN', '')
MCP_TOKEN = os.environ.get('DISCTASK_MCP_TOKEN', '')
if len(DEVICE_TOKEN) < 24 or len(MCP_TOKEN) < 24 or DEVICE_TOKEN == MCP_TOKEN:
    raise SystemExit('set distinct DISCTASK_DEVICE_TOKEN and DISCTASK_MCP_TOKEN (>= 24 chars each)')
TZ = ZoneInfo(os.environ.get('DISCTASK_TZ', 'UTC'))
db = store.connect(os.environ.get('DISCTASK_DB', 'disctask.db'))
now = lambda: int(time.time() * 1000)

# --- MCP tools (same set as the local server, addressed by id, deletes are soft and reversible) ---
# DNS-rebinding protection only matters for local servers; here the bearer token gates every request.
mcp = FastMCP('disctask', stateless_http=True, json_response=True,
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

def check_date(d):
    if not (re.fullmatch(r'\d{4}-\d\d-\d\d', d) and d <= '2040-12-31'):
        raise ValueError('date must be YYYY-MM-DD, up to 2040-12-31')

def get(kind, id):
    r = db.execute(f'select * from {kind} where id=?', (id,)).fetchone()
    if not r: raise ValueError(f'no {kind[:-1]} with id {id}; use the list tools to see ids')
    return r

def put(kind, id, **f):
    store.upsert(db, kind, {'id': id, 'updated_at': now(), **f}); db.commit()
    return id

def edit(kind, id, deleted=False, **f):
    r = get(kind, id)
    return put(kind, id, deleted=deleted, **{k: v for k, v in f.items() if v is not None})

def view(kind, **where):
    q = [f'select * from {kind} where deleted=0']
    for k, v in where.items():
        if v: q.append(f'and {k}=?')
    rows = db.execute(' '.join(q) + ' order by date, ' + ('pos' if kind == 'tasks' else 'start, "end"'),
                      [v for v in where.values() if v]).fetchall()
    return [{k: (bool(r[k]) if k == 'done' else r[k]) for k in r.keys() if k not in ('seq', 'deleted')} for r in rows]

@mcp.tool()
def list_tasks(date: str = '', from_date: str = '', to_date: str = '') -> list:
    """Tasks {id, date, text, done, pos}. Pass date for one day, or from_date/to_date (YYYY-MM-DD) for a range."""
    rows = view('tasks', date=date)
    return [t for t in rows if (not from_date or t['date'] >= from_date) and (not to_date or t['date'] <= to_date)]

@mcp.tool()
def list_events(date: str = '') -> list:
    """Calendar events {id, date, start, end, title, color, desc}; start/end are minutes since 00:00."""
    return view('events', date=date)

@mcp.tool()
def add_task(date: str, text: str, done: bool = False) -> str:
    """Add a task to a day (YYYY-MM-DD). Returns its id. It goes at the end of that day's list."""
    check_date(date)
    pos = max([t['pos'] for t in view('tasks', date=date)] or [0]) + 1
    return put('tasks', str(uuid.uuid4()), date=date, text=text, done=done, pos=pos)

@mcp.tool()
def update_task(id: str, text: str | None = None, done: bool | None = None, date: str | None = None) -> str:
    """Change text, done flag and/or day of the task with this id (from list_tasks)."""
    if date is not None: check_date(date)
    return edit('tasks', id, text=text, done=done, date=date)

@mcp.tool()
def complete_task(id: str, done: bool = True) -> str:
    """Mark the task done (or not done with done=false)."""
    return edit('tasks', id, done=done)

@mcp.tool()
def delete_task(id: str) -> str:
    """Delete a task (soft delete: restore_task brings it back)."""
    get('tasks', id)
    return put('tasks', id, deleted=True)

@mcp.tool()
def restore_task(id: str) -> str:
    """Undo delete_task."""
    get('tasks', id)
    return put('tasks', id, deleted=False)

def check_times(s, e):
    if not (0 <= s < e <= 1440): raise ValueError('start/end are minutes since 00:00 with 0 <= start < end <= 1440')

@mcp.tool()
def add_event(date: str, start: int, end: int, title: str = '', color: str = '', desc: str = '') -> str:
    """Add a calendar event. start/end are minutes since 00:00 (end > start, max 1440). Returns its id."""
    check_date(date); check_times(start, end)
    return put('events', str(uuid.uuid4()), date=date, start=start, end=end, title=title, color=color, desc=desc)

@mcp.tool()
def update_event(id: str, date: str | None = None, start: int | None = None, end: int | None = None,
                 title: str | None = None, color: str | None = None, desc: str | None = None) -> str:
    """Change any fields of the event with this id; omitted fields stay as they are."""
    r = get('events', id)
    if date is not None: check_date(date)
    check_times(r['start'] if start is None else start, r['end'] if end is None else end)
    return edit('events', id, date=date, start=start, end=end, title=title, color=color, desc=desc)

@mcp.tool()
def delete_event(id: str) -> str:
    """Delete an event (soft delete: restore_event brings it back)."""
    get('events', id)
    return put('events', id, deleted=True)

@mcp.tool()
def restore_event(id: str) -> str:
    """Undo delete_event."""
    get('events', id)
    return put('events', id, deleted=False)

@mcp.tool()
def today_summary() -> dict:
    """Today's date (server timezone) with today's pending tasks, done tasks and calendar events. Use `today` to resolve 'tomorrow', 'Friday', etc."""
    d = datetime.now(TZ)
    t = d.strftime('%Y-%m-%d')
    tasks = view('tasks', date=t)
    return {'today': t, 'weekday': d.strftime('%A'), 'pending': [x for x in tasks if not x['done']],
            'done': [x for x in tasks if x['done']], 'events': view('events', date=t)}

@mcp.tool()
def tasks_today() -> list:
    """Today's tasks (server timezone)."""
    return view('tasks', date=datetime.now(TZ).strftime('%Y-%m-%d'))

# --- device sync API ---
async def health(request): return JSONResponse({'ok': True})

async def sync(request):
    try:
        b = await request.json()
        since = int(b.get('since', 0))
        ch = {k: b.get('changes', {}).get(k, []) for k in store.COLS}
        if not all(isinstance(x, dict) and 'id' in x and 'updated_at' in x for v in ch.values() for x in v):
            raise ValueError
        return JSONResponse(store.sync(db, since, ch))
    except (ValueError, TypeError, AttributeError, KeyError):
        return JSONResponse({'error': 'bad request'}, status_code=400)

# --- auth: /mcp needs the MCP token, /api/sync the device token; /api/health and /apk are public ---
class Auth:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            p = scope['path']
            want = MCP_TOKEN if p.startswith('/mcp') else DEVICE_TOKEN if p.startswith('/api/') and p != '/api/health' else None
            if want is not None and scope['method'] != 'OPTIONS':
                h = dict(scope['headers']).get(b'authorization', b'').decode()
                if not hmac.compare_digest(h.encode(), f'Bearer {want}'.encode()):
                    return await JSONResponse({'error': 'unauthorized'}, status_code=401,
                                              headers={'WWW-Authenticate': 'Bearer'})(scope, receive, send)
        await self.app(scope, receive, send)

app = mcp.streamable_http_app()  # route /mcp, no redirects; reuses its lifespan (session manager)
app.router.routes[:0] = [Route('/api/health', health), Route('/api/sync', sync, methods=['POST'])]
app.router.redirect_slashes = False
app.add_middleware(Auth)
# origins: desktop WebView (file:// -> "null") and the Capacitor APK
app.add_middleware(CORSMiddleware, allow_origins=['null', 'https://localhost', 'capacitor://localhost', 'http://localhost'],
                   allow_methods=['POST', 'GET'], allow_headers=['Authorization', 'Content-Type'])
