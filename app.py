"""
Sistema de Termos de Responsabilidade - Valorização Assessoria Contábil
Flask + SQLite. Login, cadastro de usuários e armazenamento dos termos.
"""
import base64
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from functools import wraps

import tempfile
from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

if getattr(sys, "frozen", False):
    # Executável (PyInstaller): arquivos do site vêm do pacote, banco fica ao lado do .exe
    BASE_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(APP_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "termos.db")
os.makedirs(DATA_DIR, exist_ok=True)


def _secret_key():
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(DATA_DIR, ".secret_key")
    try:
        with open(path, "x") as f:  # "x": só cria se não existir (seguro com vários workers)
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 10,  # 10 horas
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,  # inclui o PDF enviado por e-mail
)

EMPRESA_PADRAO = {
    "empresa": "VALORIZAÇÃO ASSESSORIA CONTÁBIL LTDA",
    "cnpj": "37.864.788/0001-94",
    "empEndereco": "Avenida Pastor Martin Luther King Jr., 126, Bl 9, sala 1315, torre 1, "
    "Del Castilho, CEP: 20.765-000, Rio de Janeiro - RJ",
    "empContato": "",
    "local": "Rio de Janeiro - RJ",
    "logo": None,
    "unidades": ["Barra", "Nova América", "Duque de Caxias"],
    "dominioEmail": "valorizacao.com",  # usado para sugerir o e-mail corporativo (nome.sobrenome@...)
}
TIPOS = ("equipamentos", "acessos", "completo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  login TEXT NOT NULL UNIQUE COLLATE NOCASE,
  senha_hash TEXT NOT NULL,
  perfil TEXT NOT NULL DEFAULT 'usuario' CHECK (perfil IN ('admin','usuario')),
  ativo INTEGER NOT NULL DEFAULT 1,
  trocar_senha INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT NOT NULL,
  ultimo_acesso TEXT
);
CREATE TABLE IF NOT EXISTS termos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  numero TEXT NOT NULL UNIQUE,
  colaborador TEXT NOT NULL DEFAULT '',
  cpf TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','devolvido','cancelado')),
  dados TEXT NOT NULL,
  criado_por INTEGER REFERENCES users(id),
  criado_em TEXT NOT NULL,
  atualizado_por INTEGER REFERENCES users(id),
  atualizado_em TEXT NOT NULL,
  devolvido_em TEXT
);
CREATE TABLE IF NOT EXISTS historico (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  termo_id INTEGER NOT NULL REFERENCES termos(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id),
  acao TEXT NOT NULL,
  detalhe TEXT,
  quando TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config (
  chave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_termos_colab ON termos(colaborador);
CREATE INDEX IF NOT EXISTS idx_hist_termo ON historico(termo_id);
"""


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def _close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    # WAL é mais rápido, mas não é seguro em discos de rede (ex.: PythonAnywhere) -> SQLITE_JOURNAL=DELETE
    modo = os.environ.get("SQLITE_JOURNAL", "WAL").upper()
    conn.execute(f"PRAGMA journal_mode={'DELETE' if modo == 'DELETE' else 'WAL'}")
    conn.executescript(SCHEMA)
    # migração: colunas novas em bancos já existentes
    cols = {c[1] for c in conn.execute("PRAGMA table_info(termos)")}
    if "unidade" not in cols:
        conn.execute("ALTER TABLE termos ADD COLUMN unidade TEXT NOT NULL DEFAULT ''")
    if "tipo" not in cols:
        conn.execute("ALTER TABLE termos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'equipamentos'")
    conn.execute("BEGIN IMMEDIATE")  # trava para que só um worker crie os dados iniciais
    conn.execute("INSERT OR IGNORE INTO config VALUES ('empresa', ?)", (json.dumps(EMPRESA_PADRAO),))
    if not conn.execute("SELECT 1 FROM users").fetchone():
        login = os.environ.get("ADMIN_LOGIN", "admin")
        senha = os.environ.get("ADMIN_PASSWORD")
        gerada = not senha
        if gerada:
            senha = secrets.token_urlsafe(9)
        conn.execute(
            "INSERT INTO users (nome, login, senha_hash, perfil, trocar_senha, criado_em) VALUES (?,?,?,?,?,?)",
            ("Administrador", login, generate_password_hash(senha), "admin", 1, agora()),
        )
        msg = f"Usuário administrador criado: login '{login}'"
        if gerada:
            # Gravado em arquivo local (não no log) para primeiro acesso; apague após usar.
            path = os.path.join(DATA_DIR, "senha-inicial-admin.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"login: {login}\nsenha: {senha}\n(troque no primeiro acesso e apague este arquivo)\n")
            msg += f" - senha inicial gravada em {path}"
        print(msg, flush=True)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- auth helpers

def usuario_atual():
    uid = session.get("uid")
    if not uid:
        return None
    u = db().execute("SELECT * FROM users WHERE id=? AND ativo=1", (uid,)).fetchone()
    return u


def login_required(admin=False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = usuario_atual()
            if not u:
                return jsonify(erro="Não autenticado"), 401
            if admin and u["perfil"] != "admin":
                return jsonify(erro="Acesso restrito ao administrador"), 403
            # bloqueia uso do sistema até trocar senha provisória
            if u["trocar_senha"] and request.endpoint not in ("api_me", "api_trocar_senha", "api_logout"):
                return jsonify(erro="Troque sua senha provisória para continuar", trocar_senha=True), 403
            g.user = u
            return fn(*a, **kw)
        return wrapper
    return deco


@app.before_request
def _csrf_guard():
    # Requisições que alteram dados precisam ser JSON (navegadores não enviam JSON cross-site sem CORS).
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        if not request.is_json:
            return jsonify(erro="Requisição inválida"), 400


def user_publico(u):
    return {
        "id": u["id"], "nome": u["nome"], "login": u["login"], "perfil": u["perfil"],
        "ativo": bool(u["ativo"]), "trocar_senha": bool(u["trocar_senha"]),
        "criado_em": u["criado_em"], "ultimo_acesso": u["ultimo_acesso"],
    }


def validar_senha(s):
    if not s or len(s) < 8:
        return "A senha deve ter pelo menos 8 caracteres"
    return None


_tentativas = {}  # ip -> [timestamps]


def _bloqueado(ip):
    t = [x for x in _tentativas.get(ip, []) if time.time() - x < 300]
    _tentativas[ip] = t
    return len(t) >= 8


# ---------------------------------------------------------------- rotas: auth

@app.post("/api/login")
def api_login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if _bloqueado(ip):
        return jsonify(erro="Muitas tentativas. Aguarde alguns minutos."), 429
    d = request.get_json(silent=True) or {}
    u = db().execute("SELECT * FROM users WHERE login=?", ((d.get("login") or "").strip(),)).fetchone()
    if not u or not u["ativo"] or not check_password_hash(u["senha_hash"], d.get("senha") or ""):
        _tentativas.setdefault(ip, []).append(time.time())
        return jsonify(erro="Login ou senha inválidos"), 401
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    db().execute("UPDATE users SET ultimo_acesso=? WHERE id=?", (agora(), u["id"]))
    db().commit()
    return jsonify(user=user_publico(u))


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def api_me():
    u = usuario_atual()
    if not u:
        return jsonify(user=None)
    return jsonify(user=user_publico(u))


@app.post("/api/me/senha")
def api_trocar_senha():
    u = usuario_atual()
    if not u:
        return jsonify(erro="Não autenticado"), 401
    d = request.get_json() or {}
    if not check_password_hash(u["senha_hash"], d.get("atual") or ""):
        return jsonify(erro="Senha atual incorreta"), 400
    err = validar_senha(d.get("nova"))
    if err:
        return jsonify(erro=err), 400
    db().execute("UPDATE users SET senha_hash=?, trocar_senha=0 WHERE id=?",
                 (generate_password_hash(d["nova"]), u["id"]))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- rotas: usuários (admin)

@app.get("/api/usuarios")
@login_required(admin=True)
def api_usuarios():
    rows = db().execute("SELECT * FROM users ORDER BY nome").fetchall()
    return jsonify(usuarios=[user_publico(r) for r in rows])


@app.post("/api/usuarios")
@login_required(admin=True)
def api_criar_usuario():
    d = request.get_json() or {}
    nome, login = (d.get("nome") or "").strip(), (d.get("login") or "").strip()
    perfil = d.get("perfil") if d.get("perfil") in ("admin", "usuario") else "usuario"
    if not nome or not login:
        return jsonify(erro="Informe nome e login"), 400
    err = validar_senha(d.get("senha"))
    if err:
        return jsonify(erro=err), 400
    try:
        db().execute(
            "INSERT INTO users (nome, login, senha_hash, perfil, trocar_senha, criado_em) VALUES (?,?,?,?,1,?)",
            (nome, login, generate_password_hash(d["senha"]), perfil, agora()),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(erro="Já existe um usuário com esse login"), 400
    return jsonify(ok=True), 201


@app.put("/api/usuarios/<int:uid>")
@login_required(admin=True)
def api_editar_usuario(uid):
    d = request.get_json() or {}
    u = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return jsonify(erro="Usuário não encontrado"), 404
    nome = (d.get("nome") or u["nome"]).strip()
    perfil = d.get("perfil") if d.get("perfil") in ("admin", "usuario") else u["perfil"]
    ativo = int(bool(d.get("ativo", u["ativo"])))
    if uid == g.user["id"] and (perfil != "admin" or not ativo):
        return jsonify(erro="Você não pode remover seu próprio acesso de administrador"), 400
    db().execute("UPDATE users SET nome=?, perfil=?, ativo=? WHERE id=?", (nome, perfil, ativo, uid))
    if d.get("senha"):
        err = validar_senha(d["senha"])
        if err:
            return jsonify(erro=err), 400
        db().execute("UPDATE users SET senha_hash=?, trocar_senha=1 WHERE id=?",
                     (generate_password_hash(d["senha"]), uid))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- rotas: empresa

@app.get("/api/empresa")
@login_required()
def api_empresa():
    r = db().execute("SELECT valor FROM config WHERE chave='empresa'").fetchone()
    return jsonify(dict(EMPRESA_PADRAO, **json.loads(r["valor"])))


@app.put("/api/empresa")
@login_required(admin=True)
def api_salvar_empresa():
    d = request.get_json() or {}
    dados = {k: d.get(k, EMPRESA_PADRAO[k]) for k in EMPRESA_PADRAO}
    dados["unidades"] = [u.strip() for u in (dados.get("unidades") or []) if isinstance(u, str) and u.strip()]
    db().execute("UPDATE config SET valor=? WHERE chave='empresa'", (json.dumps(dados),))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- rotas: termos

def registrar(termo_id, acao, detalhe=""):
    db().execute("INSERT INTO historico (termo_id, user_id, acao, detalhe, quando) VALUES (?,?,?,?,?)",
                 (termo_id, g.user["id"], acao, detalhe, agora()))


def proximo_numero():
    ano = datetime.now().year
    r = db().execute("SELECT numero FROM termos WHERE numero LIKE ? ORDER BY id DESC LIMIT 1",
                     (f"TR-{ano}-%",)).fetchone()
    seq = int(r["numero"].split("-")[-1]) + 1 if r else 1
    return f"TR-{ano}-{seq:04d}"


def termo_json(r, completo=False):
    t = {
        "id": r["id"], "numero": r["numero"], "colaborador": r["colaborador"], "cpf": r["cpf"],
        "status": r["status"], "criado_em": r["criado_em"], "atualizado_em": r["atualizado_em"],
        "devolvido_em": r["devolvido_em"], "criado_por_nome": r["criado_por_nome"],
        "unidade": r["unidade"], "tipo": r["tipo"],
    }
    dados = json.loads(r["dados"])
    t["qtd_itens"] = len([i for i in dados.get("itens", []) if i.get("item")]) if r["tipo"] != "acessos" else 0
    t["qtd_acessos"] = len([a for a in dados.get("acessos", []) if a.get("sistema")]) if r["tipo"] != "equipamentos" else 0
    if completo:
        t["dados"] = dados
    return t


SELECT_TERMO = """SELECT t.*, u.nome AS criado_por_nome FROM termos t
                  LEFT JOIN users u ON u.id = t.criado_por"""


@app.get("/api/termos")
@login_required()
def api_termos():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    sql, args = SELECT_TERMO + " WHERE 1=1", []
    if q:
        like = f"%{q}%"
        sql += " AND (t.colaborador LIKE ? OR t.cpf LIKE ? OR t.numero LIKE ? OR t.dados LIKE ?)"
        args += [like, like, like, like]
    if status in ("ativo", "devolvido", "cancelado"):
        sql += " AND t.status=?"
        args.append(status)
    unidade = request.args.get("unidade") or ""
    if unidade:
        sql += " AND t.unidade=?"
        args.append(unidade)
    tipo = request.args.get("tipo") or ""
    if tipo in TIPOS:
        sql += " AND t.tipo=?"
        args.append(tipo)
    sql += " ORDER BY t.id DESC LIMIT 500"
    rows = db().execute(sql, args).fetchall()
    # contagem por status respeita o filtro de unidade (painel da unidade)
    csql, cargs = "SELECT status, COUNT(*) n FROM termos", []
    if unidade:
        csql += " WHERE unidade=?"
        cargs.append(unidade)
    cont = {r["status"]: r["n"] for r in db().execute(csql + " GROUP BY status", cargs)}
    por_unidade = {r["unidade"] or "": r["n"] for r in
                   db().execute("SELECT unidade, COUNT(*) n FROM termos WHERE status='ativo' GROUP BY unidade")}
    return jsonify(termos=[termo_json(r) for r in rows], contagem=cont, por_unidade=por_unidade)


@app.get("/api/termos/<int:tid>")
@login_required()
def api_termo(tid):
    r = db().execute(SELECT_TERMO + " WHERE t.id=?", (tid,)).fetchone()
    if not r:
        return jsonify(erro="Termo não encontrado"), 404
    hist = db().execute("""SELECT h.acao, h.detalhe, h.quando, u.nome FROM historico h
                           LEFT JOIN users u ON u.id=h.user_id WHERE h.termo_id=? ORDER BY h.id DESC""",
                        (tid,)).fetchall()
    t = termo_json(r, completo=True)
    t["historico"] = [dict(h) for h in hist]
    return jsonify(t)


def _limpar_dados(d):
    d = dict(d or {})
    d.pop("logo", None)  # logo vem da configuração, não é duplicada em cada termo
    if d.get("tipo") not in TIPOS:
        d["tipo"] = "completo" if d.get("incluirAcessos") else "equipamentos"
    # Senhas provisórias NUNCA são gravadas no banco: só aparecem na impressão feita na hora.
    d["acessos"] = [{k: v for k, v in (a or {}).items() if k != "senha"} for a in (d.get("acessos") or [])]
    return d


@app.post("/api/termos")
@login_required()
def api_criar_termo():
    d = _limpar_dados((request.get_json() or {}).get("dados"))
    numero = proximo_numero()
    cur = db().execute(
        """INSERT INTO termos (numero, colaborador, cpf, unidade, tipo, dados, criado_por, criado_em, atualizado_por, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (numero, d.get("nome", ""), d.get("cpf", ""), d.get("unidade", ""), d["tipo"], json.dumps(d, ensure_ascii=False),
         g.user["id"], agora(), g.user["id"], agora()),
    )
    registrar(cur.lastrowid, "criado", numero)
    db().commit()
    return jsonify(id=cur.lastrowid, numero=numero), 201


@app.put("/api/termos/<int:tid>")
@login_required()
def api_editar_termo(tid):
    r = db().execute("SELECT * FROM termos WHERE id=?", (tid,)).fetchone()
    if not r:
        return jsonify(erro="Termo não encontrado"), 404
    body = request.get_json() or {}
    if "dados" in body:
        d = _limpar_dados(body["dados"])
        db().execute("""UPDATE termos SET colaborador=?, cpf=?, unidade=?, tipo=?, dados=?, atualizado_por=?, atualizado_em=?
                        WHERE id=?""",
                     (d.get("nome", ""), d.get("cpf", ""), d.get("unidade", ""), d["tipo"], json.dumps(d, ensure_ascii=False),
                      g.user["id"], agora(), tid))
        registrar(tid, "editado")
    if body.get("status") in ("ativo", "devolvido", "cancelado") and body["status"] != r["status"]:
        st = body["status"]
        db().execute("UPDATE termos SET status=?, devolvido_em=?, atualizado_por=?, atualizado_em=? WHERE id=?",
                     (st, agora() if st == "devolvido" else None, g.user["id"], agora(), tid))
        registrar(tid, f"status: {st}", (body.get("observacao") or "").strip())
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/termos/<int:tid>")
@login_required(admin=True)
def api_excluir_termo(tid):
    db().execute("DELETE FROM termos WHERE id=?", (tid,))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- e-mail (SMTP)

SMTP_PADRAO = {"host": "", "porta": 587, "seguranca": "starttls", "usuario": "", "senha": "",
               "remetente": "", "nome_remetente": "", "copia": ""}
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def smtp_config():
    r = db().execute("SELECT valor FROM config WHERE chave='smtp'").fetchone()
    cfg = dict(SMTP_PADRAO, **(json.loads(r["valor"]) if r else {}))
    # variáveis de ambiente têm prioridade (útil na nuvem, sem guardar senha no banco)
    for k, env in (("host", "SMTP_HOST"), ("porta", "SMTP_PORT"), ("seguranca", "SMTP_SECURITY"),
                   ("usuario", "SMTP_USER"), ("senha", "SMTP_PASSWORD"), ("remetente", "SMTP_FROM")):
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    cfg["porta"] = int(cfg["porta"] or 587)
    return cfg


def enviar_email(para, assunto, texto, html, anexos=()):
    cfg = smtp_config()
    gm = gmail_config()
    usar_gmail = bool(gm["refresh_token"])
    if not usar_gmail and (not cfg["host"] or not cfg["remetente"]):
        raise RuntimeError("Envio de e-mail não configurado. Peça ao administrador para configurar em Empresa › E-mail.")
    msg = EmailMessage()
    msg["Subject"] = assunto
    remetente = gm["email"] if usar_gmail else cfg["remetente"]
    msg["From"] = formataddr((cfg["nome_remetente"] or "", remetente))
    msg["To"] = para
    if cfg.get("copia"):
        msg["Cc"] = cfg["copia"]
    msg["Message-ID"] = make_msgid()
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    for nome, dados, tipo in anexos:
        maintype, subtype = tipo.split("/")
        msg.add_attachment(dados, maintype=maintype, subtype=subtype, filename=nome)
    if usar_gmail:
        return _gmail_enviar(gm, msg)
    ctx = ssl.create_default_context()
    try:
        if cfg["seguranca"] == "ssl":
            srv = smtplib.SMTP_SSL(cfg["host"], cfg["porta"], timeout=20, context=ctx)
        else:
            srv = smtplib.SMTP(cfg["host"], cfg["porta"], timeout=20)
            if cfg["seguranca"] == "starttls":
                srv.starttls(context=ctx)
        with srv:
            if cfg["usuario"]:
                srv.login(cfg["usuario"], cfg["senha"])
            srv.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("O servidor de e-mail recusou o usuário/senha configurados.")
    except (smtplib.SMTPException, OSError) as e:
        raise RuntimeError(f"Falha ao enviar o e-mail: {e}")


# ---------------------------------------------------------------- e-mail (API do Gmail)
# Envia por HTTPS (gmail.googleapis.com) em vez de SMTP. Útil em hospedagens que bloqueiam
# SMTP, como a conta gratuita do PythonAnywhere (que libera *.googleapis.com).

GMAIL_PADRAO = {"client_id": "", "client_secret": "", "refresh_token": "", "email": ""}
GMAIL_ESCOPOS = "openid email https://www.googleapis.com/auth/gmail.send"
_gmail_token = {"valor": None, "expira": 0}


def gmail_config():
    r = db().execute("SELECT valor FROM config WHERE chave='gmail'").fetchone()
    return dict(GMAIL_PADRAO, **(json.loads(r["valor"]) if r else {}))


def _gmail_salvar(cfg):
    db().execute("INSERT OR REPLACE INTO config VALUES ('gmail', ?)", (json.dumps(cfg),))
    db().commit()


def _http_json(url, dados=None, token=None, corpo_json=None):
    """POST simples com urllib (respeita o proxy https_proxy do PythonAnywhere)."""
    import urllib.error
    import urllib.parse
    import urllib.request
    headers = {}
    if corpo_json is not None:
        body = json.dumps(corpo_json).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = urllib.parse.urlencode(dados or {}).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read().decode())
        except Exception:
            detalhe = {}
        err = detalhe.get("error")
        if isinstance(err, dict):
            err = err.get("message")
        raise RuntimeError(f"{e.code} {err or detalhe.get('error_description') or e.reason}")
    except OSError as e:
        raise RuntimeError(str(e))


def _gmail_redirect_uri():
    if os.environ.get("GMAIL_REDIRECT_URI"):
        return os.environ["GMAIL_REDIRECT_URI"]
    host = request.host
    local = host.split(":")[0] in ("localhost", "127.0.0.1")
    esquema = request.headers.get("X-Forwarded-Proto") or ("http" if local else "https")
    return f"{esquema}://{host}/api/gmail/callback"


def _gmail_enviar(gm, msg):
    try:
        if not _gmail_token["valor"] or time.time() > _gmail_token["expira"] - 60:
            t = _http_json("https://oauth2.googleapis.com/token", {
                "client_id": gm["client_id"], "client_secret": gm["client_secret"],
                "refresh_token": gm["refresh_token"], "grant_type": "refresh_token"})
            _gmail_token.update(valor=t["access_token"], expira=time.time() + int(t.get("expires_in", 3600)))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        _http_json("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                   token=_gmail_token["valor"], corpo_json={"raw": raw})
    except RuntimeError as e:
        _gmail_token["valor"] = None
        if "invalid_grant" in str(e):
            raise RuntimeError("A autorização do Gmail expirou ou foi revogada. Clique em \"Conectar Gmail\" novamente.")
        raise RuntimeError(f"Falha ao enviar o e-mail pelo Gmail: {e}")


@app.get("/api/gmail")
@login_required(admin=True)
def api_gmail():
    gm = gmail_config()
    return jsonify(client_id=gm["client_id"], tem_secret=bool(gm["client_secret"]),
                   conectado=bool(gm["refresh_token"]), email=gm["email"], redirect_uri=_gmail_redirect_uri())


@app.put("/api/gmail")
@login_required(admin=True)
def api_salvar_gmail():
    d = request.get_json() or {}
    gm = gmail_config()
    novo_id = (d.get("client_id") or "").strip()
    if novo_id != gm["client_id"]:  # trocou a credencial: precisa autorizar de novo
        gm.update(refresh_token="", email="")
    gm["client_id"] = novo_id
    if (d.get("client_secret") or "").strip():
        gm["client_secret"] = d["client_secret"].strip()
    _gmail_salvar(gm)
    return jsonify(ok=True)


@app.post("/api/gmail/desconectar")
@login_required(admin=True)
def api_gmail_desconectar():
    gm = gmail_config()
    gm.update(refresh_token="", email="")
    _gmail_salvar(gm)
    _gmail_token["valor"] = None
    return jsonify(ok=True)


@app.get("/api/gmail/conectar")
@login_required(admin=True)
def api_gmail_conectar():
    import urllib.parse
    from flask import redirect
    gm = gmail_config()
    if not gm["client_id"] or not gm["client_secret"]:
        return jsonify(erro="Salve o Client ID e o Client secret antes de conectar"), 400
    session["gmail_state"] = secrets.token_urlsafe(24)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": gm["client_id"], "redirect_uri": _gmail_redirect_uri(), "response_type": "code",
        "scope": GMAIL_ESCOPOS, "access_type": "offline", "prompt": "consent",
        "state": session["gmail_state"]})
    return redirect(url)


