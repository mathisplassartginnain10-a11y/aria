"""
Serveur mobile PWA + WebSocket pour contrôle ARIA via Tailscale (Sprint D v2).
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import app_paths
import websockets

logger = logging.getLogger(__name__)

_HTTP_PORT: int | None = None
_WS_PORT: int | None = None
_TAILSCALE_IP = "100.73.160.68"
_mobile_clients: set[Any] = set()
_ws_loop: asyncio.AbstractEventLoop | None = None
_started = False


def _find_free_port(start: int = 5000, host: str = "0.0.0.0") -> int:
    for port in range(start, start + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Aucun port libre à partir de {start}")


def _save_ports(http_port: int, ws_port: int) -> None:
    data_dir = app_paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "http_port": http_port,
        "ws_port": ws_port,
        "ip": _TAILSCALE_IP,
        "url": f"http://{_TAILSCALE_IP}:{http_port}",
        "ws_url": f"ws://{_TAILSCALE_IP}:{ws_port}",
    }
    (data_dir / "mobile_ports.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _broadcast_mobile(message: dict) -> None:
    if not _mobile_clients or _ws_loop is None:
        return
    raw = json.dumps(message, ensure_ascii=False)

    async def _send() -> None:
        dead = []
        for ws in list(_mobile_clients):
            try:
                await ws.send(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _mobile_clients.discard(ws)

    asyncio.run_coroutine_threadsafe(_send(), _ws_loop)


def _relay_ui_event(event_name: str, data: Any) -> None:
    mapping = {
        "assistant_token": ("token", lambda d: d),
        "assistant_done": ("done", lambda d: d or ""),
        "status_change": ("status", lambda d: d),
        "stt_result": ("stt_result", lambda d: d),
        "toast": ("toast", lambda d: d if isinstance(d, dict) else {"message": str(d), "type": "info"}),
        "user_message": ("user_message", lambda d: d),
    }
    if event_name not in mapping:
        return
    msg_type, fn = mapping[event_name]
    _broadcast_mobile({"type": msg_type, "data": fn(data)})


def _handle_mobile_action(payload: dict) -> None:
    action = payload.get("action")
    try:
        import ui_bridge as ui
    except Exception:
        logger.exception("ui_bridge indisponible")
        return

    if action == "ask":
        text = str(payload.get("text", "")).strip()
        conv_mode = str(payload.get("conv_mode") or "ecrit")
        if text:
            threading.Thread(
                target=ui.ask,
                args=(text, conv_mode),
                daemon=True,
                name="ARIA-MobileAsk",
            ).start()
    elif action == "stop_generation":
        threading.Thread(target=ui.stop_generation, daemon=True).start()
    elif action == "start_mic":
        threading.Thread(target=ui.start_mic, daemon=True).start()
    elif action == "stop_mic":
        threading.Thread(target=ui.stop_mic, daemon=True).start()
    elif action == "launch_app":
        name = str(payload.get("name", "")).strip()
        if name:
            threading.Thread(
                target=lambda: ui.ask(f"lance {name}", "ecrit"),
                daemon=True,
            ).start()
    elif action == "volume":
        level = payload.get("level", 50)
        threading.Thread(
            target=lambda: ui.ask(f"volume à {level}", "ecrit"),
            daemon=True,
        ).start()
    elif action == "quick":
        cmd = str(payload.get("cmd", "")).strip()
        if cmd:
            threading.Thread(target=ui.ask, args=(cmd, "ecrit"), daemon=True).start()


async def _ws_handler(websocket) -> None:
    _mobile_clients.add(websocket)
    _broadcast_mobile({"type": "status", "data": "idle"})
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                _handle_mobile_action(msg)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _mobile_clients.discard(websocket)


def _run_ws_server(port: int) -> None:
    global _ws_loop
    loop = asyncio.new_event_loop()
    _ws_loop = loop
    asyncio.set_event_loop(loop)

    async def _serve() -> None:
        async with websockets.serve(_ws_handler, "0.0.0.0", port, ping_interval=20):
            logger.info("Mobile WS sur 0.0.0.0:%s", port)
            await asyncio.Future()

    loop.run_until_complete(_serve())


_PWA_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="theme-color" content="#04080F">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<title>ARIA Mobile</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;background:#04080F;color:#E8EDFF;font-family:system-ui,sans-serif;touch-action:manipulation}
header{display:flex;align-items:center;gap:10px;padding:14px 16px;background:rgba(8,16,32,.95);border-bottom:1px solid rgba(100,130,255,.2);position:sticky;top:0;z-index:10}
.logo{font-weight:800;font-size:18px;background:linear-gradient(135deg,#6C8EFF,#A78BFA);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.dot{width:10px;height:10px;border-radius:50%;background:#EF4444;flex-shrink:0}
.dot.ok{background:#4ADE80}
.sub{font-size:11px;color:#8892B0;margin-left:auto;text-align:right}
.quick{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:12px}
.qbtn{min-height:48px;border:1px solid rgba(108,142,255,.25);background:rgba(108,142,255,.08);color:#C7D2FE;border-radius:12px;font-size:12px;padding:8px 4px;cursor:pointer}
.qbtn:active{background:rgba(108,142,255,.25)}
#chat{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:10px;min-height:0}
.msg{max-width:92%;padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-break:break-word}
.msg.user{align-self:flex-end;background:linear-gradient(135deg,#3B5BDB,#6C8EFF);color:#fff}
.msg.aria{align-self:flex-start;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08)}
footer{padding:10px 12px 16px;background:rgba(4,8,15,.98);border-top:1px solid rgba(100,130,255,.15)}
.row{display:flex;gap:8px;align-items:flex-end}
#input{flex:1;min-height:48px;max-height:120px;padding:12px 14px;border-radius:14px;border:1px solid rgba(108,142,255,.3);background:rgba(255,255,255,.05);color:#E8EDFF;font-size:16px;resize:none}
.btn{min-width:48px;min-height:48px;border:none;border-radius:14px;font-size:18px;cursor:pointer;color:#fff}
#send{background:linear-gradient(135deg,#6C8EFF,#8B5CF6)}
#mic{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.15)}
#stop{display:none;width:100%;margin-top:8px;min-height:48px;background:#EF4444;border:none;border-radius:12px;color:#fff;font-weight:600}
main{display:flex;flex-direction:column;height:calc(100% - 56px)}
</style>
</head>
<body>
<header>
  <div class="dot" id="dot"></div>
  <div class="logo">ARIA</div>
  <div class="sub"><div id="conn">Déconnecté</div><div id="ip"></div></div>
</header>
<main>
  <div class="quick" id="quick"></div>
  <div id="chat"></div>
</main>
<footer>
  <div class="row">
    <textarea id="input" rows="1" placeholder="Message ARIA…"></textarea>
    <button class="btn" id="mic" type="button">🎤</button>
    <button class="btn" id="send" type="button">➤</button>
  </div>
  <button id="stop" type="button">⏹ Arrêter la génération</button>
</footer>
<script>
const WS_PORT = __WS_PORT__;
const TAILSCALE_IP = "__TAILSCALE_IP__";
const quickActions = [
  {label:"🌤 Météo", cmd:"quelle météo"},
  {label:"🕐 Heure", cmd:"quelle heure est-il"},
  {label:"🔊 Vol 50", cmd:"volume à 50"},
  {label:"🎵 Spotify", cmd:"lance spotify"},
  {label:"✈️ MSFS", cmd:"lance msfs"},
  {label:"📸 Capture", cmd:"screenshot"},
  {label:"🎮 Gaming", cmd:"mode gaming"},
  {label:"🌙 Nuit", cmd:"mode nuit"},
];
let ws=null, reconnectDelay=3000, maxDelay=30000, streaming=false, ariaBuf="";
const dot=document.getElementById("dot"), connEl=document.getElementById("conn");
const chat=document.getElementById("chat"), input=document.getElementById("input");
const stopBtn=document.getElementById("stop");
document.getElementById("ip").textContent=TAILSCALE_IP+":"+location.port;
const quickEl=document.getElementById("quick");
quickActions.forEach(a=>{
  const b=document.createElement("button");
  b.className="qbtn"; b.textContent=a.label;
  b.onclick=()=>sendAsk(a.cmd);
  quickEl.appendChild(b);
});
function setConn(ok,txt){
  dot.classList.toggle("ok",ok);
  connEl.textContent=txt||(ok?"Connecté":"Déconnecté");
}
function addMsg(text,who){
  const d=document.createElement("div");
  d.className="msg "+who; d.textContent=text;
  chat.appendChild(d); chat.scrollTop=chat.scrollHeight;
  return d;
}
function sendAsk(text){
  if(!text.trim()) return;
  addMsg(text,"user");
  wsSend({action:"ask",text,conv_mode:"ecrit"});
  streaming=true; ariaBuf=""; stopBtn.style.display="block";
}
function wsSend(obj){
  if(ws&&ws.readyState===1) ws.send(JSON.stringify(obj));
}
function connect(){
  const proto=location.protocol==="https:"?"wss:":"ws:";
  const url=proto+"//"+location.hostname+":"+WS_PORT;
  ws=new WebSocket(url);
  ws.onopen=()=>{reconnectDelay=3000; setConn(true);};
  ws.onclose=()=>{setConn(false,"Reconnexion…"); setTimeout(connect,reconnectDelay); reconnectDelay=Math.min(reconnectDelay*2,maxDelay);};
  ws.onerror=()=>setConn(false,"Erreur");
  ws.onmessage=(ev)=>{
    let m; try{m=JSON.parse(ev.data);}catch{return;}
    if(m.type==="token"){
      if(!streaming){streaming=true; ariaBuf=""; stopBtn.style.display="block";}
      ariaBuf+=m.data||"";
      let el=chat.querySelector(".msg.aria.streaming");
      if(!el){el=addMsg("","aria"); el.classList.add("streaming");}
      el.textContent=ariaBuf; chat.scrollTop=chat.scrollHeight;
    } else if(m.type==="done"){
      streaming=false; stopBtn.style.display="none";
      chat.querySelector(".msg.aria.streaming")?.classList.remove("streaming");
    } else if(m.type==="status"){
      if(m.data==="thinking") setConn(true,"Réflexion…");
      else if(m.data==="idle"){setConn(true); streaming=false; stopBtn.style.display="none";}
      else if(m.data==="listening") setConn(true,"Écoute…");
    } else if(m.type==="stt_result"&&m.data){
      input.value=m.data; sendAsk(m.data);
    } else if(m.type==="toast"&&m.data){
      addMsg("ℹ "+(m.data.message||""),"aria");
    }
  };
}
document.getElementById("send").onclick=()=>{const t=input.value.trim(); if(t){input.value=""; sendAsk(t);}};
input.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault(); document.getElementById("send").click();}});
let micOn=false;
document.getElementById("mic").onclick=()=>{
  micOn=!micOn;
  wsSend({action: micOn?"start_mic":"stop_mic"});
  document.getElementById("mic").style.background=micOn?"rgba(74,222,128,.25)":"";
};
stopBtn.onclick=()=>wsSend({action:"stop_generation"});
if("serviceWorker" in navigator){navigator.serviceWorker.register("/sw.js").catch(()=>{});}
connect();
</script>
</body>
</html>"""

