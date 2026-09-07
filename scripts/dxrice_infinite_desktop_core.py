import sys, struct, threading, time, subprocess, json, os
from evdev import InputDevice, list_devices, ecodes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import move_window_exact_lua, batch_async

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
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        if monitors:
            for m in monitors:
                if m.get('focused', False):
                    return {
                        'left': m['x'], 'right': m['x'] + m['width'],
                        'top': m['y'], 'bottom': m['y'] + m['height'],
                        'width': m['width'], 'height': m['height']
                    }
            m = monitors[0]
            return {
                'left': m['x'], 'right': m['x'] + m['width'],
                'top': m['y'], 'bottom': m['y'] + m['height'],
                'width': m['width'], 'height': m['height']
            }
    except Exception:
        pass
    return {'left': 0, 'right': 1920, 'top': 0, 'bottom': 1080, 'width': 1920, 'height': 1080}

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

def get_floating_windows(workspace_id):
    try:
        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        clients = json.loads(r.stdout)
        return [w for w in clients if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id]
    except Exception:
        return []

def get_focused_window():
    try:
        r = subprocess.run(['hyprctl', 'activewindow', '-j'], capture_output=True, text=True, timeout=0.1)
        return json.loads(r.stdout)
    except Exception:
        return None

def get_window_bounds(window):
    x, y = window['at'][0], window['at'][1]
    w, h = window['size'][0], window['size'][1]
    return {
        'left': x, 'right': x + w, 'top': y, 'bottom': y + h,
        'center_x': x + w // 2, 'center_y': y + h // 2
    }

def pan_other_windows(excluded_addr, dx, dy, workspace_id):
    if dx == 0 and dy == 0:
        return
    try:
        floating_windows = get_floating_windows(workspace_id)
        exprs = []
        for w in floating_windows:
            if w['address'] != excluded_addr:
                nx = int(w['at'][0] + dx)
                ny = int(w['at'][1] + dy)
                exprs.append(move_window_exact_lua(nx, ny, w['address']))
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

            time.sleep(0.016)
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
    subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.5)
    subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.5)
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
            r = subprocess.run(['hyprctl', 'activeworkspace', '-j'],
                               capture_output=True, text=True, timeout=0.1)
            ws = json.loads(r.stdout)
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
    global _drag_cache, _drag_cache_workspace, _drag_cache_last_refresh
    now = time.time()
    if (not force
            and workspace_id == _drag_cache_workspace
            and (now - _drag_cache_last_refresh) < DRAG_CACHE_REFRESH):
        return
    try:
        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        clients = json.loads(r.stdout)
        _drag_cache = {
            w['address']: [w['at'][0], w['at'][1]]
            for w in clients
            if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id
        }
        _drag_cache_workspace = workspace_id
        _drag_cache_last_refresh = now
    except Exception:
        pass

BATCH_SEND_EVERY_N = 3
_pending_dx = 0
_pending_dy = 0
_frame_count = 0

while True:
    time.sleep(0.016)

    with lock:
        active_drag = super_pressed and alt_pressed
        dx = acc_x
        dy = acc_y
        acc_x = 0.0
        acc_y = 0.0

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