@app.get("/api/gmail/callback")
@login_required(admin=True)
def api_gmail_callback():
    from flask import redirect
    estado = session.pop("gmail_state", None)
    if not estado or request.args.get("state") != estado:
        return redirect("/#/empresa?gmail=erro_estado")
    if request.args.get("error") or not request.args.get("code"):
        return redirect("/#/empresa?gmail=cancelado")
    gm = gmail_config()
    try:
        t = _http_json("https://oauth2.googleapis.com/token", {
            "code": request.args["code"], "client_id": gm["client_id"], "client_secret": gm["client_secret"],
            "redirect_uri": _gmail_redirect_uri(), "grant_type": "authorization_code"})
    except RuntimeError:
        return redirect("/#/empresa?gmail=erro_token")
    if not t.get("refresh_token"):
        return redirect("/#/empresa?gmail=erro_token")
    email = ""
    try:  # o id_token veio direto do Google por HTTPS; só lemos o e-mail dele
        carga = t["id_token"].split(".")[1]
        email = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))).get("email", "")
    except Exception:
        pass
    gm.update(refresh_token=t["refresh_token"], email=email)
    _gmail_salvar(gm)
    _gmail_token.update(valor=t.get("access_token"), expira=time.time() + int(t.get("expires_in", 3600)))
    return redirect("/#/empresa?gmail=ok")


