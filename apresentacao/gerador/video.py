"""Monta o vídeo MP4: slides PNG + narração WAV, transições, zoom suave e legendas.
uso: python video.py <pasta_deck> <arquivo_mp4>
"""
import json, os, re, subprocess, sys, wave
import imageio_ffmpeg

DECK, OUT = sys.argv[1], sys.argv[2]
FF = imageio_ffmpeg.get_ffmpeg_exe()
PNG, AUD = os.path.join(DECK, "png"), os.path.join(DECK, "audio")
textos = json.load(open(os.path.join(DECK, "narracao.json"), encoding="utf-8"))
n = len(textos)
FPS, T, PRE, POS = 30, 0.7, 0.6, 1.0   # transição, silêncio antes/depois da fala

def dur(p):
    with wave.open(p) as w: return w.getnframes() / w.getframerate()
fala = [dur(os.path.join(AUD, f"narr{i + 1:02d}.wav")) for i in range(n)]
D = [max(5.0, PRE + f + POS) for f in fala]
inicio = [sum(D[:i]) - i * T for i in range(n)]          # início de cada slide na linha do tempo
total = sum(D) - (n - 1) * T

args = [FF, "-y"]
for i in range(n): args += ["-i", os.path.join(PNG, f"slide{i + 1:02d}.png")]
for i in range(n): args += ["-i", os.path.join(AUD, f"narr{i + 1:02d}.wav")]

f = []
for i in range(n):
    N = int(round(D[i] * FPS))
    z = "1+0.03*on/{N}".format(N=N) if i % 2 == 0 else "1.03-0.03*on/{N}".format(N=N)   # alterna aproximar/afastar
    f.append(f"[{i}:v]scale=3840:2160,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={N}:s=1920x1080:fps={FPS},format=yuv420p,setsar=1[v{i}]")
prev = "v0"
for i in range(1, n):
    off = sum(D[:i]) - i * T
    trans = "fadeblack" if i in (1, n - 1) else "fade"
    f.append(f"[{prev}][v{i}]xfade=transition={trans}:duration={T}:offset={off:.3f}[x{i}]"); prev = f"x{i}"
for i in range(n):
    ms = int((inicio[i] + PRE) * 1000)
    f.append(f"[{n + i}:a]aresample=44100,adelay={ms}|{ms}[a{i}]")
f.append("".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,apad,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")

# legendas: divide a fala de cada slide em frases e distribui o tempo pelo tamanho
def ts(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"
srt, k = [], 1
for i, txt in enumerate(textos):
    frases = []
    for x in (x.strip() for x in re.split(r"(?<=[.!?])\s+", txt) if x.strip()):
        if frases and len(frases[-1]) < 20: frases[-1] += " " + x   # junta frases curtas ("Olá!") com a seguinte
        else: frases.append(x)
    t0, tot = inicio[i] + PRE, sum(len(x) for x in frases)
    for fr in frases:
        d = fala[i] * len(fr) / tot
        srt.append(f"{k}\n{ts(t0)} --> {ts(t0 + d - 0.05)}\n{fr}\n"); k += 1; t0 += d
srt_path = os.path.splitext(OUT)[0] + ".srt"
open(srt_path, "w", encoding="utf-8").write("\n".join(srt))

fc = os.path.join(DECK, "filtro.txt"); open(fc, "w", encoding="utf-8").write(";\n".join(f))
args += ["-i", srt_path, "-/filter_complex", fc, "-map", f"[{prev}]", "-map", "[aout]", "-map", f"{2 * n}:s",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text", "-metadata:s:s:0", "language=por",
         "-metadata", "title=Termos de Responsabilidade – Guia do usuário", "-movflags", "+faststart", "-t", f"{total:.3f}", OUT]
print(f"duração total: {total:.1f}s ({total / 60:.1f} min)", flush=True)
r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode: print(r.stderr[-3000:]); sys.exit(1)
print("ok", OUT, os.path.getsize(OUT) // 1024, "KB")
