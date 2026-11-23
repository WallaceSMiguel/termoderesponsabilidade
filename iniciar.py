"""Inicializador do executável: sobe o servidor e abre o navegador."""
import os
import socket
import threading
import webbrowser

from waitress import serve

from app import DATA_DIR, app

PORT = int(os.environ.get("PORT", "5000"))
# Por padrão só este computador acessa. Para liberar na rede local, defina HOST=0.0.0.0
HOST = os.environ.get("HOST", "127.0.0.1")


def porta_em_uso(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    url = f"http://localhost:{PORT}"
    if porta_em_uso(PORT):
        print(f"O sistema já está aberto. Abrindo {url}")
        webbrowser.open(url)
    else:
        print("=" * 60)
        print(" Termos de Responsabilidade - Valorização")
        print(f" Endereço: {url}")
        print(f" Dados salvos em: {DATA_DIR}")
        print(" Feche esta janela para encerrar o sistema.")
        print("=" * 60)
        if os.environ.get("ABRIR_NAVEGADOR", "1") != "0":
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        serve(app, host=HOST, port=PORT, threads=8)
