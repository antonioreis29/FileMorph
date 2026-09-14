# FFmpeg distribuído junto com o FileMorph

Esta pasta é onde fica o FFmpeg que o instalador leva para a máquina do
usuário, para áudio e vídeo funcionarem sem ninguém configurar o PATH do
Windows. **Nesta versão ela está vazia de propósito**: nenhum build do
FFmpeg foi escolhido e verificado ainda.

Sem os executáveis aqui, o build do FileMorph funciona normalmente — o
aplicativo só passa a depender de um FFmpeg instalado na máquina do usuário
(ou definido em `ffmpeg_path` nas configurações).

## Para incluir um FFmpeg

1. Escolha um build do FFmpeg para Windows 64 bits e **verifique a licença
   dele**. Um build com libx264 (necessário para MP4 e MKV) é GPL-3.0;
   um build só com componentes LGPL não gera H.264. A escolha muda o que
   precisa acompanhar a distribuição (texto da licença e oferta do
   código-fonte correspondente).
2. Copie para esta pasta:
   - `ffmpeg.exe`
   - `ffprobe.exe` (opcional, melhora o progresso)
   - o arquivo de licença do build (`LICENSE`, `COPYING` ou equivalente) —
     sem ele a receita do PyInstaller interrompe o empacotamento.
3. Registre o build em `THIRD_PARTY_LICENSES.md` (origem, versão, licença e
   onde está o código-fonte).
4. Rode `.\empacotar.ps1`. A mensagem `[FileMorph] FFmpeg incluído` aparece
   no começo do PyInstaller, e a janela de diagnóstico do aplicativo
   instalado mostra "FFmpeg encontrado (…, incluído no FileMorph)".

Os executáveis não são versionados no Git (ver `.gitignore`): são grandes e
dependem da escolha de build de quem empacota.

O FileMorph nunca baixa o FFmpeg sozinho na máquina do usuário.
