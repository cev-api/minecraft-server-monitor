#!/usr/bin/env python3

import os
import sys
import json
import time
import socket
import struct
import hashlib
from typing import Optional, Dict, Any, Tuple, List

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    from rich.text import Text
except Exception as e:
    print("This script now requires 'rich'. Install with: pip install rich")
    raise

# === Requests (required for Discord) ===
try:
    import requests
except Exception:
    print("This script requires 'requests'. Install with: pip install requests")
    raise

console = Console()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(APP_DIR, "mc_state.json")

DEFAULT_INTERVAL_SEC = 30
DEFAULT_PROTOCOL = 767   # works fine for modern servers for status ping

# ===============
# UI helpers
# ===============

def _ui_width() -> int:
    try:
        w = getattr(console, "width", 80) or 80
        return max(60, min(120, int(w) - 2))
    except Exception:
        return 100


def _banner_lines() -> List[str]:
    return [
        "░▒▓██████████████▓▒░ ░▒▓██████▓▒░░▒▓███████▓▒░░▒▓██████████████▓▒░ ░▒▓██████▓▒░░▒▓███████▓▒░  ",
        "░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ ",
        "░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ ",
        "░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ ",
        "░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ ",
        "░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░░▒▓██████▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓█▓▒░░▒▓██████▓▒░░▒▓█▓▒░░▒▓█▓▒░ ",
        "",
    ]

def _gradient_banner_text() -> Text:
    lines = _banner_lines()
    text = Text()
    # simple purple gradient (start -> end)
    start_rgb = (85, 0, 145)
    end_rgb   = (199, 162, 255)
    n = max(1, len(lines))
    for i, line in enumerate(lines):
        t = 0 if n == 1 else i/(n-1)
        r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * t)
        g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * t)
        b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * t)
        text.append(line + "", style=f"rgb({r},{g},{b})")
    text.append("\n                                                   Minecraft Server Monitor (Discord Alerts)\n", style="bold white")
    return text

def _screen_header() -> None:
    console.clear()
    console.print(_gradient_banner_text())

# ===============
# Persistence
# ===============

def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    tmp = f"{path}.{int(time.time()*1000)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {
            "webhook_url": None,
            "interval_sec": DEFAULT_INTERVAL_SEC,
            "verbose_status": False,
            "servers": [],
            "last": {}
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"webhook_url": None, "interval_sec": DEFAULT_INTERVAL_SEC, "verbose_status": False, "servers": [], "last": {}}

def save_state(st: Dict[str, Any]) -> None:
    _atomic_write_json(STATE_FILE, st)

# ===============
# Discord
# ===============

