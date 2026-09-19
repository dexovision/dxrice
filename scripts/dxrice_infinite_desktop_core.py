import sys, struct, threading, time, os
from evdev import InputDevice, list_devices, ecodes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import move_window_exact_lua, batch_async, hyprctl_json
import dxrice_singleton

# Same exclusive-instance guard dxrice_auto_place_window.py uses -- this
# daemon has the same "exactly one per session, started by an unguarded
# autostart line" shape, so it has the same double-instance exposure
# (two copies would both react to every drag/pan input event and both
# issue their own batch of window moves) even though it had never actually
# been hit in practice the way the placement listener's was. Refuse to
# start a second copy rather than silently duplicating every window move.
_singleton_lock = dxrice_singleton.claim_single_instance("infinite-desktop-core")
if _singleton_lock is None:
    print("another dxrice_infinite_desktop_core.py already holds the lock for this "
          "session -- exiting.", flush=True)
    sys.exit(0)

speed = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

DEVICE_RESCAN_INTERVAL = 3.0

EVENT_SIZE = struct.calcsize('llHHi')
EV_KEY = 1; EV_REL = 2; REL_X = 0; REL_Y = 1
KEY_LEFTMETA = 125; KEY_RIGHTMETA = 126
KEY_LEFTALT = 56; KEY_RIGHTALT = 100
KEY_LEFTCTRL = 29; KEY_RIGHTCTRL = 97
BTN_LEFT = 272

STATE_FILE = "/tmp/infinite-desktop-state"
PROTECTED_APPS = ['brave-browser', 'chromium', 'chromium-browser', 'google-chrome',
                  'firefox', 'firefoxdeveloperedition', 'librewolf', 'vivaldi',
                  'opera', 'microsoft-edge']

lock = threading.Lock()
super_pressed = False; alt_pressed = False; ctrl_pressed = False; btn_left = False
acc_x = 0.0; acc_y = 0.0

window_drag_active = False
last_window_bounds = None
mouse_rel_x = 0
mouse_rel_y = 0

_inverted_cache = False
_inverted_last_check = 0.0
INVERTED_CACHE_TTL = 0.5

def get_cached_inverted():
    global _inverted_cache, _inverted_last_check
    now = time.time()
    if now - _inverted_last_check > INVERTED_CACHE_TTL:
        try:
            with open(STATE_FILE) as f:
                _inverted_cache = f.read().strip() == 'inverse'
        except Exception:
            _inverted_cache = False
        _inverted_last_check = now
    return _inverted_cache

def get_monitor_bounds():
    try:
        monitors = hyprctl_json(['monitors'])
        if monitors:
            m = next((x for x in monitors if x.get('focused', False)), monitors[0])
            return {
                'left': m['x'], 'right': m['x'] + m['width'],
                'top': m['y'], 'bottom': m['y'] + m['height'],
                'width': m['width'], 'height': m['height'],
                # Real refresh rate (this machine's panel is 144Hz, not the
                # 60Hz this loop used to assume) -- see get_frame_interval().
                'refreshRate': m.get('refreshRate', 60.0),
            }
    except Exception:
        pass
    return {'left': 0, 'right': 1920, 'top': 0, 'bottom': 1080, 'width': 1920, 'height': 1080, 'refreshRate': 60.0}

_monitor_bounds_cache = None
_monitor_bounds_last_check = 0.0
MONITOR_BOUNDS_CACHE_TTL = 1.0

def get_cached_monitor_bounds():
    global _monitor_bounds_cache, _monitor_bounds_last_check
    now = time.time()
    if _monitor_bounds_cache is None or (now - _monitor_bounds_last_check) > MONITOR_BOUNDS_CACHE_TTL:
        _monitor_bounds_cache = get_monitor_bounds()
        _monitor_bounds_last_check = now
    return _monitor_bounds_cache

