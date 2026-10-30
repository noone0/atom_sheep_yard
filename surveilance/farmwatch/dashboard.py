"""Minimal web dashboard: recent events with snapshots, live counts, feed level."""
import os
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Sheep Heaven – farm watch</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f6f6f3;color:#222}
header{padding:12px 20px;background:#2d4a2d;color:#fff;display:flex;justify-content:space-between}
main{padding:20px;display:grid;gap:20px;grid-template-columns:1fr 2fr}
section{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
.urgent{background:#ffe3e3}.warning{background:#fff4d6}img{max-width:220px;border-radius:4px}
.kpi{display:flex;gap:16px;flex-wrap:wrap}.kpi div{padding:10px 14px;background:#eef3ee;border-radius:6px;min-width:120px}
.kpi b{display:block;font-size:22px}
</style></head><body>
<header><span>Sheep Heaven – farm watch</span><span id="usage"></span></header>
<main>
<section><h3>Now</h3><div class="kpi" id="kpi"></div><h3>Latest values (24h)</h3><table id="series"></table></section>
<section><h3>Events</h3><table id="events"></table></section>
</main>
<script>
async function j(u){return (await fetch(u)).json()}
function fmt(ts){return new Date(ts*1000).toLocaleString()}
async function refresh(){
  const u=await j('/api/usage');document.getElementById('usage').textContent='vision today: '+u.calls+' calls, '+u.input_tokens+' tokens';
  const ev=await j('/api/events?limit=60');
  document.getElementById('events').innerHTML='<tr><th>time</th><th>camera</th><th>module</th><th>event</th><th>photo</th></tr>'+
    ev.map(e=>`<tr class="${e.level}"><td>${fmt(e.ts)}</td><td>${e.camera}</td><td>${e.module}</td><td><b>${e.kind}</b><br>${e.message||''}</td><td>${e.snapshot?`<a href="/snapshots/${e.snapshot.split('/').pop()}" target="_blank"><img src="/snapshots/${e.snapshot.split('/').pop()}"></a>`:''}</td></tr>`).join('');
  const s=await j('/api/latest');
  document.getElementById('kpi').innerHTML=s.filter(x=>x.key.indexOf(':')<0).map(x=>`<div>${x.camera}<br>${x.key}<b>${x.value.toFixed(1)}</b><small>${fmt(x.ts)}</small></div>`).join('');
  document.getElementById('series').innerHTML='<tr><th>camera</th><th>key</th><th>last</th><th>min</th><th>max</th><th>n</th></tr>'+
    s.map(x=>`<tr><td>${x.camera}</td><td>${x.key}</td><td>${x.value.toFixed(2)}</td><td>${x.min.toFixed(2)}</td><td>${x.max.toFixed(2)}</td><td>${x.n}</td></tr>`).join('');
}
refresh();setInterval(refresh,15000);
</script></body></html>"""


def build_app(storage, vision) -> FastAPI:
    app = FastAPI(title="farmwatch")
    os.makedirs(storage.snapshot_dir, exist_ok=True)
    app.mount("/snapshots", StaticFiles(directory=storage.snapshot_dir), name="snapshots")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/events")
    def events(limit: int = 100, camera: str = None):
        return storage.recent_events(limit, camera)

    @app.get("/api/usage")
    def usage():
        return vision.usage()

    @app.get("/api/series")
    def series(camera: str, key: str, hours: float = 24):
        return storage.series(camera, key, time.time() - hours * 3600)

    @app.get("/api/latest")
    def latest(hours: float = 24):
        out = []
        since = time.time() - hours * 3600
        for k in storage.keys():
            s = storage.series(k["camera"], k["key"], since)
            if s:
                vals = [p["value"] for p in s]
                out.append({"camera": k["camera"], "key": k["key"], "ts": s[-1]["ts"], "value": vals[-1],
                            "min": min(vals), "max": max(vals), "n": len(vals)})
        return sorted(out, key=lambda x: (x["camera"], x["key"]))

    return app


def serve(storage, vision, port: int = 8080) -> None:
    import uvicorn
    uvicorn.run(build_app(storage, vision), host="0.0.0.0", port=port, log_level="warning")