def _html_email(corpo_html, empresa):
    return f"""<div style="font-family:Arial,sans-serif;color:#24272B;max-width:560px">
      <div style="border-bottom:3px solid #F2501B;padding-bottom:8px;margin-bottom:16px;font-weight:bold;color:#C93A0C">{empresa}</div>
      {corpo_html}
      <p style="color:#8a9097;font-size:12px;margin-top:24px">Mensagem automática do sistema de Termos de Responsabilidade.</p></div>"""


@app.get("/api/smtp")
@login_required(admin=True)
def api_smtp():
    cfg = smtp_config()
    cfg["tem_senha"] = bool(cfg.pop("senha"))
    return jsonify(cfg)


@app.put("/api/smtp")
@login_required(admin=True)
def api_salvar_smtp():
    d = request.get_json() or {}
    atual = smtp_config()
    novo = {k: d.get(k, atual[k]) for k in SMTP_PADRAO}
    if not d.get("senha"):  # campo vazio = manter a senha já salva
        novo["senha"] = atual["senha"]
    if novo["seguranca"] not in ("starttls", "ssl", "nenhuma"):
        novo["seguranca"] = "starttls"
    db().execute("INSERT OR REPLACE INTO config VALUES ('smtp', ?)", (json.dumps(novo),))
    db().commit()
    return jsonify(ok=True)


