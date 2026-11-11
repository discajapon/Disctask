"""Disctask central store: SQLite with last-write-wins per record, soft deletes and a server-side
change counter (seq) so clients sync incrementally without trusting clocks for paging."""
import sqlite3, time

COLS = {
    'tasks': ('date', 'text', 'done', 'pos'),
    'events': ('date', 'start', 'end', 'title', 'color', 'desc'),
}
DEFAULT = {'text': '', 'done': 0, 'pos': 0, 'start': 0, 'end': 60, 'title': '', 'color': '', 'desc': ''}
MAX_SKEW_MS = 5 * 60 * 1000  # a device clock ahead of this cannot win conflicts forever

def connect(path=':memory:'):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('pragma journal_mode=wal')
    for t, cols in COLS.items():
        db.execute(f'create table if not exists {t} (id text primary key, '
                   + ''.join(f'"{c}", ' for c in cols)
                   + 'updated_at integer not null, deleted integer not null default 0, seq integer not null)')
        db.execute(f'create index if not exists {t}_seq on {t}(seq)')
    db.execute('create table if not exists meta (key text primary key, value integer)')
    db.execute("insert or ignore into meta values ('seq', 0)")
    db.commit()
    return db

def _next_seq(db):
    db.execute("update meta set value=value+1 where key='seq'")
    return db.execute("select value from meta where key='seq'").fetchone()[0]

def cursor(db):
    return db.execute("select value from meta where key='seq'").fetchone()[0]

def _row(r):
    d = dict(r)
    d.pop('seq', None)
    d['deleted'] = bool(d['deleted'])
    return d

def upsert(db, kind, rec, now_ms=None):
    """Apply one client record. Returns True if it won (and was stored)."""
    now_ms = now_ms or int(time.time() * 1000)
    rid = str(rec['id'])
    ts = min(int(rec['updated_at']), now_ms + MAX_SKEW_MS)
    cur = db.execute(f'select updated_at from {kind} where id=?', (rid,)).fetchone()
    if cur and cur['updated_at'] > ts:  # ponytail: ties go to the newcomer; per-field merge if it ever hurts
        return False
    old = db.execute(f'select * from {kind} where id=?', (rid,)).fetchone()
    vals = {c: rec.get(c, old[c] if old else DEFAULT.get(c)) for c in COLS[kind]}
    if kind == 'tasks': vals['done'] = int(bool(vals['done']))
    seq = _next_seq(db)
    names = ('id',) + COLS[kind] + ('updated_at', 'deleted', 'seq')
    args = (rid, *vals.values(), ts, int(bool(rec.get('deleted'))), seq)
    db.execute(f'insert or replace into {kind} ({",".join(chr(34)+n+chr(34) for n in names)}) '
               f'values ({",".join("?" * len(names))})', args)
    return True

def changes_since(db, since):
    out = {}
    for kind in COLS:
        out[kind] = [_row(r) for r in db.execute(f'select * from {kind} where seq>? order by seq', (since,))]
    return out

def sync(db, since, changes, now_ms=None):
    """changes = {'tasks': [...], 'events': [...]}. Returns everything newer than `since` plus the new cursor.
    Idempotent: resending the same changes is harmless."""
    for kind in COLS:
        for rec in changes.get(kind, []):
            upsert(db, kind, rec, now_ms)
    db.commit()
    return {'cursor': cursor(db), **changes_since(db, since)}

def purge(db, days=90):
    cut = int((time.time() - days * 86400) * 1000)
    for kind in COLS:
        db.execute(f'delete from {kind} where deleted=1 and updated_at<?', (cut,))
    db.commit()
