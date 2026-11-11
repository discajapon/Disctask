# Disctask

Daily task app for Ubuntu with a liquid glass look. Add tasks per day, check them off, browse days with ‹ › and years with « ».

## Calendar
The 🗓 button opens a weekly schedule next to the tasks (the window widens to fit).

- Click an empty slot for a 1 h event, or drag to size it (15-min steps).
- Drag an event to move it to another hour or day; drag its top or bottom edge to make it longer or shorter.
- Click an event to edit its title, translucent color, date, times and description. Links in the description (`https://…`, `www.…`) are clickable and open in your browser.
- Overlapping events sit side by side.
- Drag a task from the list onto the calendar to drop a 1 h box titled like the task (the task stays in the list and is not ticked). The calendar must be open; hover the top or bottom edge while dragging to scroll.
- Drag the left or right edge of a box across other days: a dashed band shows the span, and on release it splits into one box per day with the same hours, title, colour and description.

## Run
Needs GTK3 + WebKit2GTK (`gir1.2-webkit2-4.1`).

    ./disctask.py

Data is stored in `~/.local/share/disctask`.

The app forces WebKit's GPU renderer when OpenGL works, since WebKitGTK may otherwise paint on the CPU (about 9 fps with the glass effects). If you see rendering glitches, run `WEBKIT_FORCE_DMABUF_RENDERER=0 ./disctask.py`.

That renderer leaks one `sync_file` file descriptor per presented frame. At the usual 1024-fd limit the web process wedged at 100% CPU after a few minutes (the app "froze"), so `disctask.py` raises the limit, the page pauses its endless animations after 20 s without input (and whenever the window is unfocused), and a dead web process is reloaded.

## Data, offline use and sync
The app is offline-first: tasks and events live in the WebView's localStorage under `~/.local/share/disctask` (fonts and wallpaper are bundled) and everything works without internet. If stored data is ever unreadable it is kept as `disctask-corrupt` / `disctask-cal-corrupt` instead of being overwritten. "Exportar notas" saves a backup. The first run after updating also keeps a raw copy of the old data in `localStorage['disctask-premigrate']`.

To mirror the data on the VPS (and the phone), click the status button in the header (`○ solo local`), keep the server `https://discajapon.com/disctask` and paste the device token. From then on:

- Every task and event has a UUID, an `updated_at` and soft deletes (tombstones). The first sync uploads what is already on the PC.
- Changes queue locally and are sent a couple of seconds after an edit, on reconnect, and every 60 s, retrying with exponential backoff (5 s up to 5 min). The button shows `● sincronizado`, `◐ pendiente (n)`, `○ sin conexión` or `⚠ token`.
- Conflicts: the newest edit **per record** wins (server keeps the max `updated_at`; a device clock more than 5 min ahead is clamped). A delete is just an edit, so a later edit resurrects it. Limitation: if two devices change different fields of the same task offline, one whole record wins.

## Server (VPS)
`server/` is one Python process (Starlette + the `mcp` SDK, SQLite in WAL) behind the existing nginx at `https://discajapon.com/disctask/`:

- `/api/sync` (device token): `POST {since, changes:{tasks,events}}` -> everything newer than `since` + new cursor. Idempotent; `server/store.py` has the merge rules.
- `/mcp` (separate MCP token): remote MCP, Streamable HTTP, same tools as the local server but addressed by id: `list_tasks`, `list_events`, `add_task`, `update_task`, `complete_task`, `delete_task`/`restore_task`, `add_event`, `update_event`, `delete_event`/`restore_event`, plus `today_summary` and `tasks_today` for voice. Deletes are soft and reversible; there is no bulk delete. Add `https://discajapon.com/disctask/mcp` as a custom connector in Claude with `Authorization: Bearer <MCP token>`.
- `/` is the APK download page (version, date, size, sha256) and `/dl/` the files.

Deploy: `./deploy/deploy.sh` (ssh as root, idempotent; creates the `disctask` user, systemd unit, nginx route with rollback if `nginx -t` fails, daily backup timer). Tokens are generated on the server in `/etc/disctask/env` (0600) and never printed or committed; read or rotate them there (`systemctl restart disctask`). The device and MCP tokens are separate so one can be revoked without breaking the other. Set `DISCTASK_TZ` there for "today".

## Android APK
`android/` wraps the same `index.html` with Capacitor (touch, local reminders: events 10 min before, pending tasks at 08:00, all offline). `android/build.sh` builds the signed `dist/disctask-<version>.apk` + `latest.json` (needs node, Android SDK; it downloads a user-local JDK 21 on first run); `android/publish.sh` uploads them to the VPS. The signing key is created in `~/.config/disctask/signing/` outside the repo: back it up, because a new key means the phone must uninstall before updating. Bump `version` in `android/package.json` for each release. The proprietary font is not bundled in the APK (falls back to a serif).

## Tests
`python3 server/tests/test_store.py` (sync rules, no deps) and `python3 server/tests/test_app.py` (auth, no-redirect MCP, sync over real HTTP). `python3 tests/test_sync.py` runs two real app pages through a real server (offline edits, delete vs edit, migration; needs a display, ~15 s). `python3 tests/test_app.py` runs the real app on a throwaway data dir (needs a display, ~50 s). `DISCTASK_DATA=<dir>` points the app at any data dir.

## Local MCP (legacy, Claude Desktop and Claude Code)
Superseded by the remote MCP above, which also works from Claude voice calls; this stdio server still works against the local app (its edits are synced like any other).

`mcp_server.py` lets Claude read and edit your tasks and calendar events: `list_tasks`, `list_events` (optional `date`), `add_task`, `update_task`, `delete_task`, `add_event`, `update_event`, `delete_event`. Edits are not written to the app's database (the open app keeps its data in memory and would overwrite them): they are queued in `inbox.jsonl` in the data dir, and the app applies them within a second (or at next launch if it is closed). Reads come from the database, so they can lag a moment behind. Needs `pip install mcp`.

    claude mcp add disctask --scope user -- python3 /path/to/Disctask/mcp_server.py

For Claude Desktop add to `~/.config/Claude/claude_desktop_config.json` and restart it:

    {"mcpServers": {"disctask": {"command": "python3", "args": ["/path/to/Disctask/mcp_server.py"]}}}

`python3 tests/test_mcp.py` checks it.

## Font
The UI uses Anthropic Serif. It is not in the repo (proprietary): install it system-wide, or drop the `.otf` files into `fonts/` (ignored by git). Without it the app falls back to Georgia.

## Launcher
Copy `disctask.desktop` to `~/.local/share/applications/` and replace `/path/to/Disctask` with the real path.

## Export
The "Exportar notas" button saves all tasks and calendar events to `~/Downloads/disctask-notas.json` as `{tareas, horarios}`; an existing file is never overwritten.