@app.post("/api/smtp/teste")
@login_required(admin=True)
def api_teste_smtp():
    para = ((request.get_json() or {}).get("para") or "").strip()
    if not EMAIL_RE.match(para):
        return jsonify(erro="Informe um e-mail válido"), 400
    try:
        enviar_email(para, "Teste de envio - Termos de Responsabilidade",
                     "O envio de e-mails do sistema está funcionando.",
                     _html_email("<p>O envio de e-mails do sistema está funcionando. ✅</p>", "Termos de Responsabilidade"))
    except RuntimeError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.post("/api/termos/<int:tid>/email")
@login_required()
def api_enviar_termo(tid):
    r = db().execute("SELECT * FROM termos WHERE id=?", (tid,)).fetchone()
    if not r:
        return jsonify(erro="Termo não encontrado"), 404
    d = request.get_json() or {}
    para = (d.get("para") or "").strip()
    if not EMAIL_RE.match(para):
        return jsonify(erro="Informe um e-mail válido"), 400
    try:
        pdf = base64.b64decode((d.get("pdf") or "").split(",")[-1], validate=True)
    except Exception:
        pdf = b""
    if not pdf.startswith(b"%PDF"):
        return jsonify(erro="Não foi possível gerar o PDF do termo"), 400
    dados = json.loads(r["dados"])
    emp = (dados.get("empresaSnapshot") or {}).get("empresa") or EMPRESA_PADRAO["empresa"]
    nome = r["colaborador"] or "colaborador(a)"
    primeiro = nome.split()[0] if nome.split() else nome
    extra = (d.get("mensagem") or "").strip()
    doc_nome = {"acessos": "Termo de Responsabilidade de Acessos",
                "completo": "Termo de Responsabilidade por Equipamentos e Acessos"}.get(
        r["tipo"], "Termo de Responsabilidade por Equipamentos")
    ref = "aos acessos fornecidos" if r["tipo"] == "acessos" else "aos itens entregues"
    texto = (f"Olá, {primeiro}.\n\nSegue em anexo a sua via do {doc_nome} "
             f"nº {r['numero']}, referente {ref} pela {emp}.\n\n"
             + (extra + "\n\n" if extra else "") + "Guarde este documento para sua conferência.\n\nAtenciosamente,\n" + emp)
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = _html_email(
        f"<p>Olá, <b>{esc(primeiro)}</b>.</p><p>Segue em anexo a sua via do <b>{doc_nome} "
        f"nº {esc(r['numero'])}</b>, referente {ref} pela {esc(emp)}.</p>"
        + (f"<p>{esc(extra).replace(chr(10), '<br>')}</p>" if extra else "")
        + "<p>Guarde este documento para sua conferência.</p>", esc(emp))
    nome_arq = re.sub(r"[^\w\-]+", "-", f"{r['numero']}-{nome}").strip("-") + ".pdf"
    try:
        enviar_email(para, f"{doc_nome} {r['numero']} - {nome}", texto, html,
                     [(nome_arq, pdf, "application/pdf")])
    except RuntimeError as e:
        return jsonify(erro=str(e)), 400
    registrar(tid, "enviado por e-mail", para)
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- backup

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_RE = re.compile(r"^(auto|manual|antes-restauracao)-\d{4}-\d{2}-\d{2}_\d{6}\.db$")
MANTER_AUTO = int(os.environ.get("BACKUPS_AUTOMATICOS", "30"))
_ultimo_auto = {"dia": None}


