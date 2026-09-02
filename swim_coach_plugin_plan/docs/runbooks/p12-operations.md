# Runbook pessoal 1.0 — instalar, atualizar, recuperar e responder

## Instalação

1. Copie `.env.example` para um arquivo privado fora do Git e substitua todos os
   valores locais por URLs HTTPS, allowlist e secrets reais do ambiente.
2. Mantenha `SWIM_COACH_DEV_AUTH_ENABLED=false` e os writes Garmin/MCP desligados.
3. Execute `docker compose -f docker-compose.yml -f docker-compose.production.yml
   config` e revise portas, volumes e variáveis resolvidas.
4. Execute `docker compose ... build`, depois somente o serviço `migrate`.
5. Suba API/worker/web, espere `/health/ready`, valide primeiro o backend, MCP e
   plugin, execute `backend/scripts/load_smoke.py` contra o endpoint loopback e
   então valide o painel auxiliar.
6. Termine TLS no Secure MCP Tunnel/ingress gerenciado. O Compose só publica
   loopback e nunca deve ser exposto diretamente na Internet.

## Atualização e rollback

Antes de atualizar, crie um backup criptografado verificado e guarde o hash do
commit/imagem. Pare o worker, aplique a migration one-shot, suba a nova API e o
painel auxiliar e rode os smokes. Se uma verificação falhar, desligue
`GARMIN_WRITE`, `MCP_WRITE` e
`AUTOMATION`, restaure a imagem anterior e faça downgrade da migration apenas
quando o arquivo Alembic declara downgrade seguro. Para perda/corrupção de dados,
não tente downgrade: restaure o último backup verificado em destino isolado.

### Deploy automatizado na VM pessoal

O workflow `Deploy production` roda somente depois do `CI` verde em um push da
`main`, ou por disparo manual da própria `main`. Em ambos os casos o SHA precisa
ser a ponta atual da branch e possuir CI verde. O ambiente GitHub `production`
fornece `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_SSH_PRIVATE_KEY` e
`DEPLOY_SSH_KNOWN_HOSTS`.

A chave SSH é exclusiva do deploy e usa forced command para chamar
`/opt/swim-coach/deploy-main.sh`; ela não libera shell, PTY ou forwarding. O
entrypoint extrai `ops/deploy-vm.sh` do SHA aprovado. O script serializa deploys,
valida espaço, cria e verifica o dump pré-deploy, constrói antes da parada, roda
a migration one-shot e só grava `.deployed-commit` depois dos health checks. Em
falha após a parada, ele tenta restaurar as imagens anteriores sem executar
downgrade automático do banco.

## Backup e restore

Gere uma chave de 32 bytes, codifique em base64 URL-safe e salve em arquivo `0600`
fora do repositório. Exemplo de comandos (URLs e caminhos vêm do secret manager):

```bash
uv run python -m swim_coach.interfaces.cli.backup create \
  --database-url "$DATABASE_URL" --artifacts "$ARTIFACTS" \
  --output "$BACKUPS/swim-coach-$(date +%F).scbk" \
  --key-file "$BACKUP_KEY_FILE" --retain 7

uv run python -m swim_coach.interfaces.cli.backup restore \
  --database-url "$ISOLATED_RESTORE_DATABASE_URL" \
  --artifacts "$EMPTY_RESTORE_ARTIFACTS" \
  --input "$BACKUP_FILE" --key-file "$BACKUP_KEY_FILE"
```

O restore recusa storage não vazio por padrão, autentica o envelope AES-GCM,
valida cada checksum antes do `pg_restore` e nunca segue symlink/path traversal.
Depois, compare `alembic_version`, counts de usuário/identidade/atividade/treino,
resolução de login e checksums de artefatos. Só então declare o backup verificado.

## API ou banco indisponível

Veja `/health/live` e `/health/ready`. Readiness exige banco, migration `000015` e
volume de artefatos gravável. Não reinicie em loop se houver `SCHEMA_MISMATCH`;
execute a migration controlada. Em falha de storage, preserve o volume e corrija
owner/permissões antes de reabrir exports ou FIT.

O downgrade de `000014` para `000013` é bloqueado quando algum feedback já ficou
temporariamente desacoplado da atividade interna após uma exclusão/reimportação. Preserve o
schema atual ou restaure um backup anterior; não apague feedback para forçar o rollback.

Antes de rollback, consulte `activity_normalization` e `activity_analysis`. O downgrade de
`000013` para `000012` é bloqueado quando já existe RPE/sensação Garmin normalizado,
override manual de sensação ou feedback manual sem RPE próprio; o schema anterior não consegue
representar esses fatos sem perda. Reprocesse todos os FITs locais por usuário com
`backend/scripts/reprocess_local_swims.py --user-id UUID` depois do upgrade. O comando usa
somente artifacts imutáveis e não consulta nem escreve na Garmin.

O downgrade de `000012` aceita somente normalizações legadas `swim-coach:1.x`, cujo
`moving_seconds` físico é preservado para a imagem v1. Ele é deliberadamente bloqueado quando existe qualquer fato
canônico v2 ou moving nullable: mantenha a aplicação v2 ou restaure um backup anterior à
migration. A mesma restrição vale para rollback **somente da imagem**: depois do primeiro write
v2, uma imagem v1 pode tentar materializar `Decimal(NULL)` mesmo com o banco ainda em `000012`.
Não suba imagem v1 nesse estado. Não apague normalizações para forçar downgrade.
Reprocessamento local deve usar o artifact FIT já armazenado e o summary raw persistido; nunca
consulta nem altera a Garmin.

## Fila parada

Abra `/operations`, confira idade, estado e código sanitizado. Retry só aparece
para falha terminal classificada como segura, sem efeito externo ambíguo. Nunca
repita cegamente publicação Garmin. Se a idade exceder 300 s, pare automação,
capture correlation/job ID sanitizados e reinicie um único worker.

## Pressão de disco

Acima de 80%, pare imports/exports, confirme que existe backup recente e remova
somente backups além da retenção ou jobs finalizados pela rotina prevista. Não
apague FIT, volume PostgreSQL ou export diretamente. Faça export/delete pela API.

## OAuth Garmin ou plugin

Para OAuth, reexecute o metadata probe e valide issuer/audience/PKCE sem imprimir
token. Para Garmin, respeite `429`, espere o backoff e reconecte pela CLI segura;
senha não entra no painel auxiliar. Para o plugin, confirme o app mapping,
reinstale a versão 3.0.0 e abra uma conversa nova no ChatGPT. Faça o smoke
principal pelo ChatGPT: consulte contexto, natação recente e treinos planejados.
Mantenha writes desligados até o read smoke user-scoped passar; só depois valide
o painel auxiliar e efeitos externos descartáveis.

## Incidente de segurança/privacidade

1. Desligue writes, automação e túnel; preserve logs sanitizados e backups.
2. Revogue sessão/OAuth/Garmin e rotacione somente secrets possivelmente afetados.
3. Determine usuários/objetos pelo audit/correlation ID, sem copiar payload livre.
4. Corrija, execute secret/dependency/image scans e restore drill.
5. Reabra em ordem: health, login, leitura, proposta e por último efeito externo.
