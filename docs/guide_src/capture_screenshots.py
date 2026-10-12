"""
Captures real screenshots of the running AnyDoc UI for the visual guide.
Starts uvicorn + Streamlit with an OFFLINE dummy LLM key (no Groq calls succeed),
ingests the synthetic samples, drives headless Chrome over the DevTools protocol,
and shuts everything down. Output: docs/guide_assets/ui_*.png

    python docs/guide_src/capture_screenshots.py
"""
import base64, json, os, shutil, signal, subprocess, sys, tempfile, time
import requests, websocket
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "docs", "guide_assets")
PY = sys.executable
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
API, UI = "http://127.0.0.1:8020", "http://127.0.0.1:8521"
run = tempfile.mkdtemp()
env = dict(os.environ, PYTHONPATH=ROOT, GROQ_API_KEY="dummy-offline-key", API_URL=API)
NEW = subprocess.CREATE_NEW_PROCESS_GROUP
procs = []

def wait(url, ok=lambda r: r.status_code == 200, t=180):
    end = time.time() + t
    while time.time() < end:
        try:
            if ok(requests.get(url, timeout=2)): return
        except requests.RequestException: pass
        time.sleep(1)
    raise SystemExit(f"timeout waiting for {url}")

try:
    procs.append(subprocess.Popen([PY, "-m", "uvicorn", "src.api.main:app", "--port", "8020"], cwd=run, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NEW))
    wait(f"{API}/stats")
    for f in ["acme_handbook.pdf", "travel_policy.docx", "release_notes.txt", "inventory.csv"]:
        with open(os.path.join(ROOT, "samples", f), "rb") as fh:
            requests.post(f"{API}/ingest/file", files={"file": (f, fh)}, timeout=120)
    procs.append(subprocess.Popen([PY, "-m", "streamlit", "run", os.path.join(ROOT, "app.py"), "--server.port", "8521",
                                   "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=run, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NEW))
    wait(f"{UI}/_stcore/health", ok=lambda r: r.text == "ok")
    profile = tempfile.mkdtemp()
    procs.append(subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", "--remote-allow-origins=http://127.0.0.1:9333", f"--user-data-dir={profile}",
                                   "--window-size=1440,1700", "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait("http://127.0.0.1:9333/json")
    page = next(t for t in requests.get("http://127.0.0.1:9333/json").json() if t["type"] == "page")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60, origin="http://127.0.0.1:9333")
    msg_id = [0]
    def cdp(method, **params):
        msg_id[0] += 1; ws.send(json.dumps({"id": msg_id[0], "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == msg_id[0]: return m.get("result", {})
    js = lambda expr: cdp("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True).get("result", {}).get("value")
    def click_text(selector, text):
        return js(f"""(() => {{ const el=[...document.querySelectorAll({json.dumps(selector)})].find(e=>e.innerText.trim().includes({json.dumps(text)}));
                     if(!el) return false; el.scrollIntoView({{block:'center'}}); el.click(); return true; }})()""")
    def open_tab(name):
        ok = click_text('[role="tab"], [data-baseweb="tab"]', name); time.sleep(2)
        selected = js("[...document.querySelectorAll('[role=tab]')].filter(t=>t.getAttribute('aria-selected')==='true').map(t=>t.innerText.trim()).join()")
        if not ok or name not in (selected or ""):
            raise SystemExit(f"could not open tab {name!r} (selected={selected!r})")
    def shot(name, height=1700):
        time.sleep(1.5)
        data = cdp("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": 1440, "height": height, "scale": 1})["data"]
        open(os.path.join(ASSETS, f"ui_{name}.png"), "wb").write(base64.b64decode(data)); print("saved", name)
    def scroll_main(y):
        js(f"(() => {{ const m=document.querySelector('[data-testid=stMain]')||document.querySelector('section.main'); if(m) m.scrollTop={y}; window.scrollTo(0,{y}); }})()")

    cdp("Page.enable"); cdp("DOM.enable"); cdp("Page.navigate", url=UI); time.sleep(8)
    shot("overview", 900)

    open_tab("Ingestion"); time.sleep(2)
    doc = cdp("DOM.getDocument", depth=-1, pierce=True)
    node = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector='input[type="file"]')["nodeId"]
    cdp("DOM.setFileInputFiles", nodeId=node, files=[os.path.join(ROOT, "samples", "invoice.pdf")]); time.sleep(3)
    click_text("button", "Ingest File"); time.sleep(5)
    shot("ingestion_rejected", 820)

    open_tab("Chat"); time.sleep(2)
    js("document.querySelector('[data-testid=stChatInputTextArea]').focus()")
    cdp("Input.insertText", text="What does error code ZX-4471 mean?")
    for t in ("keyDown", "keyUp"):
        cdp("Input.dispatchKeyEvent", type=t, key="Enter", code="Enter", windowsVirtualKeyCode=13, nativeVirtualKeyCode=13, **({"text": "\r"} if t == "keyDown" else {}))
    time.sleep(12)
    click_text("summary", "acme_handbook.pdf"); click_text("summary", "Retrieval trace"); time.sleep(2)
    scroll_main(0); shot("chat", 1700)

    open_tab("Chunking Lab"); time.sleep(2)
    click_text("button", "Evaluate Strategies"); time.sleep(4); scroll_main(0)
    shot("chunking_lab", 1150)

    open_tab("Evaluation"); time.sleep(4); scroll_main(0)
    shot("evaluation", 1250)
    ws.close()
finally:
    for p in reversed(procs):
        try:
            p.send_signal(signal.CTRL_BREAK_EVENT) if p.args[0] == PY else p.terminate()
            p.wait(20)
        except Exception:
            p.kill()
    shutil.rmtree(run, ignore_errors=True)
