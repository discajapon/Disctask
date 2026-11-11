#!/usr/bin/env python3
"""Two real app pages (two 'devices') syncing through a real server on throwaway data. Needs a display (~15 s).

    python3 tests/test_sync.py
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import gi
gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2
D, M, URL = 'd' * 32, 'm' * 32, 'http://127.0.0.1:8798'
tmp = tempfile.mkdtemp(prefix='disctask-sync-')
srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--port', '8798', '--log-level', 'warning'], cwd=ROOT + '/server',
                       env={**os.environ, 'DISCTASK_DEVICE_TOKEN': D, 'DISCTASK_MCP_TOKEN': M, 'DISCTASK_DB': tmp + '/s.db'})
fails = []
def check(name, ok, info=''):
    print(('PASS ' if ok else 'FAIL ') + name, '' if ok else info, flush=True)
    if not ok: fails.append(name)
def spin(cond, secs=15):
    end = time.time() + secs
    while not cond() and time.time() < end: Gtk.main_iteration_do(False); time.sleep(0.01)
    return cond()
def device(name):
    d = f'{tmp}/{name}'
    ctx = WebKit2.WebContext.new_with_website_data_manager(WebKit2.WebsiteDataManager(base_data_directory=d, base_cache_directory=d))
    v = WebKit2.WebView.new_with_context(ctx)
    w = Gtk.OffscreenWindow(); w.add(v); w.show_all()
    v.w = w
    return v
def load(v):
    done = []
    v.connect('load-changed', lambda v, e: done.append(1) if e == WebKit2.LoadEvent.FINISHED else None)
    v.load_uri('file://' + ROOT + '/index.html'); spin(lambda: done)
def js(v, code):
    out = []
    def fin(v, r):
        try: out.append(v.run_javascript_finish(r).get_js_value().to_string())
        except Exception as e: out.append('ERR ' + str(e))
    v.run_javascript(code, None, fin); spin(lambda: out)
    return out[0] if out else 'TIMEOUT'
def server():
    r = urllib.request.Request(URL + '/api/sync', data=b'{"since":0}', headers={'Authorization': 'Bearer ' + D, 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r).read())
STATE = "JSON.stringify({db:db,ev:ev,dirty:Object.values(S.meta).filter(m=>m.dirty).length,cursor:S.cursor,ss:$('ss').textContent})"
def state(v): return json.loads(js(v, STATE))
def sync(v):
    js(v, "next=0;syncNow();1"); spin(lambda: False, 0.05)
    ok = spin(lambda: not state(v)['dirty'] and json.loads(js(v, "JSON.stringify(!busy)")))
    return ok
def cfg(v, url): js(v, f"localStorage['disctask-server']='{url}';localStorage['disctask-token']='{D}';1")

try:
    for _ in range(50):
        try: urllib.request.urlopen(URL + '/api/health'); break
        except OSError: time.sleep(0.2)
    A, B = device('a'), device('b')
    load(A); load(B)
    # device A has old-format data (no ids); it must migrate in place and push
    js(A, """localStorage['disctask']=JSON.stringify({'2026-11-12':[{text:'t1',done:false},{text:'t2',done:true}]});
     localStorage['disctask-cal']=JSON.stringify([{id:'e1',date:'2026-11-12',start:60,end:120,title:'ev',color:'',desc:''}]);1""")
    cfg(A, URL); load(A)
    check('A synced its migrated data', spin(lambda: state(A)['cursor'] > 0 and not state(A)['dirty']), state(A))
    a = state(A)
    check('tasks got ids and positions, order kept', [t['text'] for t in a['db']['2026-11-12']] == ['t1', 't2'] and all(t.get('id') and t.get('p') for t in a['db']['2026-11-12']), a['db'])
    check('premigration copy kept', 'disctask-premigrate' in js(A, "Object.keys(localStorage).join()"))
    s = server()
    check('server has 2 tasks and 1 event', len(s['tasks']) == 2 and len(s['events']) == 1, s)
    cfg(B, URL); load(B)
    check('B (fresh) pulled everything', spin(lambda: len(state(B)['ev']) == 1 and len(state(B)['db'].get('2026-11-12', [])) == 2), state(B))
    b = state(B)
    check('B has same ids, order and done flag', [(t['id'], t['text'], t['done']) for t in b['db']['2026-11-12']] == [(t['id'], t['text'], t['done']) for t in a['db']['2026-11-12']], b['db'])
    check('indicator says synced', '●' in b['ss'], b['ss'])

    # both offline, edit the same things; the later edit must win, the later delete must win
    for v in (A, B): cfg(v, 'http://127.0.0.1:1')
    js(A, "db['2026-11-12'][0].text='A edit';save();1"); time.sleep(0.05)
    js(A, "db['2026-11-12'][1].text='A edit t2';save();1"); time.sleep(0.05)
    js(B, "db['2026-11-12'][0].text='B edit';save();1"); time.sleep(0.05)
    js(B, "db['2026-11-12'].splice(1,1);save();ev[0].title='B title';saveEv();1")
    js(A, "next=0;syncNow();1"); js(B, "next=0;syncNow();1")
    spin(lambda: 'offline' in js(A, "state") and 'offline' in js(B, "state"), 5)
    check('offline: pending indicator shows the queue', '◐' in state(A)['ss'] and state(A)['dirty'] == 2, state(A)['ss'])
    for v in (A, B): cfg(v, URL)
    for v in (A, B, A): check('reconnect syncs', sync(v))
    a, b = state(A), state(B)
    for n, x in (('A', a), ('B', b)):
        check(f'{n}: later edit won', x['db']['2026-11-12'][0]['text'] == 'B edit', x['db'])
        check(f'{n}: later delete won', len(x['db']['2026-11-12']) == 1, x['db'])
        check(f'{n}: event edit synced', x['ev'][0]['title'] == 'B title', x['ev'])
    t = {x['id']: x for x in server()['tasks']}
    check('server keeps the delete as a tombstone', sum(x['deleted'] for x in t.values()) == 1, t)
finally:
    srv.terminate()
print('FAILED: ' + ', '.join(fails) if fails else 'ALL OK'); sys.exit(1 if fails else 0)
