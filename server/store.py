"""Disctask central store: SQLite with last-write-wins per field, soft deletes and a server-side
change counter (seq) so clients sync incrementally without trusting clocks for paging."""
import json, sqlite3, time

COLS = {
    'tasks': ('date', 'text', 'done', 'pos', 'note'),
    'events': ('date', 'start', 'end', 'title', 'color', 'desc'),
}
DEFAULT = {'text': '', 'note': '', 'done': 0, 'pos': 0, 'start': 0, 'end': 60, 'title': '', 'color': '', 'desc': ''}
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
        have = [r[1] for r in db.execute(f'pragma table_info({t})')]
        for c in cols + ('fts',):  # databases deployed before per-field merge / before a new field existed
            if c not in have: db.execute(f'alter table {t} add column "{c}"')
    db.execute('create table if not exists conflicts (id integer primary key autoincrement, at integer, '
               'kind text, rec_id text, field text, kept text, lost text, kept_ts integer, lost_ts integer)')
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
    d.pop('fts', None)
    d['deleted'] = bool(d['deleted'])
    if 'done' in d: d['done'] = bool(d['done'])
    return d

def _norm(field, val):
    if field in ('done', 'deleted'): return int(bool(val))
    return val if val is not None else DEFAULT.get(field)

def upsert(db, kind, rec, now_ms=None):
    """Apply one client record field by field: the newest edit of each field wins.
    Returns True if every candidate field won (or the record is new)."""
    now_ms = now_ms or int(time.time() * 1000)
    rid = str(rec['id'])
    ts = min(int(rec['updated_at']), now_ms + MAX_SKEW_MS)
    tracked = COLS[kind] + ('deleted',)
    old = db.execute(f'select * from {kind} where id=?', (rid,)).fetchone()
    if old is None:
        vals = {c: _norm(c, rec.get(c)) for c in COLS[kind]}
        vals['deleted'] = int(bool(rec.get('deleted')))
        fts = {c: ts for c in tracked}
        seq = _next_seq(db)
        names = ('id',) + COLS[kind] + ('deleted', 'updated_at', 'seq', 'fts')
        args = (rid, *vals.values(), ts, seq, json.dumps(fts))
        db.execute(f'insert or replace into {kind} ({",".join(chr(34)+n+chr(34) for n in names)}) '
                   f'values ({",".join("?" * len(names))})', args)
        return True
    if 'fields' in rec:
        cands = [f for f in rec['fields'] if f in tracked]
    else:
        cands = [c for c in COLS[kind] if c in rec] + ['deleted']
    fts = json.loads(old['fts']) if old['fts'] else {}
    vals, lost_any, changed = {}, False, False
    for c in COLS[kind]: vals[c] = _norm(c, old[c])
    vals['deleted'] = int(bool(old['deleted']))
    for f in cands:
        cur_ts = fts.get(f, old['updated_at'])
        if ts >= cur_ts:
            has = f == 'deleted' and 'fields' not in rec
            if f in rec: new = _norm(f, rec[f])
            elif has: new = 0  # a full record without 'deleted' resurrects, as before
            else: new = vals[f]
            if vals[f] != new or fts.get(f) != ts: changed = True
            vals[f] = new
            fts[f] = ts
        elif f in rec and _norm(f, rec[f]) != vals[f]:
            db.execute('insert into conflicts (at, kind, rec_id, field, kept, lost, kept_ts, lost_ts) '
                       'values (?,?,?,?,?,?,?,?)',
                       (int(time.time() * 1000), kind, rid, f,
                        json.dumps(vals[f]), json.dumps(rec[f]), cur_ts, ts))
            lost_any = True
    updated_at = max(fts.values()) if fts else old['updated_at']
    if changed or updated_at != old['updated_at']:
        seq = _next_seq(db)
        names = ('id',) + COLS[kind] + ('deleted', 'updated_at', 'seq', 'fts')
        args = (rid, *vals.values(), updated_at, seq, json.dumps(fts))
        db.execute(f'insert or replace into {kind} ({",".join(chr(34)+n+chr(34) for n in names)}) '
                   f'values ({",".join("?" * len(names))})', args)
    return not lost_any

def changes_since(db, since):
    out = {}
    for kind in COLS:
        out[kind] = [_row(r) for r in db.execute(f'select * from {kind} where seq>? order by seq', (since,))]
    return out

def sync(db, since, changes, now_ms=None):
    """changes = {'tasks': [...], 'events': [...]}. Returns everything newer than `since` plus the new cursor,
    and the winning row for any pushed record that lost, so a client that lost converges.
    Idempotent: resending the same changes is harmless."""
    lost = {k: [] for k in COLS}
    for kind in COLS:
        for rec in changes.get(kind, []):
            if not upsert(db, kind, rec, now_ms): lost[kind].append(str(rec['id']))
    db.commit()
    out = changes_since(db, since)
    for kind, ids in lost.items():
        have = {r['id'] for r in out[kind]}
        out[kind] += [_row(db.execute(f'select * from {kind} where id=?', (i,)).fetchone()) for i in ids if i not in have]
    return {'cursor': cursor(db), **out}

def conflicts(db, limit=50):
    return [dict(r) for r in db.execute('select * from conflicts order by id desc limit ?', (limit,))]

def purge(db, days=90):
    cut = int((time.time() - days * 86400) * 1000)
    for kind in COLS:
        db.execute(f'delete from {kind} where deleted=1 and updated_at<?', (cut,))
    db.commit()