def _carimbo():
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def criar_backup(tipo):
    """Cópia consistente do banco (API de backup do SQLite) — segura mesmo com o sistema em uso."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    nome = f"{tipo}-{_carimbo()}.db"
    tmp = os.path.join(BACKUP_DIR, f".{nome}.tmp")
    src = sqlite3.connect(DB_PATH, timeout=15)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.commit()
    finally:
        dst.close()
        src.close()
    os.replace(tmp, os.path.join(BACKUP_DIR, nome))
    return nome


def listar_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for n in os.listdir(BACKUP_DIR):
        if BACKUP_RE.match(n):
            st = os.stat(os.path.join(BACKUP_DIR, n))
            out.append({"nome": n, "tipo": "antes-restauracao" if n.startswith("antes") else n.split("-")[0],
                        "tamanho": st.st_size, "mtime": st.st_mtime,
                        "criado_em": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    out.sort(key=lambda b: b["mtime"], reverse=True)  # mais recente primeiro
    for b in out:
        b.pop("mtime")
    return out


def _limpar_automaticos():
    autos = sorted(b["nome"] for b in listar_backups() if b["tipo"] == "auto")
    for n in autos[:-MANTER_AUTO] if MANTER_AUTO > 0 else []:
        try:
            os.remove(os.path.join(BACKUP_DIR, n))
        except OSError:
            pass


@app.before_request
def _backup_diario():
    """Um backup automático por dia, feito no primeiro acesso do dia (não precisa de agendador)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    if _ultimo_auto["dia"] == hoje or not request.path.startswith("/api/"):
        return
    _ultimo_auto["dia"] = hoje
    try:
        if not any(b["nome"].startswith(f"auto-{hoje}") for b in listar_backups()):
            criar_backup("auto")
            _limpar_automaticos()
    except Exception as e:  # backup nunca pode derrubar o sistema
        print("Falha no backup automático:", e, flush=True)


