"""Renderiza os slides HTML em PNG 1920x1080 com o Edge headless.  uso: python render.py <pasta_html> <pasta_png>"""
import base64, glob, json, os, shutil, subprocess, sys, time
import requests, websocket

HDIR, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
PROF = os.path.join(os.path.dirname(os.path.abspath(HDIR)), "edge-prof-render")
shutil.rmtree(PROF, ignore_errors=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9355
edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={PROF}", "--hide-scrollbars",
                         "--no-first-run", "--allow-file-access-from-files", "--window-size=1920,1080", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            page = [t for t in requests.get(f"http://127.0.0.1:{PORT}/json", timeout=1).json() if t["type"] == "page"][0]; break
        except Exception: time.sleep(0.3)
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60)
    _id = [0]
    def cdp(method, **params):
        _id[0] += 1; ws.send(json.dumps({"id": _id[0], "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == _id[0]:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    cdp("Page.enable")
    cdp("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
    for f in sorted(glob.glob(os.path.join(HDIR, "slide*.html"))):
        cdp("Page.navigate", url="file:///" + f.replace(os.sep, "/")); time.sleep(0.9)
        cdp("Runtime.evaluate", expression="Promise.all([...document.images].map(i=>i.complete?1:new Promise(r=>{i.onload=i.onerror=r})))", awaitPromise=True)
        data = cdp("Page.captureScreenshot", format="png")["data"]
        name = os.path.splitext(os.path.basename(f))[0] + ".png"
        open(os.path.join(OUT, name), "wb").write(base64.b64decode(data)); print("ok", name, flush=True)
    ws.close()
finally:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*" + PROF + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1); shutil.rmtree(PROF, ignore_errors=True)