def get_frame_interval():
    """Paces the pan/drag loops to the monitor's own real refresh rate
    instead of a hardcoded 60fps assumption -- sending position updates
    slower than the display can actually redraw is exactly what a fixed
    16ms (60Hz) sleep did on this machine's real 144Hz panel, and was a
    direct, measurable contributor to panning looking less smooth than the
    display is actually capable of."""
    rate = get_cached_monitor_bounds().get('refreshRate', 60.0) or 60.0
    return 1.0 / max(30.0, min(rate, 240.0))

# Idle poll rate for both while-True loops below, used whenever nothing is
# actually being panned/dragged right now -- there is no reason to wake up
# up to 240 times/sec (this machine's real refresh rate) just to re-check
# two booleans that a keyboard-reader thread updates asynchronously anyway.
# 60Hz still notices a drag start within ~16ms (imperceptible) while
# cutting idle wakeups by up to ~4x on a 240Hz panel and ~2.4x on this
# machine's own 144Hz one -- real, measured-in-kind savings for a loop that
# otherwise runs unconditionally for the entire session, not just while
# actively dragging.
IDLE_POLL_INTERVAL = 1.0 / 60.0

def get_floating_windows(workspace_id):
    try:
        clients = hyprctl_json(['clients']) or []
        return [w for w in clients if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id]
    except Exception:
        return []

def get_focused_window():
    try:
        return hyprctl_json(['activewindow'])
    except Exception:
        return None

def get_window_bounds(window):
    x, y = window['at'][0], window['at'][1]
    w, h = window['size'][0], window['size'][1]
    return {
        'left': x, 'right': x + w, 'top': y, 'bottom': y + h,
        'center_x': x + w // 2, 'center_y': y + h // 2
    }

# Edge-push drag (Super+click, dragging a window into the monitor's edge so
# it shoves the others along) can call pan_other_windows on every single
# frame while the edge is held -- previously this issued a fresh, blocking
# `hyprctl clients` query every single time, on the same thread that's also
# tracking the drag itself. The whole-desktop glide path just below
# (refresh_drag_cache/_drag_cache) already solved this exact problem by
# caching positions and applying each frame's delta directly instead of
# re-querying; this mirrors that same pattern for the edge-push path
# specifically, rather than inventing a second caching scheme.
_push_cache = {}
_push_cache_workspace = None
_push_cache_last_refresh = 0.0
PUSH_CACHE_REFRESH = 0.2


def _push_cache_workspace_reset():
    global _push_cache_workspace
    _push_cache_workspace = None


def pan_other_windows(excluded_addr, dx, dy, workspace_id):
    global _push_cache, _push_cache_workspace, _push_cache_last_refresh
    if dx == 0 and dy == 0:
        return
    try:
        now = time.time()
        fresh_start = workspace_id != _push_cache_workspace
        if fresh_start or (now - _push_cache_last_refresh) >= PUSH_CACHE_REFRESH:
            floating_windows = get_floating_windows(workspace_id)
            live = {w['address']: [w['at'][0], w['at'][1]] for w in floating_windows}
            if fresh_start:
                _push_cache = live
            else:
                # Merge, never replace -- identical reasoning to
                # refresh_drag_cache's own comment: this loop is the sole
                # authority on where the pushed windows are while a push is
                # in progress (it drives them with fire-and-forget moves),
                # so a read-back that lags those dispatches must not be
                # allowed to overwrite them and snap the windows backward.
                # The dragged window itself is excluded from the push below
                # and is moved by Hyprland's own drag, so its live position
                # is always the correct one to adopt.
                for addr, pos in live.items():
                    if addr not in _push_cache or addr == excluded_addr:
                        _push_cache[addr] = pos
                for addr in list(_push_cache):
                    if addr not in live:
                        del _push_cache[addr]
            _push_cache_workspace = workspace_id
            _push_cache_last_refresh = now

        exprs = []
        for addr, pos in _push_cache.items():
            if addr == excluded_addr:
                continue
            pos[0] += dx
            pos[1] += dy
            exprs.append(move_window_exact_lua(pos[0], pos[1], addr))
        batch_async(exprs)
    except Exception:
        pass

