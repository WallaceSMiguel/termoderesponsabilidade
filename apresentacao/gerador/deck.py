"""Guia do usuário – Termos de Responsabilidade.
Um único roteiro de slides gera:
  * PowerPoint nativo (python-pptx, textos editáveis)  -> apresentacao/Guia-Termos-de-Responsabilidade.pptx
  * HTML 1920x1080 de cada slide (mesmo layout)          -> renderizado pelo Edge em PNG para o vídeo/QA
  * roteiro de narração (JSON)
uso: python deck.py <pasta_projeto> <pasta_trabalho>
"""
import html, json, os, sys
from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree

PROJ, WORK = sys.argv[1], sys.argv[2]
TELAS = os.path.join(PROJ, "apresentacao", "telas")
LOGO = os.path.join(PROJ, "static", "logo.jpg")
CROPS = os.path.join(WORK, "crops"); os.makedirs(CROPS, exist_ok=True)

SW, SH = 13.333, 7.5
PX = 144  # px por polegada no HTML (1920 px de largura)
C = dict(brand="F2501B", dark="C93A0C", ink="24272B", muted="5E646B", line="E3E5E8", bg="F5F6F8",
         soft="FFF1EB", white="FFFFFF", night="17191C", night2="23262B", gray="9AA0A6", purple="5B3CC4", green="1D7A3C")
FONT, EMOJI = "Segoe UI", "Segoe UI Emoji"

# ------------------------------------------------------------------ recortes das telas
def crop(name, box=None, out=None):
    src = os.path.join(TELAS, name)
    dst = os.path.join(CROPS, out or name)
    im = Image.open(src).convert("RGB")
    if box: im = im.crop(box)
    im.save(dst, quality=95) if dst.endswith(".jpg") else im.save(dst)
    return dst

def crop_dialog(name, out, inset=7):
    """Recorta a janela de diálogo: é a única área de branco puro sobre o fundo escurecido."""
    im = Image.open(os.path.join(TELAS, name)).convert("RGB")
    mask = im.point(lambda v: 255 if v == 255 else 0).convert("L").point(lambda v: 255 if v == 255 else 0)
    x0, y0, x1, y1 = mask.getbbox()
    dst = os.path.join(CROPS, out)
    im.crop((x0 + inset, y0 + inset, x1 - inset, y1 - inset)).save(dst)
    return dst

IMG = {
    "login": crop("01-login.png", (820, 300, 1580, 1050), "login.png"),
    "lista": crop("02-lista.png"),
    "lista_barra": crop("03-lista-barra.png"),
    "novo": crop("04-novo-equipamentos.png"),
    "tipo": crop("05-tipo.png"),
    "unidade": crop("06-unidade.png"),
    "itens": crop("07-itens.png"),
    "acessos": crop("08-acessos.png"),
    "sistemas": crop("09-sistemas.png"),
    "doc_acessos": crop("10-doc-acessos.png", (0, 0, 1587, 1500), "doc-acessos-topo.png"),
    "completo": crop("11-termo-completo.png"),
    "email": crop_dialog("13-enviar-email.png", "email.png"),
    "devolucao": crop_dialog("14-devolucao.png", "devolucao.png"),
    "historico": crop("15-historico.png", (1635, 110, 2115, 1195), "historico.png"),
    "usuarios": crop("16-usuarios.png", (330, 70, 2070, 730), "usuarios.png"),
    "novo_usuario": crop("17-novo-usuario.png", (820, 300, 1580, 1050), "novo-usuario.png"),
    "empresa": crop("18-empresa.png", (640, 70, 1760, 1350), "empresa.png"),
    "config_email": crop("19-config-email.png", (500, 0, 1900, 1350), "config-email.png"),
}

# ------------------------------------------------------------------ primitivas do roteiro
def R(x, y, w, h, fill, radius=0, line=None, shadow=False, name=None):
    return dict(t="rect", x=x, y=y, w=w, h=h, fill=fill, radius=radius, line=line, shadow=shadow, name=name)

def O(x, y, d, fill, name=None):
    return dict(t="oval", x=x, y=y, w=d, h=d, fill=fill, name=name)

