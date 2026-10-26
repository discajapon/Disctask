# Disctask

Daily task app for Ubuntu with a liquid glass look. Add tasks per day, check them off, browse days with ‹ › and years with « ».

## Calendar
The 🗓 button opens a weekly schedule next to the tasks (the window widens to fit).

- Click an empty slot for a 1 h event, or drag to size it (15-min steps).
- Drag an event to move it to another hour or day; drag its top or bottom edge to make it longer or shorter.
- Click an event to edit its title, translucent color, date, times and description. Links in the description (`https://…`, `www.…`) are clickable and open in your browser.
- Overlapping events sit side by side.

## Run
Needs GTK3 + WebKit2GTK (`gir1.2-webkit2-4.1`).

    ./disctask.py

Data is stored in `~/.local/share/disctask`.

The app forces WebKit's GPU renderer when OpenGL works, since WebKitGTK may otherwise paint on the CPU (about 9 fps with the glass effects). If you see rendering glitches, run `WEBKIT_FORCE_DMABUF_RENDERER=0 ./disctask.py`.

That renderer leaks one `sync_file` file descriptor per presented frame. At the usual 1024-fd limit the web process wedged at 100% CPU after a few minutes (the app "froze"), so `disctask.py` raises the limit, the page pauses its endless animations after 20 s without input (and whenever the window is unfocused), and a dead web process is reloaded.

## Data and offline use
Everything is local: no network access, fonts and wallpaper are bundled. Tasks and events live in the WebView's localStorage under `~/.local/share/disctask`. If stored data is ever unreadable it is kept as `disctask-corrupt` / `disctask-cal-corrupt` instead of being overwritten. Use "Exportar notas" for a backup.

## Tests
`python3 tests/test_app.py` runs the real app on a throwaway data dir (needs a display, ~50 s). `DISCTASK_DATA=<dir>` points the app at any data dir.

## Font
The UI uses Anthropic Serif. It is not in the repo (proprietary): install it system-wide, or drop the `.otf` files into `fonts/` (ignored by git). Without it the app falls back to Georgia.

## Launcher
Copy `disctask.desktop` to `~/.local/share/applications/` and replace `/path/to/Disctask` with the real path.

## Export
The "Exportar notas" button saves all tasks and calendar events to `~/Downloads/disctask-notas.json` as `{tareas, horarios}`; an existing file is never overwritten.