_MANIFEST = json.dumps({
    "name": "ARIA Mobile",
    "short_name": "ARIA",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#04080F",
    "theme_color": "#6C8EFF",
    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}],
}, ensure_ascii=False)

_SW_JS = "self.addEventListener('fetch',e=>{e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});"


class _PWAHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        logger.debug("HTTP %s", format % args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            html = _PWA_HTML.replace("__WS_PORT__", str(_WS_PORT or 5001))
            html = html.replace("__TAILSCALE_IP__", _TAILSCALE_IP)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/manifest.json":
            self._send(200, _MANIFEST.encode("utf-8"), "application/json")
        elif path == "/sw.js":
            self._send(200, _SW_JS.encode("utf-8"), "application/javascript")
        elif path == "/icon-192.png":
            icon = _find_icon()
            if icon:
                self._send(200, icon.read_bytes(), "image/png")
            else:
                self.send_error(404)
        elif path == "/ports.json":
            ports_file = app_paths.data_dir() / "mobile_ports.json"
            if ports_file.is_file():
                self._send(200, ports_file.read_bytes(), "application/json")
            else:
                self.send_error(404)
        else:
            self.send_error(404)


def _find_icon() -> Path | None:
    for candidate in (
        app_paths.resource_path("electron", "assets", "icon.png"),
        app_paths.resource_path("assets", "icon.png"),
        app_paths.resource_path("electron", "icon.png"),
    ):
        if candidate.is_file():
            return candidate
    return None


def get_connect_info() -> dict:
    return {
        "ip": _TAILSCALE_IP,
        "http_port": _HTTP_PORT,
        "ws_port": _WS_PORT,
        "url": f"http://{_TAILSCALE_IP}:{_HTTP_PORT}" if _HTTP_PORT else None,
        "ws_url": f"ws://{_TAILSCALE_IP}:{_WS_PORT}" if _WS_PORT else None,
    }


def start_mobile_server(config: dict | None = None, **_kwargs) -> dict:
    global _HTTP_PORT, _WS_PORT, _started
    if _started:
        return {"success": True, **get_connect_info()}

    try:
        import ui_bridge as ui
        ui.set_mobile_relay(_relay_ui_event)
    except Exception:
        logger.debug("Relay mobile non enregistré", exc_info=True)

    _HTTP_PORT = _find_free_port(5000)
    _WS_PORT = _find_free_port(_HTTP_PORT + 1)
    _save_ports(_HTTP_PORT, _WS_PORT)

    httpd = ThreadingHTTPServer(("0.0.0.0", _HTTP_PORT), _PWAHandler)
    threading.Thread(
        target=httpd.serve_forever,
        daemon=True,
        name="ARIA-MobileHTTP",
    ).start()
    threading.Thread(
        target=_run_ws_server,
        args=(_WS_PORT,),
        daemon=True,
        name="ARIA-MobileWS",
    ).start()

    _started = True
    info = get_connect_info()
    logger.info("Serveur mobile PWA : %s (WS %s)", info["url"], info["ws_port"])
    return {"success": True, **info}
