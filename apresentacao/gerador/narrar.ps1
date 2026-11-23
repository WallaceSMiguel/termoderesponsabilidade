param([string]$Json, [string]$OutDir)
# Gera um WAV por slide com a voz Microsoft Maria (pt-BR), offline.
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$textos = Get-Content -Raw -Encoding UTF8 $Json | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(44100, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$i = 0
foreach ($t in $textos) {
    $i++
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SelectVoice("Microsoft Maria Desktop")
    $s.Rate = 2
    $arq = Join-Path $OutDir ("narr{0:D2}.wav" -f $i)
    $s.SetOutputToWaveFile($arq, $fmt)
    $s.Speak([string]$t)
    $s.Dispose()
    "ok $arq"
}