def monitor_window_drag():
    global window_drag_active, last_window_bounds, mouse_rel_x, mouse_rel_y

    dragged_window_addr = None
    _last_focused_poll = 0.0
    _cached_focused = None
    DRAG_POLL_INTERVAL = 0.1

    def poll_focused_throttled():
        nonlocal _last_focused_poll, _cached_focused
        now = time.time()
        if now - _last_focused_poll >= DRAG_POLL_INTERVAL:
            _cached_focused = get_focused_window()
            _last_focused_poll = now
        return _cached_focused

    while True:
        try:
            with lock:
                is_dragging = super_pressed and btn_left and not alt_pressed and not ctrl_pressed
                mouse_dx = mouse_rel_x
                mouse_dy = mouse_rel_y
                mouse_rel_x = 0
                mouse_rel_y = 0

            if is_dragging and not window_drag_active:
                focused = get_focused_window()
                if focused and focused.get('address'):
                    dragged_window_addr = focused['address']
                    window_drag_active = True
                    last_window_bounds = get_window_bounds(focused)
                    _last_focused_poll = time.time()
                    _cached_focused = focused

            elif not is_dragging and window_drag_active:
                window_drag_active = False
                dragged_window_addr = None
                last_window_bounds = None
                _push_cache_workspace_reset()

            if window_drag_active and dragged_window_addr:
                window = poll_focused_throttled()
                if window and window.get('address') == dragged_window_addr:
                    current_bounds = get_window_bounds(window)
                    monitor = get_cached_monitor_bounds()
                    MARGIN = 10

                    touch_left = current_bounds['left'] <= monitor['left'] + MARGIN
                    touch_right = current_bounds['right'] >= monitor['right'] - MARGIN
                    touch_top = current_bounds['top'] <= monitor['top'] + MARGIN
                    touch_bottom = current_bounds['bottom'] >= monitor['bottom'] - MARGIN

                    if (touch_left or touch_right or touch_top or touch_bottom) and (mouse_dx != 0 or mouse_dy != 0):
                        pan_dx = 0
                        pan_dy = 0

                        if touch_right and mouse_dx > 0:
                            pan_dx = -mouse_dx
                        elif touch_left and mouse_dx < 0:
                            pan_dx = -mouse_dx

                        if touch_bottom and mouse_dy > 0:
                            pan_dy = -mouse_dy
                        elif touch_top and mouse_dy < 0:
                            pan_dy = -mouse_dy

                        if pan_dx != 0 or pan_dy != 0:
                            workspace_id = get_cached_workspace_id()
                            if workspace_id is not None:
                                pan_other_windows(dragged_window_addr, int(pan_dx), int(pan_dy), workspace_id)

                    last_window_bounds = current_bounds
                else:
                    window_drag_active = False
                    dragged_window_addr = None

            time.sleep(get_frame_interval() if (is_dragging or window_drag_active) else IDLE_POLL_INTERVAL)
        except Exception:
            time.sleep(0.1)

def classify_device(path):
    try:
        dev = InputDevice(path)
        caps = dev.capabilities()
        dev.close()
    except Exception:
        return None

    keys = set(caps.get(ecodes.EV_KEY, []))
    rels = set(caps.get(ecodes.EV_REL, []))

    if ecodes.REL_X in rels and ecodes.REL_Y in rels and ecodes.BTN_LEFT in keys:
        return 'mouse'

    is_keyboard = (
        ecodes.KEY_A in keys and ecodes.KEY_Z in keys and ecodes.KEY_LEFTSHIFT in keys
        and (ecodes.KEY_LEFTMETA in keys or ecodes.KEY_RIGHTMETA in keys)
    )
    if is_keyboard:
        return 'keyboard'

    return None

def scan_devices():
    keyboards, mice = [], []
    for path in list_devices():
        kind = classify_device(path)
        if kind == 'mouse':
            mice.append(path)
        elif kind == 'keyboard':
            keyboards.append(path)
    return keyboards, mice

