"""Sync cases with simulated devices. Run: python3 server/tests/test_store.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import store

def task(i, t, text='x', **kw): return dict(id=i, updated_at=t, date='2026-11-11', text=text, done=False, pos=1, **kw)

def merged(db, since=0): return {r['id']: r for r in store.sync(db, since, {})['tasks']}

# two devices, one offline, edit the same task: newest wins on both
db = store.connect()
store.sync(db, 0, {'tasks': [task('a', 1000, 'original')]})
store.sync(db, 0, {'tasks': [task('a', 3000, 'phone offline edit')]})   # pushed later, but edited later
r = store.sync(db, 0, {'tasks': [task('a', 2000, 'pc edit')]})          # older edit arrives last: loses
assert merged(db)['a']['text'] == 'phone offline edit' and r['tasks'][0]['text'] == 'phone offline edit'

# delete vs. older edit: tombstone wins and syncs; newer edit resurrects
store.sync(db, 0, {'tasks': [task('a', 4000, deleted=True)]})
assert merged(db)['a']['deleted'] is True
store.sync(db, 0, {'tasks': [task('a', 3500, 'stale edit')]})
assert merged(db)['a']['deleted'] is True
store.sync(db, 0, {'tasks': [task('a', 5000, 'back')]})
assert merged(db)['a']['deleted'] is False and merged(db)['a']['text'] == 'back'

# incremental: a device at the current cursor sees nothing, then only the new record
c = store.cursor(db)
assert store.sync(db, c, {})['tasks'] == []
store.sync(db, 0, {'events': [dict(id='e', updated_at=1, date='2026-11-11', start=60, end=120, title='t')]})
r = store.sync(db, c, {})
assert [e['id'] for e in r['events']] == ['e'] and r['tasks'] == [] and r['cursor'] > c

# idempotent retry: same payload twice leaves one row, same content
p = {'tasks': [task('b', 10, 'once')]}
store.sync(db, 0, p); store.sync(db, 0, p)
assert db.execute("select count(*) from tasks where id='b'").fetchone()[0] == 1

# clock far in the future is clamped, so a later real edit can still win
store.sync(db, 0, {'tasks': [task('f', 10**15, 'bad clock')]}, now_ms=1_000_000)
assert merged(db)['f']['updated_at'] == 1_000_000 + store.MAX_SKEW_MS
store.sync(db, 0, {'tasks': [task('f', 1_000_000 + store.MAX_SKEW_MS + 1, 'fixed')]}, now_ms=1_000_000)
assert merged(db)['f']['text'] == 'fixed'

# partial update keeps untouched fields
store.sync(db, 0, {'events': [dict(id='e', updated_at=2, title='renamed')]})
e = {x['id']: x for x in store.sync(db, 0, {})['events']}['e']
assert e['title'] == 'renamed' and e['start'] == 60 and e['date'] == '2026-11-11'
# a client that loses gets the winner back even though its cursor is already past it
db = store.connect()
store.sync(db, 0, {'tasks': [task('w', 9000, 'winner')]})
c = store.cursor(db)
r = store.sync(db, c, {'tasks': [task('w', 100, 'loser')]})
assert [t['text'] for t in r['tasks']] == ['winner']
print('ok')
