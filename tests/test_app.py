#!/usr/bin/env python3
"""End-to-end check of the real app (needs a display). Runs it on a throwaway data dir.

    python3 tests/test_app.py          # ~50 s, exit code 1 on any failure
"""
import os, sys, tempfile, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['DISCTASK_DATA'] = tempfile.mkdtemp(prefix='disctask-test-')
import gi
gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib
import runpy, resource
# a desktop launcher starts apps with a 1024 soft fd limit; mimic it (the app must raise it itself)
resource.setrlimit(resource.RLIMIT_NOFILE, (1024, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
fails, wv, checks = [], None, [0]

def check(name, ok, info=''):
    checks[0] += 1
    print(('PASS ' if ok else 'FAIL ') + name, info, flush=True)
    if not ok: fails.append(name)
def js(code, cb):
    def done(v, res):
        try: cb(v.run_javascript_finish(res).get_js_value().to_string())
        except Exception as e: check('script ran', False, e)
    wv.run_javascript(code, None, done)
def at(ms, f): GLib.timeout_add(ms, lambda: (f(), False)[1])
def web_pid():
    me = os.getpid()
    for p in os.listdir('/proc'):
        if p.isdigit():
            try:
                if int(open(f'/proc/{p}/stat').read().rsplit(')', 1)[1].split()[1]) == me and b'WebKitWebProcess' in open(f'/proc/{p}/cmdline', 'rb').read(): return int(p)
            except OSError: pass
def syncs(pid): return sum(1 for f in os.listdir(f'/proc/{pid}/fd') if os.path.islink(f'/proc/{pid}/fd/{f}') and 'sync_file' in os.readlink(f'/proc/{pid}/fd/{f}'))

SEED = """localStorage['disctask']='{broken';
localStorage['disctask-cal']=JSON.stringify([{id:'a',date:'2026-10-26',start:450,end:510,title:'',color:'1,2,3',desc:''},{id:'bad'},{id:'c',date:'2026-10-26',start:600,end:540}]);1"""
RENAME = """(()=>{const fire=(el,t)=>{const r=(el.getBoundingClientRect?el:document.querySelector('.ev')).getBoundingClientRect();el.dispatchEvent(new PointerEvent(t,{bubbles:true,clientX:r.left+10,clientY:r.top+10,button:0,pointerId:1}))};
 day='2026-10-26';render();const el=document.querySelector('.ev');fire(el,'pointerdown');fire(window,'pointerup');
 const opened=$('dlg').open;$('et').value='Instituto';$('ef').requestSubmit($('ef').querySelector('[value=ok]'));
 window.__opened=opened;return 1})()"""
READ = """JSON.stringify({opened:window.__opened,closed:!$('dlg').open,n:ev.length,title:ev[0].title,stored:JSON.parse(localStorage['disctask-cal'])[0].title,corrupt:localStorage['disctask-corrupt'],db:JSON.stringify(db)})"""

DRAG = """(()=>{const P=(el,t,x,y)=>el.dispatchEvent(new PointerEvent(t,{bubbles:true,clientX:x,clientY:y,button:0,pointerId:1}));
 ev.length=0;db['2026-10-26']=[{text:'Estudiar',done:false}];day='2026-10-26';render();calOpen(true);return 1})()"""
DRAG2 = """(()=>{const P=(el,t,x,y)=>el.dispatchEvent(new PointerEvent(t,{bubbles:true,clientX:x,clientY:y,button:0,pointerId:1}));
 const li=document.querySelector('li').getBoundingClientRect(),c=document.querySelectorAll('.col')[1].getBoundingClientRect(),g=$('g').getBoundingClientRect();
 const y=g.top+10*44+5; // 10:00 slot
 P(document.querySelector('li label'),'pointerdown',li.left+40,li.top+10);P(window,'pointermove',li.left+80,li.top+30);P(window,'pointermove',c.left+20,y);
 const preview=!!document.querySelector('.sp');P(window,'pointerup',c.left+20,y);
 const k=ev[0]||{};return JSON.stringify({preview,n:ev.length,title:k.title,date:k.date,start:k.start,len:k.end-k.start,done:db['2026-10-26'][0].done,ghost:!!document.querySelector('.tg')})})()"""
SPAN = """(()=>{const P=(el,t,x,y)=>el.dispatchEvent(new PointerEvent(t,{bubbles:true,clientX:x,clientY:y,button:0,pointerId:1}));
 const h=document.querySelector('.ev .rr'),b=h.getBoundingClientRect(),cols=document.querySelectorAll('.col'),c=cols[3].getBoundingClientRect();
 P(h,'pointerdown',b.left+3,b.top+20);P(window,'pointermove',c.left+20,b.top+20);const preview=!!document.querySelector('.sp');P(window,'pointerup',c.left+20,b.top+20);
 return JSON.stringify({preview,days:ev.map(k=>k.date).sort(),same:ev.every(k=>k.start==ev[0].start&&k.end==ev[0].end&&k.title=='Estudiar'),ids:new Set(ev.map(k=>k.id)).size,sp:!!document.querySelector('.sp')})})()"""
def drag_phase():
    def a(r):
        o = json.loads(r)
        check('dragging a task shows a drop preview', o['preview'])
        check('dropping a task creates a 1 h box with its title', o['n'] == 1 and o['title'] == 'Estudiar' and o['len'] == 60 and o['date'] == '2026-10-27' and o['start'] == 600, o)
        check('the dragged task is not ticked and the ghost is gone', not o['done'] and not o['ghost'])
        def b(r2):
            o2 = json.loads(r2)
            check('stretching shows a preview, then splits into one box per day', o2['preview'] and not o2['sp'] and o2['days'] == ['2026-10-27', '2026-10-28', '2026-10-29'], o2)
            check('split boxes keep time and title and get unique ids', o2['same'] and o2['ids'] == 3, o2)
        js(SPAN, b)
    js(DRAG, lambda r: at(1300, lambda: js(DRAG2, a)))
def phase2():
    def got(r):
        o = json.loads(r)
        check('corrupt task data survives as a copy', o['corrupt'] == '{broken', o['corrupt'])
        check('app boots with empty tasks after corrupt data', o['db'] == '{}')
        check('invalid events are dropped, valid one kept', o['n'] == 1, o['n'])
        check('editor opens for an event with an unknown colour', o['opened'])
        check('renaming an event saves and closes the dialog', o['closed'] and o['title'] == 'Instituto' and o['stored'] == 'Instituto', o)
    js(RENAME, lambda r: at(400, lambda: js(READ, got)))  # the dialog's close event is asynchronous
    at(2500, drag_phase)
    pid = web_pid(); lim = [l for l in open(f'/proc/{pid}/limits') if l.startswith('Max open files')][0].split()
    check('web process has a high fd limit', int(lim[3]) >= 65536, lim[3])
    for t in range(30000, 43000, 3000): at(t, lambda: samples.append(syncs(pid)))  # animations pause after 20 s idle
    at(43000, finish)
samples = []
def finish():
    last = samples[-3:]  # once idle the count must hold still (a stray burst earlier in the window is tolerated)
    check('no fence fds leak while idle', max(last) - min(last) <= 5, samples)
    if checks[0] < 12: fails.append('only %d checks ran' % checks[0])
    print('FAILED: ' + ', '.join(fails) if fails else 'ALL PASSED'); Gtk.main_quit()

orig, state = WebKit2.WebView.load_uri, [0]
def lu(self, uri):
    global wv; wv = self
    def done(v, e):
        if e != WebKit2.LoadEvent.FINISHED: return
        state[0] += 1
        if state[0] == 1: js(SEED, lambda r: v.reload())
        elif state[0] == 2: at(800, phase2)
    self.connect('load-changed', done)
    orig(self, uri)
WebKit2.WebView.load_uri = lu
at(80000, lambda: (print('TIMEOUT'), sys.exit(1)))
sys.argv = ['disctask.py']
runpy.run_path(os.path.join(ROOT, 'disctask.py'), run_name='__main__')
sys.exit(1 if fails else 0)
