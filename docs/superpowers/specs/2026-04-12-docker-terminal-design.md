# Docker Terminal — Design Spec

## Goal

Allow admin users to open an interactive shell (`/bin/sh`) inside a running Docker container, directly from the admin UI, via xterm.js + WebSocket + `docker exec`.

## Architecture

A **Terminal** button appears on each running container in the DockerfilesPage sidebar ("Running instances"). Clicking it opens a WebSocket to the backend, which creates a `docker exec` session in the target container. stdin/stdout flow bidirectionally over the WebSocket. The frontend renders the terminal in a floating, draggable, resizable window (same pattern as ChatWindow).

## Backend

### New endpoint

- **Path:** `GET /api/admin/containers/{container_id}/terminal`
- **Protocol:** WebSocket
- **File:** `backend/src/agflow/api/admin/terminal.py`
- **Auth:** None (admin-only internal tool behind Caddy)

### Flow

1. Accept WebSocket connection
2. Validate that `container_id` exists and is running (via aiodocker)
3. Create exec: `container.exec(cmd=["/bin/sh"], stdin=True, tty=True, stdout=True, stderr=True)`
4. Start the exec, get a bidirectional stream
5. Run two concurrent tasks:
   - **WS → exec stdin:** read binary frames from WebSocket, write to exec stdin
   - **exec stdout → WS:** read from exec stdout, send binary frames to WebSocket
6. On WebSocket disconnect or exec exit, clean up both sides

### Error handling

- Container not found → close WebSocket with code 4004
- Container not running → close WebSocket with code 4009
- Exec fails to start → close WebSocket with code 4500

## Frontend

### Dependencies to add

- `@xterm/xterm` (xterm.js v5)
- `@xterm/addon-fit` (auto-resize terminal to container)

### New component: `TerminalWindow.tsx`

- Floating window, same pattern as `ChatWindow.tsx`:
  - Draggable header bar
  - Resizable (min 400×300)
  - Position + size persisted in localStorage
  - Close button
- Header shows container name
- Body contains the xterm.js `<Terminal>` instance
- On mount: open WebSocket to `/api/admin/containers/{containerId}/terminal`
- Wire xterm `onData` → `ws.send()` (user input)
- Wire `ws.onmessage` → `xterm.write()` (container output)
- On unmount or close: close WebSocket, dispose xterm

### Button placement

- In DockerfilesPage sidebar, "Running instances" section
- Icon: `TerminalSquare` (lucide-react)
- One button per running container, next to the existing Stop button
- Clicking opens `TerminalWindow` for that container

## Caddy

Caddy v2 handles WebSocket upgrade automatically when reverse-proxying. No Caddyfile changes needed.

## Out of scope

- No session persistence / history
- No WebSocket authentication
- No REST API for filesystem exploration (terminal covers this)
- No dynamic PTY resize (fixed dimensions in v1)
- No multiple terminal tabs per container