def kbd_reader_device(path):
    global super_pressed, alt_pressed, ctrl_pressed
    try:
        fd = open(path, 'rb')
    except Exception:
        return

    while True:
        try:
            data = fd.read(EVENT_SIZE)
        except Exception:
            break
        if not data or len(data) < EVENT_SIZE:
            break
        _, _, etype, code, value = struct.unpack('llHHi', data)
        if etype != EV_KEY:
            continue
        if value == 2:
            continue

        with lock:
            if code in (KEY_LEFTMETA, KEY_RIGHTMETA):
                super_pressed = (value == 1)
            elif code in (KEY_LEFTALT, KEY_RIGHTALT):
                alt_pressed = (value == 1)
            elif code in (KEY_LEFTCTRL, KEY_RIGHTCTRL):
                ctrl_pressed = (value == 1)

    try:
        fd.close()
    except Exception:
        pass

def mouse_reader_device(path):
    global acc_x, acc_y, btn_left, mouse_rel_x, mouse_rel_y
    try:
        fd = open(path, 'rb')
    except Exception:
        return

    while True:
        try:
            data = fd.read(EVENT_SIZE)
        except Exception:
            break
        if not data or len(data) < EVENT_SIZE:
            break
        _, _, etype, code, value = struct.unpack('llHHi', data)

        with lock:
            if etype == EV_KEY and code == BTN_LEFT:
                btn_left = (value == 1)
            elif etype == EV_REL:
                if code == REL_X:
                    mouse_rel_x += value
                elif code == REL_Y:
                    mouse_rel_y += value

                if super_pressed and alt_pressed:
                    sign = -1 if get_cached_inverted() else 1
                    if code == REL_X:
                        acc_x += value * speed * sign
                    elif code == REL_Y:
                        acc_y += value * speed * sign
                else:
                    acc_x = 0.0
                    acc_y = 0.0

    try:
        fd.close()
    except Exception:
        pass

_active_kbd_threads = {}
_active_mouse_threads = {}

def device_manager():
    WARMUP_DURATION = 20.0
    WARMUP_INTERVAL = 0.5
    start_time = time.time()

    while True:
        try:
            keyboards, mice = scan_devices()

            for path in keyboards:
                t = _active_kbd_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=kbd_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_kbd_threads[path] = nt
                    print(f"[+] Keyboard detected: {path}", flush=True)

            for path in mice:
                t = _active_mouse_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=mouse_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_mouse_threads[path] = nt
                    print(f"[+] Mouse detected: {path}", flush=True)
        except Exception as e:
            print(f"Error in device_manager: {e}", flush=True)

        elapsed = time.time() - start_time
        interval = WARMUP_INTERVAL if elapsed < WARMUP_DURATION else DEVICE_RESCAN_INTERVAL
        time.sleep(interval)

print("Preloading...", flush=True)
try:
    hyprctl_json(['activeworkspace'])
    hyprctl_json(['clients'])
except Exception:
    pass

threading.Thread(target=device_manager, daemon=True).start()
threading.Thread(target=monitor_window_drag, daemon=True).start()
print("Infinite Desktop active (automatic device detection)", flush=True)
print("Super+click: drag window (pushes others when it hits an edge)", flush=True)
print("Super+Alt+mouse: pan the whole desktop", flush=True)
print("Super+arrows: navigate via Hyprland bind", flush=True)
print("Super+Shift+arrows: move active window via Hyprland bind", flush=True)

_cached_workspace_id = None
_last_workspace_check = 0
WORKSPACE_CACHE_TTL = 2.0

def get_cached_workspace_id():
    global _cached_workspace_id, _last_workspace_check
    now = time.time()
    if _cached_workspace_id is None or (now - _last_workspace_check) > WORKSPACE_CACHE_TTL:
        try:
            ws = hyprctl_json(['activeworkspace'])
            _cached_workspace_id = ws['id']
            _last_workspace_check = now
        except Exception:
            pass
    return _cached_workspace_id

DRAG_CACHE_REFRESH = 0.2
_drag_cache = {}
_drag_cache_workspace = None
_drag_cache_last_refresh = 0.0