def send_discord(webhook_url: Optional[str], title: str, description: str, fields: Dict[str, str]) -> None:
    if not webhook_url:
        return
    embed = {
        "title": title,
        "description": description,
        "fields": [{"name": k, "value": v, "inline": False} for (k, v) in fields.items()]
    }
    payload = {"content": None, "embeds": [embed]}
    try:
        r = requests.post(webhook_url, json=payload, timeout=15)
        if r.status_code >= 300:
            console.log(f"[yellow]Discord returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        console.log(f"[yellow]Discord send failed: {e}")

# ===============
# Input helpers
# ===============

def parse_host_port(s: str, default_port: int = 25565) -> Tuple[str, int]:
    s = (s or "").strip()
    if not s:
        return ("", default_port)

    if s.startswith("["):
        end = s.find("]")
        if end != -1:
            host = s[1:end]
            rest = s[end+1:]
            if rest.startswith(":"):
                try:
                    port = int(rest[1:])
                except Exception:
                    port = default_port
            else:
                port = default_port
            return (host, port)
        return (s, default_port)

    if s.count(":") == 1:
        host, p = s.split(":", 1)
        try:
            port = int(p)
        except Exception:
            port = default_port
        return (host, port)

    return (s, default_port)

# ===============
# Minecraft status ping (1.7+)
# ===============

def _pack_varint(n: int) -> bytes:
    out = bytearray()
    v = n & 0xFFFFFFFF
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _pack_mc_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return _pack_varint(len(b)) + b

def _read_varint(sock: socket.socket, timeout: float = 5.0) -> int:
    sock.settimeout(timeout)
    num = 0
    num_read = 0
    while True:
        b = sock.recv(1)
        if not b:
            raise IOError("Socket closed while reading VarInt")
        val = b[0]
        num |= (val & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise IOError("VarInt too big")
        if (val & 0x80) == 0:
            break
    return num

def _recv_exact(sock: socket.socket, n: int, timeout: float = 5.0) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise IOError("Socket closed while reading")
        data.extend(chunk)
    return bytes(data)

def _flatten_description(desc: Any) -> str:
    if desc is None:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        parts = []
        if "text" in desc and isinstance(desc["text"], str):
            parts.append(desc["text"])
        if "extra" in desc and isinstance(desc["extra"], list):
            for it in desc["extra"]:
                parts.append(_flatten_description(it))
        return "".join(parts)
    if isinstance(desc, list):
        return "".join(_flatten_description(x) for x in desc)
    return str(desc)

def _strip_motd_color_codes(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "§":
            if i + 1 < len(s):
                i += 2
                continue
            else:
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)

def query_status(host: str, port: int = 25565, protocol: int = DEFAULT_PROTOCOL, timeout: float = 5.0) -> Dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            data = b""
            data += _pack_varint(0x00)
            data += _pack_varint(int(protocol))
            data += _pack_mc_string(host)
            data += struct.pack(">H", port)
            data += _pack_varint(1)
            packet = _pack_varint(len(data)) + data
            sock.sendall(packet)

            req = _pack_varint(1) + b"\x00"
            sock.sendall(req)

            size = _read_varint(sock, timeout)
            body = _recv_exact(sock, size, timeout)

            idx = 0
            pid = 0; shift = 0
            while True:
                b = body[idx]; idx += 1
                pid |= (b & 0x7F) << shift
                if (b & 0x80) == 0: break
                shift += 7
                if idx >= len(body) or shift > 35:
                    raise IOError("Bad packet id VarInt")

            json_len = 0; shift = 0
            while True:
                b = body[idx]; idx += 1
                json_len |= (b & 0x7F) << shift
                if (b & 0x80) == 0: break
                shift += 7
                if idx >= len(body) or shift > 35:
                    raise IOError("Bad JSON length VarInt")

            js = body[idx:idx+json_len]
            data_json = json.loads(js.decode("utf-8", errors="replace"))

            motd_raw = _flatten_description(data_json.get("description"))
            motd = _strip_motd_color_codes(motd_raw).strip()
            players = data_json.get("players", {}) or {}
            version = data_json.get("version", {}) or {}
            out = {
                "online": True,
                "motd": motd,
                "players": {
                    "online": int(players.get("online", 0)),
                    "max": int(players.get("max", 0))
                },
                "version": {
                    "name": str(version.get("name", "")),
                    "protocol": int(version.get("protocol", 0)) if isinstance(version.get("protocol", 0), int) else 0
                }
            }
            return out
    except Exception as e:
        return {"online": False, "error": str(e)}

# ===============
# State hashing / formatting
# ===============

def _server_key(host: str, port: int) -> str:
    return f"{host}:{port}"

def _hash_state(s: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    payload = {
        "online": s.get("online", False),
        "motd": s.get("motd", ""),
        "players_online": ((s.get("players") or {}).get("online", 0)),
        "players_max": ((s.get("players") or {}).get("max", 0)),
        "version_name": ((s.get("version") or {}).get("name", "")),
        "version_protocol": ((s.get("version") or {}).get("protocol", 0)),
    }
    h.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return h.hexdigest()

def _format_fields(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, str]:
    def fmt(s: Optional[Dict[str, Any]]) -> str:
        if not s:
            return "(none)"
        if not s.get("online", False):
            return "Offline"
        pn = s.get("players", {}).get("online", 0)
        pm = s.get("players", {}).get("max", 0)
        ver = s.get("version", {}).get("name", "")
        motd = s.get("motd", "")
        return f"Online: {pn}/{pm} Version: {ver} MOTD: {motd}"
    return {"Previous": fmt(old), "Current": fmt(new)}

# ===============
# Monitor engine
# ===============

def monitor_once(state: Dict[str, Any], srv: Dict[str, Any]) -> None:
    host = srv.get("host")
    port = int(srv.get("port", 25565))
    name = srv.get("name") or _server_key(host, port)
    protocol = int(srv.get("protocol", DEFAULT_PROTOCOL))
    if not host:
        return

    key = _server_key(host, port)
    status = query_status(host, port, protocol=protocol, timeout=6.0)

    now_hash = _hash_state(status)
    prev = (state.get("last") or {}).get(key, {})
    prev_hash = prev.get("hash")

    if prev_hash != now_hash:
        fields = _format_fields(prev.get("data"), status)
        title = f"[{name}] Status Changed"
        desc = f"{host}:{port}"
        send_discord(state.get("webhook_url"), title, desc, fields)

        if status.get("online", False):
            pn = status["players"]["online"]
            pm = status["players"]["max"]
            ver = status["version"]["name"]
            console.print(f"[green][CHANGE][/green] {name} {host}:{port} -> Online {pn}/{pm}, {ver}")
        else:
            console.print(f"[red][CHANGE][/red] {name} {host}:{port} -> Offline ({status.get('error','')})")

        state.setdefault("last", {})[key] = {"hash": now_hash, "data": status}
        save_state(state)
    else:
        if state.get("verbose_status"):
            console.print(f"[purple][OK][/purple] {name} checked, no change.")


def monitor_loop(state: Dict[str, Any]) -> None:
    interval = int(state.get("interval_sec", DEFAULT_INTERVAL_SEC))
    servers = list(state.get("servers", []))

    if not servers:
        _screen_header()
        console.print("[yellow]No servers configured. Add at least one first.")
        return

    _screen_header()

    width = _ui_width()
    table = Table(title="Monitoring", box=box.SIMPLE, expand=False)
    table.width = width
    table.add_column("#", style="bold purple", no_wrap=True)
    table.add_column("Name", overflow="fold", max_width=max(12, width//4))
    table.add_column("Host:Port", overflow="fold", max_width=max(16, width//3))
    table.add_column("Proto", style="magenta", no_wrap=True)
    for i, s in enumerate(servers):
        table.add_row(str(i), s.get("name") or _server_key(s["host"], int(s.get("port",25565))), _server_key(s["host"], int(s.get("port",25565))), str(s.get("protocol", DEFAULT_PROTOCOL)))
    console.print(Panel(table, border_style="purple", width=width))
    console.print(Panel(f"Interval: {interval}s — Press Ctrl+C to stop", border_style="purple", width=width))
    console.print()

    try:
        while True:
            t0 = time.time()
            for srv in list(state.get("servers", [])):
                monitor_once(state, srv)
            elapsed = time.time() - t0
            sleep_for = max(1, interval - int(elapsed))
            for _ in range(sleep_for):
                time.sleep(1)
    except KeyboardInterrupt:
        console.print("[purple]Stopping...[/purple]")
        time.sleep(0.3)
        console.print("[green]Stopped.[/green]")

# ===============
# Menus (Rich-only) — each option has its OWN page (clear + banner)
# ===============

def list_servers(state: Dict[str, Any]) -> None:
    _screen_header()
    srvs = state.get("servers", [])
    if not srvs:
        console.print("[yellow]No servers configured yet.")
        return
    width = _ui_width()
    table = Table(title="Configured Servers", box=box.SIMPLE)
    table.width = width
    table.add_column("#", style="bold purple", no_wrap=True)
    table.add_column("Name", overflow="fold", max_width=max(12, width//4))
    table.add_column("Host:Port", overflow="fold", max_width=max(16, width//2))
    table.add_column("Protocol", style="magenta", no_wrap=True)
    for i, s in enumerate(srvs):
        table.add_row(str(i), s.get("name") or _server_key(s["host"], int(s.get("port",25565))), _server_key(s["host"], int(s.get("port",25565))), str(s.get("protocol", DEFAULT_PROTOCOL)))
    console.print(Panel(table, border_style="purple", width=width))

def add_server_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    host_in = console.input("Host (or host:port / [IPv6]:port): ").strip()
    host, port = parse_host_port(host_in, default_port=25565)
    if not host:
        console.print("[yellow]Host is required.")
        return
    name = console.input("Display name (optional): ").strip()
    proto_s = console.input(f"Protocol [{DEFAULT_PROTOCOL}]: ").strip() or str(DEFAULT_PROTOCOL)
    try:
        protocol = int(proto_s)
    except Exception:
        protocol = DEFAULT_PROTOCOL

    state.setdefault("servers", []).append({
        "host": host,
        "port": int(port),
        "name": name or None,
        "protocol": protocol
    })
    save_state(state)
    console.print(f"[green]Added {host}:{port} ({name or 'no name'})")

def edit_server_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    srvs = state.get("servers", [])
    if not srvs:
        console.print("[yellow]No servers to edit.")
        return
    list_servers(state)
    s = console.input("Index to edit: ").strip()
    if not s.isdigit():
        console.print("[yellow]Enter a valid index.")
        return
    i = int(s)
    if not (0 <= i < len(srvs)):
        console.print("[yellow]Index out of range.")
        return
    srv = srvs[i]

    console.print(f"Editing [{i}] {srv.get('name') or _server_key(srv['host'], int(srv.get('port',25565)))}")
    host_in = console.input(f"Host (or host:port) [{_server_key(srv['host'], int(srv.get('port',25565)))}]: ").strip()
    if host_in:
        h, p = parse_host_port(host_in, default_port=int(srv.get('port',25565)))
        srv["host"], srv["port"] = h, int(p)
    nm = console.input(f"Display name [{srv.get('name') or ''}]: ").strip()
    if nm or nm == "":
        srv["name"] = nm or None
    proto_s = console.input(f"Protocol [{srv.get('protocol', DEFAULT_PROTOCOL)}]: ").strip()
    if proto_s:
        try:
            srv["protocol"] = int(proto_s)
        except Exception:
            pass
    save_state(state)
    console.print("[green]Server updated.")

def remove_server_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    srvs = state.get("servers", [])
    if not srvs:
        console.print("[yellow]No servers to remove.")
        return
    list_servers(state)
    s = console.input("Index to remove: ").strip()
    try:
        i = int(s)
        if 0 <= i < len(srvs):
            rem = srvs.pop(i)
            save_state(state)
            last = state.get("last") or {}
            last.pop(_server_key(rem.get("host","?"), int(rem.get("port",25565))), None)
            save_state(state)
            console.print("[green]Removed.")
        else:
            console.print("[yellow]Index out of range.")
    except Exception:
        console.print("[yellow]Invalid index.")

def set_webhook_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    cur = state.get("webhook_url") or "(not set)"
    width = _ui_width()
    table = Table(box=box.SIMPLE, show_edge=False)
    table.width = width - 2
    table.add_column("Field", style="purple", no_wrap=True)
    table.add_column("Value")
    table.add_row("Current", cur)
    console.print(Panel(table, title="Discord Webhook", border_style="purple", width=width))
    new = console.input("Paste Discord webhook (or blank to keep): ").strip()
    if new:
        state["webhook_url"] = new
        save_state(state)
        console.print("[green]Webhook saved.")

def set_interval_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    cur = int(state.get("interval_sec", DEFAULT_INTERVAL_SEC))
    s = console.input(f"Check interval seconds [{cur}]: ").strip()
    if s:
        try:
            v = int(s)
            if v < 1:
                raise ValueError()
            state["interval_sec"] = v
            save_state(state)
            console.print("[green]Interval updated.")
        except Exception:
            console.print("[yellow]Enter a positive integer.")

def toggle_verbose_flow(state: Dict[str, Any]) -> None:
    _screen_header()
    state["verbose_status"] = not bool(state.get("verbose_status"))
    save_state(state)
    console.print(f"[green]Verbose heartbeat is now {'ON' if state['verbose_status'] else 'OFF'}.")

# ===============
# Main menu (Rich-only)
# ===============

def _render_main_menu(state: Dict[str, Any]) -> None:
    _screen_header()
    width = _ui_width()
    table = Table(box=box.SIMPLE, show_edge=False, expand=False, padding=(0,1))
    table.width = width - 2
    table.add_column("#", style="bold purple", no_wrap=True)
    table.add_column("Main Menu", style="bold white")
    table.add_row("0", "Start monitoring")
    table.add_row("1", "List servers")
    table.add_row("2", "Add server")
    table.add_row("3", "Edit server")
    table.add_row("4", "Remove server")
    table.add_row("5", f"Set Discord webhook ({'set' if state.get('webhook_url') else 'not set'})")
    table.add_row("6", f"Set interval (currently {state.get('interval_sec', DEFAULT_INTERVAL_SEC)}s)")
    table.add_row("7", f"Toggle status heartbeat (currently {'ON' if state.get('verbose_status') else 'OFF'})")
    table.add_row("8", "Quit")
    console.print(Panel(table, border_style="purple", width=width))

def main_menu() -> None:
    st = load_state()
    while True:
        _render_main_menu(st)
        choice = console.input("Select: ").strip().lower()
        if choice == "0":
            monitor_loop(st)
        elif choice == "1":
            list_servers(st)
            console.print()
            console.input("Press Enter to return to menu...")  

        elif choice == "2":
            add_server_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "3":
            edit_server_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "4":
            remove_server_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "5":
            set_webhook_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "6":
            set_interval_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "7":
            toggle_verbose_flow(st)
            console.print()
            console.input("Press Enter to return to menu...")  
        elif choice == "8":
            console.print("Bye.")
            return
        else:
            console.print("[yellow]Invalid option.")
        # loop back to top; screen will be cleared by _render_main_menu

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print()
        console.print("[purple]Exiting.[/purple]") 