def T(x, y, w, h, paras, size=16, color=C["ink"], bold=False, align="l", valign="t", font=FONT, ls=1.22, name=None):
    """paras: str (\\n separa parágrafos; **negrito**) ou lista de parágrafos [(texto, {opções})]."""
    if isinstance(paras, str): paras = paras.split("\n")
    ps = []
    for p in paras:
        opts = {}
        if isinstance(p, tuple): p, opts = p
        runs, b = [], False
        for i, chunk in enumerate(p.split("**")):
            if chunk: runs.append(dict(text=chunk, bold=bold or (i % 2 == 1)))
        ps.append(dict(runs=runs or [dict(text="", bold=False)], size=opts.get("size", size), color=opts.get("color", color),
                       font=opts.get("font", font), after=opts.get("after", 0), align=opts.get("align", align)))
    return dict(t="text", x=x, y=y, w=w, h=h, paras=ps, valign=valign, ls=ls, name=name)

def IMGBOX(x, y, w, h, key, frame=True, align="c", name=None):
    """Imagem encaixada (sem distorcer) na caixa; devolve o elemento com a área real usada."""
    path = IMG[key]; iw, ih = Image.open(path).size
    s = min(w / iw, h / ih); rw, rh = iw * s, ih * s
    rx = x + (w - rw) / 2 if align == "c" else (x if align == "l" else x + w - rw)
    ry = y + (h - rh) / 2
    return dict(t="img", x=rx, y=ry, w=rw, h=rh, src=path, frame=frame, name=name or key)

def num(x, y, n, d=0.46, fill=C["brand"], size=15):
    return [O(x, y, d, fill, name=f"num{n}"), T(x, y, d, d, str(n), size=size, color=C["white"], bold=True, align="c", valign="m")]

def icon(x, y, emoji, d=0.72, fill=C["soft"]):
    return [O(x, y, d, fill, name="icone"), T(x, y + 0.01, d, d, emoji, size=d * 30, align="c", valign="m", font=EMOJI)]

def header(kicker, title, sub=None):
    els = [T(0.7, 0.42, 9, 0.32, kicker.upper(), size=12, color=C["brand"], bold=True, name="kicker"),
           T(0.7, 0.72, 11.9, 0.75, title, size=32, bold=True, name="titulo")]
    if sub: els.append(T(0.7, 1.42, 11.9, 0.4, sub, size=15, color=C["muted"], name="subtitulo"))
    return els

def footer(n, dark=False):
    col = C["gray"] if dark else C["muted"]
    return [T(0.7, 7.02, 8, 0.3, "Termos de Responsabilidade · Guia do usuário", size=10, color=col, name="rodape"),
            T(11.63, 7.02, 1.0, 0.3, f"{n:02d}", size=10, color=col, align="r", bold=True, name="pagina")]

def bullet_rows(x, y, w, items, gap=0.98, emoji=True, size=15, title_size=17):
    """Linhas com ícone em círculo + título + descrição."""
    els = []
    for i, (ic, tit, desc) in enumerate(items):
        yy = y + i * gap
        els += icon(x, yy, ic, d=0.62) if emoji else num(x + 0.08, yy + 0.08, ic)
        els.append(T(x + 0.85, yy - 0.02, w - 0.85, 0.36, tit, size=title_size, bold=True))
        els.append(T(x + 0.85, yy + 0.33, w - 0.85, gap - 0.3, desc, size=size, color=C["muted"]))
    return els

def callout(x, y, n, text, w=3.2):
    return num(x, y, n, d=0.42, size=14) + [T(x + 0.55, y - 0.03, w, 0.6, text, size=14.5)]

# ------------------------------------------------------------------ slides
S = []
def slide(bg, els, narr, dark=False, foot=True):
    n = len(S) + 1
    S.append(dict(bg=bg, els=els + (footer(n, dark) if foot else []), narr=narr))

