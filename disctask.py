#!/usr/bin/env python3
import gi, os, resource
gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')
from gi.repository import Gtk, WebKit2, GLib
# WebKit's forced GPU renderer leaks one sync_file fd per presented frame (~15/s while
# animating); at the default 1024 limit the web process wedges at 100% CPU. Children inherit this.
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
GLib.set_prgname('disctask')  # Wayland app id; must match disctask.desktop for the dock icon
def gl_ok():  # forcing the GPU renderer aborts the app when GDK has no OpenGL, so probe first
    t = Gtk.Window(); t.realize()
    try: t.get_window().create_gl_context().realize(); return True
    except Exception: return False
    finally: t.destroy()
# WebKitGTK falls back to CPU painting on some GPUs (NVIDIA here: ~12 fps with the glass
# effects); force the GPU renderer. WEBKIT_FORCE_DMABUF_RENDERER=0 ./disctask.py to opt out.
if gl_ok(): os.environ.setdefault('WEBKIT_FORCE_DMABUF_RENDERER', '1')
d = os.environ.get('DISCTASK_DATA') or os.path.expanduser('~/.local/share/disctask')  # override for tests
ctx = WebKit2.WebContext.new_with_website_data_manager(
    WebKit2.WebsiteDataManager(base_data_directory=d, base_cache_directory=d))
def save(dl, name):  # exports land in ~/Downloads, never overwriting
    dst, i = os.path.expanduser('~/Downloads/' + name), 1
    while os.path.exists(dst):
        dst, i = os.path.expanduser('~/Downloads/%s (%d)%s' % (*os.path.splitext(name)[:1], i, os.path.splitext(name)[1])), i + 1
    dl.set_destination('file://' + dst)
    return True
ctx.connect('download-started', lambda c, dl: dl.connect('decide-destination', save))
v = WebKit2.WebView.new_with_context(ctx)
def policy(v, dec, kind):  # web links open in the default browser, not inside the app
    if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
        uri = dec.get_navigation_action().get_request().get_uri()
        if uri.startswith(('http:', 'https:')):
            Gtk.show_uri_on_window(w, uri, Gtk.get_current_event_time())
            dec.ignore()
            return True
    return False
v.connect('decide-policy', policy)
v.load_uri('file://' + os.path.join(os.path.dirname(os.path.realpath(__file__)), 'index.html'))
w = Gtk.Window(title='Disctask', default_width=520, default_height=640)
w.set_icon_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icon.png'))
def resize(m, res):  # page asks for room when the calendar opens/closes
    if not w.is_maximized():
        w.resize(1320 if res.get_js_value().to_string() == 'wide' else 520, max(w.get_size()[1], 760))
m = v.get_user_content_manager()
m.register_script_message_handler('win')
m.connect('script-message-received::win', resize)
w.add(v); w.connect('destroy', Gtk.main_quit); w.show_all(); Gtk.main()
