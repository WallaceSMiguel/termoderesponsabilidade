"""Sobe o sistema com dados FICTÍCIOS e captura as telas via Edge headless (CDP).
uso: python capturas.py <pasta_saida>
"""
import base64, json, os, shutil, subprocess, sys, time
import requests, websocket

APP = r"C:\Users\Wallace\Documents\Projeto_App\termo_contrato"
SCR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1]
DEMO = os.path.join(SCR, "demo-data"); PROF = os.path.join(SCR, "edge-prof")
for d in (DEMO, PROF): shutil.rmtree(d, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
PORT = 5091
BASE = f"http://localhost:{PORT}"
INI, PW = "Inicial#2026x", "DemoGuia#2026"

env = dict(os.environ, DATA_DIR=DEMO, ADMIN_PASSWORD=INI, PORT=str(PORT))
srv = subprocess.Popen([sys.executable, "app.py"], cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
edge = None
try:
    for _ in range(50):
        try: requests.get(BASE + "/healthz", timeout=1); break
        except Exception: time.sleep(0.3)

    s = requests.Session()
    def j(m, p, b=None):
        r = s.request(m, BASE + p, json=b if b is not None else ({} if m != "GET" else None)); r.raise_for_status(); return r.json()
    j("POST", "/api/login", {"login": "admin", "senha": INI})
    j("POST", "/api/me/senha", {"atual": INI, "nova": PW})
    s.put(BASE + "/api/usuarios/1", json={"nome": "Wallace Miguel"})
    for nome, login, perfil in [("Carla Mendes", "carla", "usuario"), ("Rafael Souza", "rafael", "usuario"), ("Juliana Costa", "juliana", "admin")]:
        j("POST", "/api/usuarios", {"nome": nome, "login": login, "senha": "Provisoria#123", "perfil": perfil})
    j("PUT", "/api/smtp", {"host": "smtp.office365.com", "porta": 587, "seguranca": "starttls", "usuario": "rh@valorizacao.com", "senha": "",
                           "remetente": "rh@valorizacao.com", "nome_remetente": "Valorização Assessoria Contábil", "copia": ""})
    EMP = j("GET", "/api/empresa")
    snap = {k: EMP[k] for k in ("empresa", "cnpj", "empEndereco", "empContato")}
    I = lambda item, serie, estado="Novo", obs="": {"item": item, "serie": serie, "qtd": 1, "estado": estado, "obs": obs}
    A = lambda sid, sistema, usuario, detalhe="": {"sid": sid, "sistema": sistema, "usuario": usuario, "detalhe": detalhe}

    def termo(tipo, unidade, nome, cpf, cargo, setor, itens=(), acessos=()):
        d = dict(tipo=tipo, unidade=unidade, nome=nome, cpf=cpf, rg="20.345.678-1", endereco="Rua das Laranjeiras, 120 - Rio de Janeiro - RJ",
                 email=nome.split()[0].lower().replace("í", "i").replace("á", "a") + "@exemplo.com", cargo=cargo, setor=setor,
                 local="Rio de Janeiro - RJ", data="2026-11-23", recNome="Wallace Miguel", recCargo="Gestão de Projetos", obs="",
                 itens=list(itens), acessos=list(acessos), empresaSnapshot=snap)
        return j("POST", "/api/termos", {"dados": d})["id"]

    ids = {}
    ids["t1"] = termo("equipamentos", "Barra", "Thiago Santos", "258.369.147-55", "Estagiário", "Contabilidade", [I("Notebook Positivo", "PT 0099", "Usado (funcionando)")])
    ids["t2"] = termo("acessos", "Nova América", "Aline Rocha", "963.852.741-44", "Analista Fiscal", "Fiscal", acessos=[A("rede", "Computador / Rede - VPN", "aline.rocha"), A("email", "E-mail corporativo", "aline.rocha@valorizacao.com")])
    ids["t3"] = termo("equipamentos", "Duque de Caxias", "Marcos Vieira", "147.258.369-33", "Auxiliar Administrativo", "Administrativo", [I("Celular Samsung A15", "IMEI 3541", "Novo", "Com capa e película")])
    ids["t4"] = termo("completo", "Barra", "Fernanda Oliveira", "321.654.987-00", "Analista Contábil", "Contabilidade",
                      [I("Notebook Dell Latitude 5440", "PT 0212", "Novo", "Com carregador"), I("Monitor LG 24\"", "PT 0187", "Bom"), I("Headset Logitech H390", "S/N 2231")],
                      [A("rede", "Computador / Rede - VPN", "fernanda.oliveira", "PC-CONT-04"), A("email", "E-mail corporativo", "fernanda.oliveira@valorizacao.com"),
                       A("dominio", "Domínio Web", "FERNANDA", "Escrita Fiscal"), A("linkus", "Telefonia Linkus", "", "Ramal 2031")])
    ids["t5"] = termo("acessos", "Duque de Caxias", "Bruno Almeida", "456.789.123-11", "Assistente Fiscal", "Fiscal",
                      acessos=[A("rede", "Computador / Rede - VPN", "bruno.almeida"), A("onvio", "Onvio", "bruno.almeida"), A("pasta", "Pasta mapeada", "", "\\\\servidor\\Fiscal (Z:)")])
    ids["t6"] = termo("equipamentos", "Nova América", "Patrícia Lima", "789.123.456-22", "Analista de DP", "Departamento Pessoal",
                      [I("Notebook Dell Vostro 3520", "PT 0195", "Usado (funcionando)", "Com carregador"), I("Teclado e Mouse MK235", "sem PT", "Bom")])
    ids["t7"] = termo("completo", "Barra", "Regiane Marques", "741.852.963-00", "Analista", "Departamento Pessoal",
                      [I("Notebook Lenovo ThinkPad E14", "PT 0220", "Novo")], [A("rede", "Computador / Rede - VPN", "regiane.marques"), A("email", "E-mail corporativo", "regiane.marques@valorizacao.com"), A("onvio", "Onvio", "regiane.marques")])
    s.put(BASE + f"/api/termos/{ids['t1']}", json={"status": "devolvido", "observacao": "Fim do estágio – itens conferidos"})
    s.put(BASE + f"/api/termos/{ids['t2']}", json={"status": "devolvido", "observacao": "Acessos revogados"})
    s.put(BASE + f"/api/termos/{ids['t4']}", json={"dados": dict(j("GET", f"/api/termos/{ids['t4']}")["dados"])})
    cookie = s.cookies.get("session")

    # ---------------- Edge headless
    EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    edge = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=9344", f"--user-data-dir={PROF}", "--hide-scrollbars",
                             "--no-first-run", "--window-size=1600,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            tabs = requests.get("http://127.0.0.1:9344/json", timeout=1).json(); page = [t for t in tabs if t["type"] == "page"][0]; break
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
    W, H = 1600, 900
    def viewport(dsf=1.5): cdp("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=dsf, mobile=False)
    viewport()
    def go(url, wait=1.8): cdp("Page.navigate", url=url); time.sleep(wait)
    def js(code, wait=0.6):
        r = cdp("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True); time.sleep(wait); return r.get("result", {}).get("value")
    def shot(name, clip=None):
        p = {"format": "png"}
        if clip: p.update(clip=dict(clip, scale=1), captureBeyondViewport=True)
        data = cdp("Page.captureScreenshot", **p)["data"]
        open(os.path.join(OUT, name + ".png"), "wb").write(base64.b64decode(data)); print("ok", name, flush=True)
    def shot_el(name, sel, pad=10):
        b = js(f"(()=>{{const r=document.querySelector({json.dumps(sel)}).getBoundingClientRect(); return {{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height}}}})()", 0.2)
        shot(name, {"x": max(0, b["x"] - pad), "y": max(0, b["y"] - pad), "width": b["width"] + 2 * pad, "height": b["height"] + 2 * pad})
    def form_scroll(sel):
        js(f"(()=>{{const f=document.querySelector('.form'); const e=document.querySelector({json.dumps(sel)}); f.scrollTop = e.getBoundingClientRect().top - f.getBoundingClientRect().top + f.scrollTop - 12; }})()", 0.5)

    cdp("Page.enable"); cdp("Network.enable")
    go(BASE + "/#/login", 2.5); shot("01-login")
    cdp("Network.setCookie", name="session", value=cookie, url=BASE)
    go(BASE + "/?r=1#/termos", 2.2); shot("02-lista")
    js("document.querySelectorAll('.unit-tab')[1].click()", 1.2); shot("03-lista-barra")
    js("sessionStorage.removeItem('filtro-unidade')", 0.1)

    # ---- novo termo: equipamentos
    draft = {"tipo": "equipamentos", "unidade": "Barra", "nome": "Ricardo Nunes", "cpf": "741.852.963-00", "rg": "11.222.333-4",
             "endereco": "Av. Brasil, 500 - Rio de Janeiro - RJ", "email": "ricardo.nunes@exemplo.com", "cargo": "Analista Contábil", "setor": "Contabilidade",
             "local": "Rio de Janeiro - RJ", "data": "2026-11-23", "recNome": "Wallace Miguel", "recCargo": "Gestão de Projetos", "obs": "",
             "itens": [I("Notebook Dell Latitude 5440", "PT 0230", "Novo", "Com carregador"), I("Mouse sem fio Logitech M170", "sem PT", "Novo")], "acessos": []}
    js(f"localStorage.setItem('termo-rascunho', {json.dumps(json.dumps(draft))})", 0.1)
    go(BASE + "/?r=2#/novo", 2.2); shot("04-novo-equipamentos")
    viewport(2); shot_el("05-tipo", "#tipoPick", 6); shot_el("06-unidade", "#unidPick", 6); viewport()
    form_scroll("#itemsForm"); shot("07-itens")

    # ---- novo termo: acessos
    js("document.querySelector('.tipo-opt[data-tipo=acessos]').click()", 0.3)
    js("['rede','email','onvio','dominio','linkus','pasta'].forEach(s=>document.querySelector(`.sys[data-sid=${s}]`).click())", 0.3)
    js("document.querySelector('#btnLogins').click()", 0.3)
    js("document.querySelector('#btnSenhas').click()", 0.3)
    js("(()=>{const d=[...document.querySelectorAll('#accForm [data-f=detalhe]')]; const set=(i,v)=>{d[i].value=v; d[i].dispatchEvent(new Event('input'));}; set(0,'PC-CONT-07'); set(3,'Folha, Escrita Fiscal'); set(4,'Ramal 2045'); set(5,'\\\\\\\\servidor\\\\Contabil (Z:)');})()", 0.4)
    form_scroll("#sysGrid"); time.sleep(2.6); shot("08-acessos")
    # elemento dentro da coluna rolável: print da área visível + recorte (sem captureBeyondViewport)
    viewport(2); time.sleep(0.4); form_scroll("#sysGrid")
    b = js("(()=>{const r=document.querySelector('#sysGrid').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}})()", 0.2)
    raw = base64.b64decode(cdp("Page.captureScreenshot", format="png")["data"])
    from PIL import Image; import io
    im = Image.open(io.BytesIO(raw)); k = 2; pad = 6
    im.crop((int((b["x"]-pad)*k), int((b["y"]-pad)*k), int((b["x"]+b["w"]+pad)*k), int((b["y"]+b["h"]+pad)*k))).save(os.path.join(OUT, "09-sistemas.png"))
    print("ok 09-sistemas", flush=True); viewport()
    js("document.querySelector('.preview').scrollTop=0; window.scrollTo(0,0)", 0.3)
    viewport(2); shot_el("10-doc-acessos", "#doc", 0); viewport()

    # ---- termo salvo (completo) + ações
    go(BASE + f"/?r=3#/termo/{ids['t4']}", 2.2); shot("11-termo-completo")
    js("document.querySelector('.acc').scrollIntoView({block:'center'})", 0.6); shot("12-termo-completo-acessos")
    js("window.scrollTo(0,0)", 0.3)
    js("document.querySelector('#aEmail').click()", 0.8); shot("13-enviar-email")
    js("document.querySelector('#dlg').close()", 0.3)
    js("document.querySelector('#aDev').click()", 0.8); shot("14-devolucao")
    js("document.querySelector('#dlg').close()", 0.3)
    go(BASE + f"/?r=4#/termo/{ids['t1']}", 2.0); shot("15-historico")

    # ---- administração
    go(BASE + "/?r=5#/usuarios", 2.0); shot("16-usuarios")
    js("document.querySelector('#uNovo').click()", 0.8)
    js("(()=>{const f=document.querySelector('#dlgForm'); f.nome.value='Lucas Pereira'; f.login.value='lucas'; f.senha.value='Provisoria#456';})()", 0.4); shot("17-novo-usuario")
    js("document.querySelector('#dlg').close()", 0.2)
    go(BASE + "/?r=6#/empresa", 2.2); shot("18-empresa")
    js("window.scrollTo(0, document.body.scrollHeight)", 0.8); shot("19-config-email")
    ws.close()
finally:
    if edge:  # encerra o Edge headless (o lançador sai cedo; os filhos são achados pela pasta de perfil)
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*" + PROF + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv.kill()
    time.sleep(1.5)
    shutil.rmtree(DEMO, ignore_errors=True); shutil.rmtree(PROF, ignore_errors=True)
