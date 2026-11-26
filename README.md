# KJCortes

Gera cortes verticais (9:16), legendados e prontos para TikTok, Reels e Shorts a partir de lives e vídeos de streamers no YouTube e na Twitch. Cada corte sai com o crédito do streamer e o link do momento original, para ser postado apenas com autorização do criador.

O projeto tem duas partes prontas: o **motor de cortes** (linha de comando) e o **painel web**, onde você cadastra os streamers e as autorizações, envia vídeos e revisa cada corte antes de postar. A postagem automática vem na próxima etapa.

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

## Painel

```bash
kjcortes painel
```

Abra http://localhost:8000 no navegador. No painel:

1. **Streamers**: cadastre o nome, os canais da Twitch e do YouTube e o @ de cada rede (TikTok, Instagram, YouTube). Em seguida registre a **autorização** (tipo, data, validade opcional) e anexe a prova: print da conversa, PDF do contrato etc.
2. **Início**: escolha o streamer, cole o link do vídeo e clique em *Gerar cortes*. Os vídeos são processados um por vez, em segundo plano.
3. **Revisar cortes**: assista cada corte, ajuste o título e as legendas de cada rede (já vêm com o crédito e o @ do streamer) e aprove ou rejeite.

Proteções contra strike:

- Só streamers **ativos** e com **autorização vigente** (não revogada e dentro da validade) aparecem para envio.
- Antes de baixar, o sistema confere se o vídeo é de um **canal cadastrado** daquele streamer. Se for de outro canal, o vídeo é recusado e o motivo aparece na tela.
- Revogar uma autorização bloqueia na hora novos vídeos daquele streamer.

O banco de dados e as provas ficam na pasta `dados/`. Faça backup dela.

O painel só aceita conexões deste computador. Para abrir para a rede (por exemplo, na VPS), use `kjcortes painel --host 0.0.0.0` e defina uma senha com a variável `KJCORTES_SENHA`.

## O que sai do motor de cortes

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

3. Postagem automática no TikTok, Instagram Reels e YouTube Shorts, com crédito e menção.
4. Docker e fila de tarefas para rodar em uma VPS.