# 1 — capa
IMG["logo"] = LOGO
slide(C["night"], [
    R(0, 0, SW, SH, C["night"]),
    R(6.75, 1.25, 6.1, 3.85, C["night2"], radius=0.25),
    IMGBOX(6.95, 1.45, 5.7, 3.45, "completo", name="tela_capa"),
    R(6.45, 4.45, 3.35, 2.3, C["white"], radius=0.2, shadow=True, name="cartao_sistemas"),
    IMGBOX(6.6, 4.6, 3.05, 2.0, "sistemas", frame=False, name="sistemas_capa"),
    R(0.7, 0.85, 3.6, 0.95, C["white"], radius=0.18, name="fundo_logo"),
    IMGBOX(0.85, 0.95, 3.3, 0.75, "logo", frame=False, name="logo"),
    T(0.7, 2.35, 5.45, 1.9, "Termos de\nResponsabilidade", size=46, color=C["white"], bold=True, ls=1.08),
    T(0.7, 4.35, 5.4, 0.5, "Guia do usuário · Equipamentos e acessos", size=18, color=C["brand"], bold=True),
    T(0.7, 4.95, 5.2, 1.0, "Como criar, imprimir, enviar e acompanhar os termos da Valorização Assessoria Contábil.", size=15, color="C9CDD2"),
    T(0.7, 6.55, 6.0, 0.35, "Valorização Assessoria Contábil · 2026", size=11, color=C["gray"]),
], "Olá! Este é o guia do sistema de Termos de Responsabilidade da Valorização Assessoria Contábil. "
   "Em poucos minutos, você vai aprender a criar, imprimir, enviar e acompanhar os termos de equipamentos e de acessos.",
   dark=True, foot=False)

# 2 — o que o sistema faz
cards = [("💻", "Termo de equipamentos", "Notebook, monitor, celular e outros bens entregues ao colaborador."),
         ("🔑", "Termo de acessos", "Rede/VPN, e-mail, Onvio, Domínio Web, Linkus e pastas mapeadas."),
         ("📍", "Separado por unidade", "Barra, Nova América e Duque de Caxias, com filtro na lista."),
         ("✉️", "Envio e histórico", "Via em PDF por e-mail e registro de tudo o que foi feito.")]
