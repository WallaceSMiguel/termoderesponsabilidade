# Gerador da apresentação

Refaz o PowerPoint e o vídeo depois de mudanças no sistema. Rode a partir de uma pasta de trabalho
(ex.: `C:\temp\guia`), com Python, python-pptx, Pillow, requests, websocket-client e imageio-ffmpeg instalados.

```powershell
python capturas.py <projeto>\apresentacao\telas          # telas com dados fictícios (Edge headless)
python deck.py <projeto> <trabalho>                       # PowerPoint + HTML dos slides + roteiro de narração
python render.py <trabalho>\html <trabalho>\png           # slides em PNG 1920x1080
powershell -File narrar.ps1 -Json <trabalho>\narracao.json -OutDir <trabalho>\audio   # voz Microsoft Maria
python video.py <trabalho> <projeto>\apresentacao\Guia-Termos-de-Responsabilidade.mp4
```

Os textos dos slides e da narração ficam em `deck.py`.
