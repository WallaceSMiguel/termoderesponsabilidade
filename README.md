# Termos de Responsabilidade – Valorização Assessoria Contábil

Sistema web para gerar, guardar e consultar termos de responsabilidade por equipamentos.

## Funcionalidades
- Login com usuários e perfis (**Administrador** e **Usuário**); senha provisória obrigatoriamente trocada no 1º acesso
- Cadastro, edição e bloqueio de usuários (admin)
- Geração do termo com pré-visualização em A4 e logo da empresa; impressão / PDF pelo navegador
- Todos os termos ficam salvos no banco com número sequencial (`TR-2026-0001`), busca por colaborador, CPF, número ou equipamento
- Status **Ativo / Devolvido / Cancelado**, com histórico de quem criou, editou e registrou devolução
- Cláusula opcional de acessos a sistemas (sem registrar senhas)
- Dados da empresa e logo editáveis (admin); termos antigos mantêm os dados da época

## Rodar no computador
```powershell
pip install -r requirements.txt
python app.py
```
Abra http://localhost:5000. Na primeira execução é criado o usuário `admin`; se `ADMIN_PASSWORD` não estiver definida, a senha inicial fica em `data/senha-inicial-admin.txt` (apague o arquivo depois de entrar).

## Subir para a nuvem
Funciona em qualquer serviço que rode Python ou Docker (Render, Railway, Fly.io, VPS, Azure App Service…).

1. Envie esta pasta para um repositório Git (o `.gitignore` já exclui o banco `data/`).
2. Configure as variáveis de ambiente (modelo em `.env.example`):
   - `SECRET_KEY` – valor aleatório longo
   - `ADMIN_PASSWORD` – senha inicial do admin
   - `DATA_DIR` – pasta em **disco persistente** (ex.: `/data`). Sem disco persistente os termos se perdem a cada deploy.
   - `COOKIE_SECURE=1` – quando estiver em HTTPS (obrigatório para acesso externo)
3. Comando de início: `gunicorn -w 2 -b 0.0.0.0:$PORT app:app` (já no `Procfile` e no `Dockerfile`).

### Backup
Todo o conteúdo está no arquivo `DATA_DIR/termos.db` (SQLite). Faça cópia periódica desse arquivo.

## Executável (Windows)
`dist/TermosResponsabilidade.exe` roda sem precisar instalar Python:
- Dê dois cliques: abre uma janela preta (o servidor) e o navegador em http://localhost:5000. Fechar a janela encerra o sistema.
- O banco fica na pasta `data` **ao lado do .exe** — copie essa pasta para fazer backup. A senha inicial do `admin` fica em `data/senha-inicial-admin.txt` (apague depois de entrar).
- Para gerar o executável de novo após mudanças:
```powershell
python -m PyInstaller --noconfirm --onefile --name TermosResponsabilidade --icon icone.ico --add-data "static;static" --hidden-import waitress iniciar.py
```

## PythonAnywhere
No arquivo WSGI, defina `DATA_DIR` (pasta fora do código), `COOKIE_SECURE=1` e `SQLITE_JOURNAL=DELETE`
(o modo WAL do SQLite não é seguro no disco de rede do PythonAnywhere). Para atualizar:
`cd ~/termoderesponsabilidade && git pull` no console e **Reload** na aba Web.
