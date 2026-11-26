# Rodando o KJCortes numa VPS

Este guia sobe o painel numa VPS com Docker, HTTPS no seu domínio e senha.

## 1. Escolha a VPS

| Caso | O que contratar | Transcrição |
| --- | --- | --- |
| Mais barato | VPS comum, 4 vCPU e 8 GB de RAM, Ubuntu 24.04, 80 GB+ de disco | `provedor: api` (Groq ou OpenAI) |
| Tudo local | Servidor com GPU NVIDIA (8 GB+ de VRAM) | `provedor: local` com `Dockerfile.gpu` |

O corte e a renderização com FFmpeg rodam bem na CPU. O que pesa é a transcrição, por isso numa VPS sem GPU vale usar a API: a Groq cobra centavos de dólar por hora de áudio e é bem mais rápida que a CPU.

Reserve espaço em disco: cada hora de live em 1080p ocupa de 1 a 3 GB em `cache/`. Apague as pastas antigas de `cache/` de vez em quando.

## 2. Aponte o domínio

No painel de DNS do seu domínio, crie um registro **A** (por exemplo `cortes.seudominio.com.br`) com o IP da VPS. O HTTPS só funciona depois que o DNS propagar, o que costuma levar alguns minutos.

## 3. Instale

Conecte na VPS por SSH e rode:

```bash
git clone https://github.com/Antonio-Elvis-Dev/KJCortes.git
cd KJCortes
sudo bash scripts/instalar_vps.sh
```

## 4. Configure

Edite o `.env` (`nano .env`):

```
KJCORTES_SENHA=uma-senha-forte
DOMINIO=cortes.seudominio.com.br
KJCORTES_URL_PAINEL=https://cortes.seudominio.com.br
TRANSCRICAO_API_KEY=sua-chave-da-groq
```

No `config.yaml`, para transcrever pela API:

```yaml
transcricao:
  provedor: api
  api_url: https://api.groq.com/openai/v1
  api_modelo: whisper-large-v3-turbo
```

## 5. Suba

```bash
docker compose --profile https up -d --build
```

Abra `https://cortes.seudominio.com.br` e entre com qualquer usuário e a senha do `.env`.

Para atualizar depois de um novo merge:

```bash
git pull
docker compose --profile https up -d --build
```

## 6. Leve seus dados do PC (opcional)

Copie as pastas `dados/` (streamers, autorizações, cortes e contas) e, se quiser, `saida/` do seu PC para a pasta do projeto na VPS, por exemplo com `scp -r dados usuario@ip-da-vps:~/KJCortes/`. Depois rode `sudo chown -R 1000:1000 dados saida` na VPS.

Os caminhos dos cortes antigos ficam gravados com o caminho do PC, então os vídeos antigos não abrem no painel da VPS. Os cortes novos funcionam normalmente.

## 7. Contas das redes na VPS

Com o painel em HTTPS, os logins ficam mais simples:

- **YouTube**: no Google Cloud, crie um ID do cliente OAuth do tipo **Aplicativo da Web** e cadastre o URI de redirecionamento `https://cortes.seudominio.com.br/contas/youtube/callback`. Baixe o JSON para `dados/youtube_client_secret.json`.
- **TikTok**: cadastre `https://cortes.seudominio.com.br/contas/tiktok/callback` como redirect URI no app.
- **Instagram**: continua colando o token na página Contas.

## 8. Backup

Tudo o que importa está em `dados/`. Um backup diário simples, com cron:

```bash
crontab -e
# adicione a linha:
0 4 * * * tar czf ~/backup-kjcortes-$(date +\%F).tgz -C ~/KJCortes dados
```

## Problemas comuns

- **O HTTPS não sobe**: confira se o DNS já aponta para a VPS e se as portas 80 e 443 estão liberadas no firewall do provedor. Veja `docker compose logs caddy`.
- **"Permission denied" em dados/**: rode `sudo chown -R 1000:1000 dados cache saida`.
- **Painel pede senha e não aceita**: a senha é a do `KJCORTES_SENHA` no `.env`; o usuário pode ser qualquer um. Depois de mudar o `.env`, rode `docker compose up -d` de novo.
