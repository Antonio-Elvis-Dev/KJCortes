# KJCortes

Gera cortes verticais (9:16), legendados e prontos para TikTok, Reels e Shorts a partir de lives e vídeos de streamers no YouTube e na Twitch. Cada corte sai com o crédito do streamer e o link do momento original, para ser postado apenas com autorização do criador.

Esta é a **etapa 1** do projeto: o motor de cortes, que roda no seu computador. O painel de revisão e a postagem automática vêm nas próximas etapas.

## Como funciona

1. **Download**: baixa o vídeo em até 1080p com o `yt-dlp` e, se for uma live gravada, o chat com o `chat-downloader`.
2. **Transcrição**: o `faster-whisper` transcreve o áudio palavra por palavra, usando a GPU NVIDIA quando existir.
3. **Escolha dos trechos**: o vídeo é dividido em janelas de 20 a 60 s que começam e terminam no fim de frases. Cada janela recebe uma nota que soma:
   - picos de volume (gritos, risadas, explosões);
   - picos de mensagens no chat (com alguns segundos de atraso, que é quando o chat reage);
   - quantidade de fala;
   - opcionalmente, uma nota de 0 a 10 dada pela IA (Claude) lendo a transcrição, que também sugere um título.
   
   Os melhores trechos são escolhidos sem sobreposição e com distância mínima entre eles.
4. **Edição**: o FFmpeg corta o trecho, monta o vídeo vertical (o vídeo inteiro sobre um fundo desfocado, ou um recorte central), normaliza o volume para o padrão das redes e grava a legenda com a palavra falada em destaque. Usa NVENC na GPU quando disponível.

## Instalação

Pré-requisitos:

- Python 3.10 ou mais novo
- [FFmpeg](https://ffmpeg.org/download.html) no PATH (`ffmpeg -version` precisa funcionar)
- Para usar a GPU: driver NVIDIA atualizado, mais CUDA 12 e cuDNN 9 (veja os requisitos do [faster-whisper](https://github.com/SYSTRAN/faster-whisper#gpu)). Sem isso, tudo roda na CPU, só que mais devagar.
- Recomendado: instalar a fonte [Montserrat](https://fonts.google.com/specimen/Montserrat) (a legenda usa a ExtraBold).

```bash
git clone https://github.com/Antonio-Elvis-Dev/KJCortes.git
cd KJCortes
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[chat,ia]"
cp config.example.yaml config.yaml   # opcional, para ajustar as opções
```

Na primeira execução o modelo do Whisper é baixado (cerca de 3 GB para o `large-v3`).

## Uso

```bash
# 5 cortes de um vídeo do YouTube ou VOD da Twitch
kjcortes cortar "https://www.twitch.tv/videos/123456789"

# 3 cortes, com a IA avaliando os trechos e sugerindo títulos
export ANTHROPIC_API_KEY=...          # Windows: set ANTHROPIC_API_KEY=...
kjcortes cortar "https://www.youtube.com/watch?v=XXXX" -n 3 --ia

# Vídeo que já está no disco, informando o nome do streamer para o crédito
kjcortes cortar live.mp4 --canal "NomeDoStreamer"

# Teste rápido com um modelo menor
kjcortes cortar "<link>" --modelo small
```

Outras opções: `--layout centro`, `--sem-chat`, `--sem-legenda`, `-v` (mais detalhes) e `kjcortes cortar --help`.

## O que sai

Em `saida/<plataforma>_<id>/`:

- `corte_01.mp4`, `corte_02.mp4`...: vídeos 1080x1920, 30 fps, H.264 + AAC;
- `corte_01.json`...: início e fim no vídeo original, nota de cada sinal, título sugerido, transcrição, **texto de crédito** e link do momento original (com `?t=`);
- `corte_01.ass`...: a legenda, caso queira editá-la e renderizar de novo;
- `resumo.json`: tudo junto.

Downloads, áudio, transcrição e chat ficam em `cache/`, então rodar de novo no mesmo vídeo (por exemplo, mudando o número de cortes ou o layout) é rápido.

## Configuração

Todas as opções estão comentadas em [`config.example.yaml`](config.example.yaml): modelo e idioma do Whisper, quantidade e duração dos cortes, peso de cada sinal na nota, layout, encoder e estilo da legenda.

## Testes

```bash
pip install -e ".[dev]"
pytest
```

O teste de ponta a ponta gera um vídeo sintético e roda o fluxo inteiro (sem baixar nada nem carregar o Whisper).

## Próximas etapas

2. Cadastro dos streamers autorizados (com prova da autorização e @ de cada rede) e painel para revisar os cortes.
3. Postagem automática no TikTok, Instagram Reels e YouTube Shorts, com crédito e menção.
4. Docker e fila de tarefas para rodar em uma VPS.