def validar_banco(caminho):
    """Confere se o arquivo é um banco deste sistema, íntegro e com um administrador ativo."""
    try:
        with open(caminho, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return "O arquivo não é um backup do sistema (formato inválido)"
        c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        try:
            tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "termos", "config", "historico"} <= tabelas:
                return "O arquivo não é um backup deste sistema (tabelas ausentes)"
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "O backup está corrompido"
            if not c.execute("SELECT 1 FROM users WHERE perfil='admin' AND ativo=1").fetchone():
                return "O backup não tem nenhum administrador ativo"
        finally:
            c.close()
    except sqlite3.DatabaseError:
        return "O arquivo não é um backup válido"
    return None


def resumo_banco(caminho):
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return {"termos": c.execute("SELECT COUNT(*) FROM termos").fetchone()[0],
                "usuarios": c.execute("SELECT COUNT(*) FROM users").fetchone()[0]}
    finally:
        c.close()


@app.get("/api/backups")
@login_required(admin=True)
def api_backups():
    return jsonify(backups=listar_backups(), automaticos=MANTER_AUTO, atual=resumo_banco(DB_PATH))


@app.post("/api/backups")
@login_required(admin=True)
def api_criar_backup():
    try:
        nome = criar_backup("manual")
    except Exception as e:
        return jsonify(erro=f"Não foi possível criar o backup: {e}"), 500
    return jsonify(nome=nome), 201