els = header("Visão geral", "O que o sistema faz")
for i, (ic, t, d) in enumerate(cards):
    cx, cy = 0.7 + (i % 2) * 6.05, 1.85 + (i // 2) * 2.45
    els += [R(cx, cy, 5.85, 2.2, C["white"], radius=0.2, shadow=True, name="card")]
    els += icon(cx + 0.4, cy + 0.42, ic, d=0.85)
    els += [T(cx + 1.5, cy + 0.42, 4.1, 0.45, t, size=20, bold=True), T(cx + 1.5, cy + 0.92, 4.1, 1.1, d, size=15, color=C["muted"])]
slide(C["bg"], els, "O sistema faz quatro coisas principais. Gera o termo de equipamentos, como notebook, monitor e celular. "
      "Gera o termo de acessos, com rede, e-mail, Onvio, Domínio Web, telefonia Linkus e pastas mapeadas. "
      "Separa tudo por unidade: Barra, Nova América e Duque de Caxias. E envia a via em PDF por e-mail, guardando o histórico de cada termo.")

# 3 — acessar
els = header("Primeiros passos", "Como acessar o sistema")
els += bullet_rows(0.7, 2.05, 6.4, [
    (1, "Abra o sistema", "Dois cliques em TermosResponsabilidade.exe — o navegador abre sozinho. Na nuvem, use o endereço informado."),
    (2, "Entre com seu login", "Use o usuário e a senha criados pelo administrador."),
    (3, "Defina sua senha", "No primeiro acesso o sistema pede uma senha nova, com pelo menos 8 caracteres."),
], gap=1.45, emoji=False)
els += [R(7.6, 1.7, 5.05, 4.95, C["white"], radius=0.25, shadow=True), IMGBOX(7.85, 1.9, 4.55, 4.55, "login", frame=False)]
slide(C["bg"], els, "Para acessar, dê dois cliques no arquivo Termos Responsabilidade ponto exe. O navegador abre sozinho. "
      "Se o sistema estiver na nuvem, use o endereço informado pela equipe. Entre com o login e a senha criados pelo administrador. "
      "No primeiro acesso, o sistema pede que você defina uma senha nova.")

# 4 — tela inicial
els = header("Tela inicial", "Todos os termos em um só lugar")
im = IMGBOX(0.7, 1.75, 8.3, 4.95, "lista"); els.append(im)
els += callout(9.45, 1.95, 1, "**Abas por unidade** mostram os termos ativos de cada local.")
els += callout(9.45, 3.05, 2, "**Busque** por nome, CPF, número, equipamento ou sistema.")
els += callout(9.45, 4.15, 3, "**Filtre** por tipo de termo e por status.")
els += callout(9.45, 5.25, 4, "**Clique em uma linha** para abrir, imprimir ou enviar o termo.")
slide(C["bg"], els, "Esta é a tela inicial. No topo ficam as abas de cada unidade, com o número de termos ativos. "
      "Use a busca para encontrar por nome, CPF, número do termo, equipamento ou sistema. "
      "Filtre por tipo e por status, e clique em qualquer linha para abrir o termo.")

# 5 — fluxo
els = header("Criando um termo", "Novo termo em 4 passos", "Clique em “+ Novo termo” no canto superior direito.")
steps = [("Escolha o tipo", "Equipamentos, Acessos ou Junto"), ("Colaborador e unidade", "Dados da pessoa e local de trabalho"),
         ("Itens e/ou acessos", "O que está sendo entregue"), ("Salve e envie", "Imprima, gere PDF ou mande por e-mail")]
for i, (t, d) in enumerate(steps):
    x = 0.7 + i * 3.1
    els += [R(x, 2.45, 2.75, 3.6, C["white"], radius=0.22, shadow=True, name="passo")]
    els += num(x + 0.35, 2.8, i + 1, d=0.8, size=24)
    els += [T(x + 0.35, 3.85, 2.2, 0.85, t, size=19, bold=True, ls=1.12), T(x + 0.35, 4.75, 2.15, 1.1, d, size=14.5, color=C["muted"])]
    if i < 3: els.append(T(x + 2.72, 3.85, 0.42, 0.5, "→", size=24, color=C["brand"], bold=True, align="c"))
slide(C["bg"], els, "Criar um termo leva quatro passos. Primeiro, escolha o tipo. Depois, preencha o colaborador e a unidade. "
      "Em seguida, informe os itens ou os acessos entregues. Por fim, salve, imprima ou envie por e-mail.")

# 6 — passo 1 tipo
els = header("Passo 1 de 4", "Escolha o tipo de termo")
els += [R(0.7, 1.8, 11.95, 2.45, C["white"], radius=0.22, shadow=True), IMGBOX(1.0, 1.95, 11.35, 2.15, "tipo", frame=False)]
tipos = [("💻", "Equipamentos", "Termo de entrega, guarda e devolução de bens: notebook, monitor, celular, headset…"),
         ("🔑", "Acessos", "Ficha de acessos: sistemas, logins e detalhes como ramal ou caminho da pasta."),
         ("🧩", "Junto", "Um único documento com os equipamentos e a cláusula de acessos.")]
for i, (ic, t, d) in enumerate(tipos):
    x = 0.7 + i * 4.05
    els += icon(x, 4.6, ic, d=0.66) + [T(x + 0.85, 4.6, 3.0, 0.4, t, size=18, bold=True), T(x + 0.85, 5.02, 3.05, 1.5, d, size=14.5, color=C["muted"])]
slide(C["bg"], els, "Passo um: escolha o tipo de termo. Equipamentos é o termo de entrega e devolução de bens. "
      "Acessos é a ficha com os sistemas e logins do colaborador. E Junto gera um único documento com os equipamentos e os acessos.")

# 7 — passo 2 colaborador
els = header("Passo 2 de 4", "Colaborador e unidade")
els.append(IMGBOX(0.7, 1.75, 7.6, 4.95, "novo"))
els += [T(8.75, 1.8, 3.9, 0.35, "Escolha a unidade", size=15, bold=True), R(8.75, 2.2, 3.9, 0.95, C["white"], radius=0.15, shadow=True),
        IMGBOX(8.85, 2.27, 3.7, 0.81, "unidade", frame=False)]
els += bullet_rows(8.75, 3.55, 3.9, [("🪪", "Dados da pessoa", "Nome, CPF, RG, cargo e setor."),
                                    ("📧", "E-mail pessoal", "Para receber a via do termo."),
                                    ("👀", "Prévia ao vivo", "O documento se monta ao lado.")], gap=1.05, size=13.5, title_size=15.5)
slide(C["bg"], els, "Passo dois: selecione a unidade e preencha os dados do colaborador, como nome, CPF, cargo e setor. "
      "Informe também o e-mail pessoal, para onde a via do termo será enviada. Repare que o documento vai se montando ao lado, em tempo real.")

# 8 — passo 3 itens
els = header("Passo 3 de 4", "Itens entregues", "Para termos de Equipamentos ou Junto.")
els.append(IMGBOX(0.7, 1.95, 7.6, 4.75, "itens"))
els += bullet_rows(8.75, 2.05, 3.9, [("🏷️", "Item e patrimônio", "Descrição e nº de patrimônio ou de série."),
                                    ("✅", "Estado", "Novo, bom, usado, regular ou danificado."),
                                    ("➕", "Adicionar item", "Inclua quantos itens forem necessários.")], gap=1.4)
slide(C["bg"], els, "Passo três, para equipamentos: informe cada item entregue, com o número de patrimônio ou de série, "
      "a quantidade e o estado de conservação. Use o botão adicionar item para incluir quantos forem necessários.")

# 9 — passo 3 acessos
els = header("Passo 3 de 4", "Acessos fornecidos", "Para termos de Acessos ou Junto.")
els += [R(0.7, 1.95, 5.5, 4.75, C["white"], radius=0.22, shadow=True), IMGBOX(0.95, 2.15, 5.0, 4.35, "sistemas", frame=False)]
els += bullet_rows(6.75, 2.0, 5.9, [("👆", "Toque para selecionar", "Rede/VPN, e-mail, Onvio, Domínio Web, Linkus, pasta mapeada ou outro."),
                                   ("✨", "Preencher logins pelo nome", "Sugere nome.sobrenome e o e-mail corporativo automaticamente."),
                                   ("🔐", "Gerar senhas", "Cria senhas fortes com um clique."),
                                   ("📝", "Detalhes", "Ramal do Linkus, caminho da pasta, módulos do Domínio…")], gap=1.15)
slide(C["bg"], els, "Para acessos, toque nos cartões dos sistemas entregues: rede e VPN, e-mail corporativo, Onvio, Domínio Web, telefonia Linkus ou pasta mapeada. "
      "O botão preencher logins pelo nome sugere o usuário no padrão nome ponto sobrenome, e o botão gerar senhas cria senhas fortes. "
      "Complete os detalhes, como o ramal ou o caminho da pasta.")

# 10 — senhas
els = header("Segurança", "Senhas seguras por padrão")
els += [R(0.7, 1.7, 6.0, 5.05, C["white"], radius=0.22, shadow=True), IMGBOX(0.9, 1.85, 5.6, 4.75, "doc_acessos", frame=False)]
els += bullet_rows(7.2, 1.95, 5.45, [("🖨️", "Só na impressão", "A senha aparece no papel impresso logo após salvar."),
                                    ("🚫", "Não fica gravada", "O sistema não guarda senhas no banco de dados."),
                                    ("✉️", "Não vai por e-mail", "O PDF enviado ao colaborador sai sem senhas."),
                                    ("✍️", "Em branco?", "Sai uma linha para preencher à mão.")], gap=1.18)
slide(C["bg"], els, "Atenção às senhas. Elas aparecem apenas na impressão feita logo após salvar. "
      "O sistema não guarda senhas no banco de dados, e o PDF enviado por e-mail sai sem elas. "
      "Se você deixar a senha em branco, o termo traz uma linha para preencher à mão.")

# 11 — passo 4 salvar
els = header("Passo 4 de 4", "Salve, imprima e envie")
els.append(IMGBOX(0.7, 1.65, 8.3, 5.05, "completo"))
els += callout(9.45, 1.95, 1, "**Salvar termo** gera o número automático, como TR-2026-0004.")
els += callout(9.45, 3.05, 2, "**Imprimir / Salvar PDF** abre a impressão em A4 com a logo.")
els += callout(9.45, 4.15, 3, "**Enviar por e-mail** manda a via em PDF ao colaborador.")
els += callout(9.45, 5.25, 4, "**Editar** a qualquer momento — tudo fica no histórico.")
slide(C["bg"], els, "Passo quatro: clique em salvar termo. O sistema gera um número automático e abre o termo pronto. "
      "Daqui você pode imprimir ou salvar em PDF, enviar por e-mail ao colaborador ou editar quando precisar. Tudo fica registrado no histórico.")

# 12 — e-mail
els = header("Envio por e-mail", "A via do colaborador chega por e-mail")
els += [R(0.7, 1.75, 6.1, 4.95, C["white"], radius=0.22, shadow=True), IMGBOX(0.95, 1.95, 5.6, 4.55, "email", frame=False)]
els += bullet_rows(7.3, 2.0, 5.35, [("☑️", "Ao salvar", "Deixe marcada a opção “Enviar a via do termo” e informe o e-mail pessoal."),
                                   ("📨", "Ou depois", "Abra o termo e clique em “Enviar por e-mail”."),
                                   ("📎", "PDF em anexo", "O colaborador recebe a via em PDF; o envio vai para o histórico.")], gap=1.4)
slide(C["bg"], els, "O colaborador recebe a via do termo por e-mail. Basta deixar marcada a opção enviar a via ao salvar, ou clicar em enviar por e-mail depois. "
      "Ele recebe o documento em PDF, e o envio fica registrado no histórico.")

# 13 — acompanhamento
els = header("Acompanhamento", "Devolução, revogação e histórico")
els += [R(0.7, 1.75, 4.3, 3.0, C["white"], radius=0.22, shadow=True), IMGBOX(0.85, 1.9, 4.0, 2.7, "devolucao", frame=False)]
els += [R(5.25, 1.75, 2.75, 4.95, C["white"], radius=0.22, shadow=True), IMGBOX(5.35, 1.85, 2.55, 4.75, "historico", frame=False)]
els += bullet_rows(8.4, 1.95, 4.25, [("↩️", "Devolução / revogação", "Registre quando o colaborador devolver os itens ou sair."),
                                    ("🚫", "Cancelar", "Mantém o registro, sem apagar."),
                                    ("📋", "Duplicar", "Reaproveita itens e sistemas para outra pessoa."),
                                    ("🕒", "Histórico", "Quem criou, editou, enviou e quando.")], gap=1.15, size=13.5, title_size=15.5)
els += [T(0.7, 5.0, 4.3, 1.6, "Status do termo: **Ativo**, **Devolvido** ou **Cancelado** — visíveis na lista e nos totais da tela inicial.", size=14, color=C["muted"])]
slide(C["bg"], els, "No dia a dia, registre a devolução dos itens ou a revogação dos acessos quando o colaborador sair. "
      "Você também pode cancelar um termo sem apagá-lo, ou duplicar para outro colaborador aproveitando os mesmos itens e sistemas. "
      "O histórico mostra quem criou, editou e enviou cada termo.")

# 14 — administração
els = header("Administração", "Usuários e dados da empresa", "Disponível para o perfil Administrador.")
els += [IMGBOX(0.7, 1.95, 7.2, 3.35, "usuarios"), IMGBOX(8.4, 1.95, 4.25, 3.35, "empresa")]
els += [T(0.7, 5.5, 7.2, 0.4, "👥  Usuários", size=17, bold=True), T(0.7, 5.92, 7.2, 0.9, "Crie acessos, defina o perfil e bloqueie quem saiu. Senha provisória é trocada no 1º acesso.", size=14, color=C["muted"]),
        T(8.4, 5.5, 4.25, 0.4, "🏢  Empresa", size=17, bold=True), T(8.4, 5.92, 4.25, 0.9, "Dados, logo, unidades, domínio do e-mail corporativo e a conta que envia os e-mails.", size=14, color=C["muted"])]
slide(C["bg"], els, "Se você for administrador, cuida também dos usuários e dos dados da empresa. "
      "Em usuários, crie novos acessos, defina o perfil e bloqueie quem saiu. "
      "Em empresa, ajuste os dados, a logo, a lista de unidades e a conta de e-mail que envia os termos.")

# 15 — boas práticas
els = header("Boas práticas", "Dicas para o dia a dia")
tips = [("🔎", "Confira antes de salvar", "Revise nome, CPF, unidade e itens na prévia do documento."),
        ("🤝", "Entregue senhas pessoalmente", "Nunca envie senhas por e-mail ou mensagem."),
        ("↩️", "Registre o desligamento", "Devolução de itens e revogação de acessos no mesmo dia."),
        ("💾", "Faça backup", "Copie a pasta data, ao lado do sistema, com frequência.")]
for i, (ic, t, d) in enumerate(tips):
    cx, cy = 0.7 + (i % 2) * 6.05, 1.85 + (i // 2) * 2.45
    els += [R(cx, cy, 5.85, 2.2, C["white"], radius=0.2, shadow=True, name="card")]
    els += icon(cx + 0.4, cy + 0.42, ic, d=0.85)
    els += [T(cx + 1.5, cy + 0.42, 4.1, 0.45, t, size=19, bold=True), T(cx + 1.5, cy + 0.92, 4.1, 1.1, d, size=15, color=C["muted"])]
slide(C["bg"], els, "Algumas dicas. Confira os dados na prévia antes de salvar. Entregue as senhas pessoalmente, nunca por e-mail. "
      "Registre a devolução e a revogação no dia do desligamento. E faça cópias de segurança da pasta data com frequência.")

# 16 — encerramento
els = [R(0, 0, SW, SH, C["night"]),
       R(0.7, 0.85, 3.6, 0.95, C["white"], radius=0.18), IMGBOX(0.85, 0.95, 3.3, 0.75, "logo", frame=False),
       T(0.7, 2.3, 8.5, 1.0, "Pronto para usar!", size=50, color=C["white"], bold=True),
       T(0.7, 3.35, 8.0, 0.5, "Resumo em uma linha:", size=18, color=C["brand"], bold=True)]
resumo = [("1", "Novo termo"), ("2", "Tipo + unidade"), ("3", "Itens / acessos"), ("4", "Salvar e enviar")]
for i, (n, t) in enumerate(resumo):
    x = 0.7 + i * 3.1
    els += [R(x, 4.1, 2.85, 1.25, C["night2"], radius=0.2)] + num(x + 0.3, 4.48, n, d=0.5, size=16) + [T(x + 0.95, 4.5, 1.85, 0.5, t, size=16, color=C["white"], bold=True, valign="m")]
els += [T(0.7, 6.1, 11.9, 0.5, "Dúvidas? Fale com a equipe de Gestão de Projetos.", size=16, color="C9CDD2")]
slide(C["night"], els, "Pronto! Agora você já sabe usar o sistema: novo termo, tipo e unidade, itens ou acessos, e salvar e enviar. "
      "Em caso de dúvidas, fale com a equipe de Gestão de Projetos.", dark=True)

# ------------------------------------------------------------------ backend: PowerPoint
def rgb(h): return RGBColor.from_string(h)

def add_shadow(shape, blur=18, dist=3, alpha=14):
    spPr = shape._element.spPr
    eff = etree.SubElement(spPr, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad=str(Pt(blur)), dist=str(Pt(dist)), dir="5400000", algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val="1C1F23")
    etree.SubElement(clr, qn("a:alpha"), val=str(alpha * 1000))

def build_pptx(path):
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
    blank = prs.slide_layouts[6]
    for s in S:
        sl = prs.slides.add_slide(blank)
        sl.background.fill.solid(); sl.background.fill.fore_color.rgb = rgb(s["bg"])
        for e in s["els"]:
            x, y, w, h = Inches(e["x"]), Inches(e["y"]), Inches(e["w"]), Inches(e["h"])
            if e["t"] in ("rect", "oval"):
                kind = MSO_SHAPE.OVAL if e["t"] == "oval" else (MSO_SHAPE.ROUNDED_RECTANGLE if e.get("radius") else MSO_SHAPE.RECTANGLE)
                sh = sl.shapes.add_shape(kind, x, y, w, h)
                if e["t"] == "rect" and e.get("radius"): sh.adjustments[0] = min(0.5, e["radius"] / min(e["w"], e["h"]))
                sh.fill.solid(); sh.fill.fore_color.rgb = rgb(e["fill"])
                if e.get("line"): sh.line.color.rgb = rgb(e["line"]); sh.line.width = Pt(1)
                else: sh.line.fill.background()
                if e.get("shadow"): add_shadow(sh)
                if e.get("name"): sh.name = e["name"]
                sh.text_frame.text = ""
            elif e["t"] == "img":
                if e.get("frame"):
                    fr = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(e["x"] - 0.04), Inches(e["y"] - 0.04), Inches(e["w"] + 0.08), Inches(e["h"] + 0.08))
                    fr.fill.solid(); fr.fill.fore_color.rgb = rgb(C["white"]); fr.line.color.rgb = rgb(C["line"]); fr.line.width = Pt(0.75)
                    add_shadow(fr); fr.name = "moldura"
                pic = sl.shapes.add_picture(e["src"], x, y, w, h); pic.name = e.get("name") or "imagem"
            elif e["t"] == "text":
                tb = sl.shapes.add_textbox(x, y, w, h); tf = tb.text_frame
                tf.word_wrap = True; tf.auto_size = None
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[e["valign"]]
                if e.get("name"): tb.name = e["name"]
                for i, p in enumerate(e["paras"]):
                    para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    para.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[p["align"]]
                    para.line_spacing = Pt(p["size"] * e["ls"])
                    if p["after"]: para.space_after = Pt(p["after"])
                    for r in p["runs"]:
                        run = para.add_run(); run.text = r["text"]
                        f = run.font; f.size = Pt(p["size"]); f.bold = r["bold"]; f.color.rgb = rgb(p["color"]); f.name = p["font"]
        sl.notes_slide.notes_text_frame.text = s["narr"]
    prs.core_properties.title = "Termos de Responsabilidade – Guia do usuário"
    prs.core_properties.author = "Valorização Assessoria Contábil"
    prs.save(path)

# ------------------------------------------------------------------ backend: HTML (mesmas medidas)
def px(v): return f"{v * PX:.2f}px"

def build_html(i, s, path):
    out = [f"""<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{{margin:0;padding:0}} body{{width:1920px;height:1080px;position:relative;overflow:hidden;background:#{s['bg']};font-family:'{FONT}'}}
    .e{{position:absolute;box-sizing:border-box}} p{{margin:0;white-space:pre-wrap;overflow-wrap:break-word}}
    </style></head><body>"""]
    for e in s["els"]:
        st = f"left:{px(e['x'])};top:{px(e['y'])};width:{px(e['w'])};height:{px(e['h'])};"
        if e["t"] in ("rect", "oval"):
            rad = "50%" if e["t"] == "oval" else px(e.get("radius", 0))
            sh = "box-shadow:0 6px 36px rgba(28,31,35,.14);" if e.get("shadow") else ""
            ln = f"border:1px solid #{e['line']};" if e.get("line") else ""
            out.append(f'<div class="e" style="{st}background:#{e["fill"]};border-radius:{rad};{sh}{ln}"></div>')
        elif e["t"] == "img":
            if e.get("frame"):
                fst = f"left:{px(e['x'] - 0.04)};top:{px(e['y'] - 0.04)};width:{px(e['w'] + 0.08)};height:{px(e['h'] + 0.08)};"
                out.append(f'<div class="e" style="{fst}background:#fff;border:1.5px solid #{C["line"]};box-shadow:0 6px 36px rgba(28,31,35,.14)"></div>')
            out.append(f'<img class="e" style="{st}" src="file:///{e["src"].replace(os.sep, "/")}">')
        elif e["t"] == "text":
            jc = {"t": "flex-start", "m": "center", "b": "flex-end"}[e["valign"]]
            ps = []
            for p in e["paras"]:
                runs = "".join(f'<span style="font-weight:{700 if r["bold"] else 400}">{html.escape(r["text"])}</span>' for r in p["runs"])
                ps.append(f'<p style="font-size:{p["size"] * 2:.2f}px;line-height:{p["size"] * e["ls"] * 2:.2f}px;color:#{p["color"]};'
                          f'font-family:\'{p["font"]}\';text-align:{ {"l": "left", "c": "center", "r": "right"}[p["align"]]};'
                          f'margin-bottom:{p["after"] * 2}px">{runs or "&nbsp;"}</p>')
            out.append(f'<div class="e" style="{st}display:flex;flex-direction:column;justify-content:{jc}">{"".join(ps)}</div>')
    out.append("</body></html>")
    open(path, "w", encoding="utf-8").write("".join(out))

if __name__ == "__main__":
    os.makedirs(os.path.join(PROJ, "apresentacao"), exist_ok=True)
    pptx_path = os.path.join(PROJ, "apresentacao", "Guia-Termos-de-Responsabilidade.pptx")
    build_pptx(pptx_path); print("pptx:", pptx_path)
    hdir = os.path.join(WORK, "html"); os.makedirs(hdir, exist_ok=True)
    for i, s in enumerate(S): build_html(i, s, os.path.join(hdir, f"slide{i + 1:02d}.html"))
    json.dump([s["narr"] for s in S], open(os.path.join(WORK, "narracao.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("slides:", len(S))
