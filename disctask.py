#!/usr/bin/env python3
import gi, os
gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')
from gi.repository import Gtk, WebKit2
d = os.path.expanduser('~/.local/share/disctask')
ctx = WebKit2.WebContext.new_with_website_data_manager(
    WebKit2.WebsiteDataManager(base_data_directory=d, base_cache_directory=d))
v = WebKit2.WebView.new_with_context(ctx)
v.load_uri('file://' + os.path.join(os.path.dirname(os.path.realpath(__file__)), 'index.html'))
w = Gtk.Window(title='Disctask', default_width=520, default_height=640)
w.add(v); w.connect('destroy', Gtk.main_quit); w.show_all(); Gtk.main()