@app.get("/api/backups/<nome>")
@login_required(admin=True)
def api_baixar_backup(nome):
    if not BACKUP_RE.match(nome) or not os.path.isfile(os.path.join(BACKUP_DIR, nome)):
        return jsonify(erro="Backup não encontrado"), 404
    return send_file(os.path.join(BACKUP_DIR, nome), as_attachment=True,
                     download_name=f"termos-backup-{nome}", mimetype="application/octet-stream")


@app.delete("/api/backups/<nome>")
@login_required(admin=True)
def api_excluir_backup(nome):
    p = os.path.join(BACKUP_DIR, nome)
    if not BACKUP_RE.match(nome) or not os.path.isfile(p):
        return jsonify(erro="Backup não encontrado"), 404
    os.remove(p)
    return jsonify(ok=True)


@app.post("/api/backups/restaurar")
@login_required(admin=True)
def api_restaurar_backup():
    """Restaura a partir de um backup do servidor (nome) ou de um arquivo enviado (base64).
    Antes de substituir, guarda uma cópia do banco atual em 'antes-restauracao-...'."""
    d = request.get_json() or {}
    tmp = None
    try:
        if d.get("nome"):
            if not BACKUP_RE.match(d["nome"]):
                return jsonify(erro="Backup não encontrado"), 404
            origem = os.path.join(BACKUP_DIR, d["nome"])
            if not os.path.isfile(origem):
                return jsonify(erro="Backup não encontrado"), 404
        else:
            try:
                dados = base64.b64decode((d.get("arquivo") or "").split(",")[-1], validate=True)
            except Exception:
                return jsonify(erro="Arquivo inválido"), 400
            fd, tmp = tempfile.mkstemp(suffix=".db", dir=DATA_DIR)
            with os.fdopen(fd, "wb") as f:
                f.write(dados)
            origem = tmp
        erro = validar_banco(origem)
        if erro:
            return jsonify(erro=erro), 400
        seguranca = criar_backup("antes-restauracao")
        src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
        dst = sqlite3.connect(DB_PATH, timeout=30)
        try:
            src.backup(dst)  # substitui o conteúdo do banco em uso de forma atômica
        finally:
            src.close()
            dst.close()
        init_db()  # aplica migrações caso o backup seja de uma versão anterior
        print(f"Banco restaurado por {g.user['login']} (cópia anterior: {seguranca})", flush=True)
        return jsonify(ok=True, copia_anterior=seguranca, **resumo_banco(DB_PATH))
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------- front

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/healthz")
def health():
    return "ok"


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)