def refresh_drag_cache(workspace_id, force=False):
    """Keeps _drag_cache's WINDOW LIST current without ever clobbering the
    positions this loop is itself driving.

    The distinction matters and used to be a real source of pan jitter: the
    pan loop increments each cached position every frame and dispatches the
    move fire-and-forget (never waiting for Hyprland to confirm it landed),
    so for the duration of a pan THIS process is the authority on where
    these windows are -- its accumulated values are strictly more current
    than anything `hyprctl clients` can report, which necessarily lags by
    however many dispatches are still in flight. Wholesale-replacing the
    cache from that read-back every DRAG_CACHE_REFRESH seconds therefore
    threw away real, already-dispatched movement and snapped every window
    backward by the in-flight delta -- at 144Hz and a 0.2s refresh that is
    up to ~29 frames of motion discarded several times a second, which is
    exactly what "jitter"/"windows lag behind the camera" feels like.

    So: a refresh now only ADDS windows that appeared since the last one
    (taking Hyprland's position for those, since this loop has never
    touched them) and DROPS ones that closed or left the workspace.
    Windows already being tracked keep the position this loop computed.
    `force=True` (or a workspace change, or the start of a fresh pan, which
    resets _drag_cache_workspace to None) still does a full authoritative
    re-read, because at that point this loop is NOT mid-flight and
    Hyprland's state is the correct starting truth."""
    global _drag_cache, _drag_cache_workspace, _drag_cache_last_refresh
    now = time.time()
    fresh_start = force or workspace_id != _drag_cache_workspace
    if not fresh_start and (now - _drag_cache_last_refresh) < DRAG_CACHE_REFRESH:
        return
    try:
        clients = hyprctl_json(['clients']) or []
        live = {
            w['address']: [w['at'][0], w['at'][1]]
            for w in clients
            if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id
        }
        if fresh_start:
            _drag_cache = live
        else:
            for addr, pos in live.items():
                if addr not in _drag_cache:
                    _drag_cache[addr] = pos          # newly appeared -- adopt its real position
            for addr in list(_drag_cache):
                if addr not in live:
                    del _drag_cache[addr]            # closed / moved away -- stop driving it
        _drag_cache_workspace = workspace_id
        _drag_cache_last_refresh = now
    except Exception:
        pass


# Sending every frame instead of batching every 3rd: the send itself is a
# non-blocking Popen (batch_async in dxrice_hypr_ipc.py), so the poll loop
# never actually waits on hyprctl finishing -- there was no real cost being
# amortized by only sending every 3rd frame, just an extra ~33-50ms of
# input-to-motion latency and coarser (batched, less frequent) window
# movement, which reads as choppy/laggy panning compared to the edge-push
# drag path just below (monitor_window_drag), which already sends every
# frame and has never had this complaint.
BATCH_SEND_EVERY_N = 1
_pending_dx = 0
_pending_dy = 0
_frame_count = 0

_was_active = False
while True:
    time.sleep(get_frame_interval() if _was_active else IDLE_POLL_INTERVAL)

    with lock:
        active_drag = super_pressed and alt_pressed
        dx = acc_x
        dy = acc_y
        acc_x = 0.0
        acc_y = 0.0

    _was_active = active_drag
    if not active_drag:
        _drag_cache_workspace = None
        _pending_dx = 0
        _pending_dy = 0
        _frame_count = 0
        continue

    _pending_dx += dx
    _pending_dy += dy
    _frame_count += 1

    if _frame_count < BATCH_SEND_EVERY_N:
        continue
    _frame_count = 0

    idx = int(round(_pending_dx))
    idy = int(round(_pending_dy))
    _pending_dx -= idx
    _pending_dy -= idy

    try:
        workspace_id = get_cached_workspace_id()
        if workspace_id is None:
            continue

        refresh_drag_cache(workspace_id)

        if idx == 0 and idy == 0:
            continue

        exprs = []
        for addr, pos in _drag_cache.items():
            pos[0] += idx
            pos[1] += idy
            exprs.append(move_window_exact_lua(pos[0], pos[1], addr))

        batch_async(exprs)
    except Exception:
        pass
