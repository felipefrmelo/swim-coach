# P00 — evidências da fundação e dos spikes

- Execução: 2026-08-11, `America/Sao_Paulo`
- Estado da fase: `BLOCKED`
- Atualização externa: 2026-08-11T17:25:51-03:00
- Regra: resultados reais são identificados como reais; caminhos preparados,
  fixtures e integrações pendentes não são promovidos a evidência de gate.

## Resultado por task

| Task | Estado | Evidência |
|---|---|---|
| P00-T01 | concluída | workspace Python/TypeScript, versões, lockfiles e comandos reproduzíveis |
| P00-T02 | concluída localmente | Compose subiu PostgreSQL, API, worker e web; healthchecks verdes |
| P00-T03 | concluída | limites arquiteturais, health endpoints e encerramento gracioso do worker testados |
| P00-T04 | concluída | MCP validado localmente e por Secure MCP Tunnel em chamada real do ChatGPT web |
| P00-T05 | concluída no modo permitido pela fase | plugin Skills-only instalado e conexão de teste project-scoped exercitada; nenhuma `.app.json` foi inventada |
| P00-T06 | parcial | Auth0 real passou em authorization code, PKCE S256 e DCR; protected resource metadata implementado, mas ainda não revalidado pelo tunnel |
| P00-T07 | concluída | login/read reais: atividades, nados e Forerunner 265 detectados; nenhuma escrita externa |
| P00-T08 | concluída | gates locais verdes e GitHub Actions run `31515474864` verde em clone limpo |
| P00-T09 | parcial | evidências externas registradas; decisão permanece bloqueada somente no resource metadata OAuth |

## Ambiente validado

- Python 3.12.13 via `uv` 0.11.29;
- FastAPI 0.141.1, MCP Python SDK 1.29.0, Pydantic 2.13.4 e pytest 9.1.1;
- Node 24.14.1, pnpm 11.21.0 e Vite 8.2.1;
- Docker 29.7.1 e Docker Compose 5.3.1;
- Codex CLI 0.147.0;
- PostgreSQL 16.10-alpine na imagem fixada pelo Compose;
- `garminconnect[workout]` 0.3.10 no grupo opcional `spikes`.

## Checks automatizados reais

Executados a partir da raiz deste pacote:

```text
make check
  ruff format/check: passou
  mypy strict: 16 arquivos passaram
  pytest inicial: 9 passaram
  pytest após protected resource metadata: 15 passaram
  eslint + TypeScript: passaram
  vitest: 1 passou
  repository validator: passou
  plan validator: checks=8 warnings=0 errors=0

make dependency-scan
  pip-audit: nenhuma vulnerabilidade conhecida
  pnpm audit --audit-level high: nenhuma vulnerabilidade conhecida

make secret-scan
  gitleaks git: nenhum vazamento
  gitleaks dir: nenhum vazamento

docker compose build
  api, worker e web: imagens construídas

docker compose up -d --wait
  postgres: healthy
  api: healthy
  worker: running
  web: healthy

rebuild após protected resource metadata
  api, worker e web: imagens construídas
  postgres, api, worker e web: saudáveis
  metadata sem configuração: HTTP 404 (fail-closed)

docker compose down -v
  contêineres e rede P00 removidos
  volume descartável swim-coach_postgres-data removido
```

O primeiro `docker compose up` encontrou a porta local 5432 ocupada. As portas
do host passaram a ser configuráveis e os defaults do spike foram movidos para
55432 (PostgreSQL), 18000 (API) e 14173 (web). Isso não alterou portas internas.

A primeira auditoria encontrou `PYSEC-2026-1845` no pytest 8.4.2. O lockfile foi
atualizado para pytest 9.1.1 e a auditoria foi repetida com resultado limpo.
Ao final do smoke test, o stack foi desmontado e seu volume descartável apagado;
ele não continha dados reais e só é recuperável recriando o ambiente vazio.

## MCP Inspector — integração local real

Com o stack real em execução:

```bash
npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:18000/mcp/ --transport http --method tools/list

npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:18000/mcp/ --transport http \
  --method tools/call --tool-name get_capabilities
```

Resultado sanitizado:

```json
{
  "tool_count": 1,
  "tool": "get_capabilities",
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": false
  },
  "call": {
    "status": "OK",
    "phase": "P00",
    "available_tools": ["get_capabilities"],
    "private_training_data_enabled": false,
    "garmin_read_enabled": false,
    "garmin_write_enabled": false,
    "custom_ui_enabled": false,
    "isError": false
  }
}
```

O `request_id` aleatório foi omitido. Nenhum dado de atleta, credencial, token ou
identificador Garmin esteve presente.

## Plugin — superfície pessoal real

O plugin foi criado pelo scaffold oficial disponível no Codex, validado e
instalado pelo marketplace pessoal:

```text
python3 scripts/validate_plugin.py /home/felipe/plugins/swim-coach
  Plugin validation passed

codex plugin add swim-coach@personal
  Added plugin `swim-coach` from marketplace `personal`.
  Installed plugin root: .../swim-coach/0.0.0-spike

codex plugin list
  swim-coach@personal  installed, enabled  0.0.0-spike
```

Esta é deliberadamente uma instalação **Skills-only**. Ela prova o empacotamento
e a instalação real, não uma conexão MCP remota. A `.app.json` continuará ausente
até existir um ID de conexão oficial.

## Codex — chamada MCP em superfície suportada real

A documentação oficial atual permite que clientes Codex locais usem servidores
Streamable HTTP e carreguem `.codex/config.toml` project-scoped em projetos
confiáveis. O Git root agora contém somente a seguinte política para este MCP:

```toml
[mcp_servers.swim_coach_p00]
url = "http://127.0.0.1:18000/mcp/"
enabled = true
required = false
enabled_tools = ["get_capabilities"]
default_tools_approval_mode = "auto"
startup_timeout_sec = 10
tool_timeout_sec = 10
```

Com o Compose ativo, `codex mcp get swim_coach_p00` confirmou transporte,
endpoint e allowlist. Em seguida, uma sessão real, efêmera e read-only foi
executada com todos os MCPs globais não relacionados desabilitados:

```text
codex exec --ephemeral --sandbox read-only \
  -c 'mcp_servers.context7.enabled=false' --json <prompt restrito>

mcp_tool_call:
  server: swim_coach_p00
  tool: get_capabilities
  arguments: {}
  status: completed
  error: null

structured_content:
  schema_version: "1.0"
  status: "OK"
  phase: "P00"
  available_tools: ["get_capabilities"]
  private_training_data_enabled: false
  garmin_read_enabled: false
  garmin_write_enabled: false
  custom_ui_enabled: false
```

O identificador aleatório da requisição e o identificador da thread efêmera não
foram preservados. O primeiro ensaio com `--ignore-user-config` não carregou a
configuração do projeto e retornou corretamente “tool não disponível”; o ensaio
final carregou a configuração normal e chamou exatamente um tool. O modo
`--strict-config` não pôde ser usado devido a um campo preexistente de outro
plugin na configuração global, sem relação com o Swim Coach.

## Secure MCP Tunnel — integração remota real

O proprietário criou um tunnel de desenvolvimento na OpenAI Platform, manteve a
runtime API key somente em variável de ambiente local e apontou o perfil
`swim-coach-p00` para `http://127.0.0.1:18000/mcp/`. O identificador do tunnel
foi mascarado nesta evidência.

Resultado sanitizado de `tunnel-client doctor --profile swim-coach-p00 --explain`:

```text
config_source          PASS profile: swim-coach-p00
profile_load           PASS
tunnel_id              PASS tunnel_…8500
control_plane_api_key  PASS env:CONTROL_PLANE_API_KEY
mcp_target             PASS http://127.0.0.1:18000/mcp/
mcp_server_reachable   PASS HTTP 406
oauth_metadata         PASS metadata não anunciado; candidatos retornaram 404
health_listener        PASS http://127.0.0.1:8080
RESULT ok
```

O HTTP 406 é a resposta esperada de uma requisição HTTP genérica sem o contrato
MCP; o próprio `doctor` confirmou que o alvo estava alcançável. O estado OAuth
registrou corretamente a ausência de protected resource metadata antes da nova
rota documentada abaixo.

Com `tunnel-client run` ativo, uma captura apresentada pelo proprietário mostrou
uma chamada real no ChatGPT web usando `@coach`. A resposta identificou o Swim
Coach, informou que a conexão básica estava funcionando, declarou
`get_capabilities` como única função disponível e não alegou acesso Garmin,
dados pessoais ou capacidades futuras. Isso fecha a prova de transporte remoto
P00 sem persistir na evidência qualquer API key ou dado privado.

## OAuth — Auth0 real e resource metadata pendente de revalidação

O probe `backend/scripts/probe_oauth_metadata.py` valida somente metadados
públicos e exige:

- issuer HTTPS com correspondência exata;
- authorization code;
- PKCE S256;
- DCR ou CIMD anunciado;
- quando informado, protected resource metadata RFC 9728 com `resource` e issuer
  esperados.

O proprietário habilitou DCR em um tenant Auth0 de desenvolvimento e executou o
probe contra o issuer real. O hostname do tenant foi omitido desta evidência;
nenhum client secret, access token ou refresh token foi solicitado ou impresso.

Resultado sanitizado real:

```json
{
  "oauth_probe": "passed",
  "issuer_metadata": {
    "authorization_code": true,
    "cimd": false,
    "dcr": true,
    "pkce_s256": true,
    "token_endpoint_auth_methods": [
      "client_secret_basic",
      "client_secret_post",
      "private_key_jwt",
      "none"
    ]
  }
}
```

Esse resultado fecha a compatibilidade do authorization server, mas não o gate
OAuth inteiro: o comando não recebeu `--resource` nem
`--resource-metadata-url`, e o primeiro `tunnel-client doctor` encontrou 404 nos
candidatos de protected resource metadata.

Para eliminar o gap, a API agora implementa
`GET /.well-known/oauth-protected-resource`. A rota fica em 404 quando não
configurada e só anuncia metadados quando
`SWIM_COACH_OAUTH_ISSUER` e `SWIM_COACH_OAUTH_RESOURCE` formam um par HTTPS
completo. Testes cobrem o estado fechado, o documento válido e configurações
parciais/inseguras.

Reprodução final segura, depois de reconstruir a API com o par configurado:

```bash
uv run python backend/scripts/probe_oauth_metadata.py \
  --issuer 'https://TENANT/' \
  --resource 'https://RESOURCE-HTTPS/mcp' \
  --resource-metadata-url 'https://HOST-HTTPS/.well-known/oauth-protected-resource'
```

## Garmin — leitura real concluída

O probe `backend/scripts/probe_garmin_read.py`:

- recebe email, senha e MFA somente por input oculto;
- usa diretório temporário owner-only e o apaga por padrão;
- lê somente atividades recentes e dispositivos;
- emite apenas contagens, booleanos e hash do modelo local;
- constrói localmente um treino de natação de 20 m;
- nunca chama upload/create/update/delete remoto.

O proprietário executou o probe no próprio terminal, fornecendo email, senha e
MFA apenas por input oculto. Os dois primeiros caminhos mobile receberam 429 por
rate limit do IP; o fallback da biblioteca concluiu login e leituras reais. A
saída não contém credencial, token, ID externo, FIT nem detalhe de atividade:

```json
{
  "device_count": 2,
  "external_write_performed": false,
  "garmin_read_probe": "passed",
  "local_swimming_model_sha256": "63980fde38b42d3d8a6857ff6e13b0aafba5ea42a19e8339104f0f1d47a938ba",
  "local_swimming_model_valid": true,
  "recent_activity_count": 20,
  "recent_pool_swim_count": 6,
  "target_device_family_detected": true
}
```

O diretório temporário de tokens foi apagado pelo `finally` padrão do probe. O
modelo de natação de 20 m foi apenas construído localmente; nenhuma chamada de
upload/create/update/delete foi feita.

## GitHub/CI — integração remota real

O remote configurado é `git@github.com:felipefrmelo/swim-coach.git`.
`git ls-remote --heads origin` respondeu com `refs/heads/main`, comprovando que
o repositório é alcançável por SSH. Uma verificação fora do sandbox confirmou
`gh` autenticado via keyring como `felipefrmelo`, protocolo Git SSH e scope
`repo`; `gh api user --jq .login` também retornou `felipefrmelo`. A verificação
anterior que reportou token inválido refletia o isolamento do sandbox, não o
estado real da máquina.

A publicação autorizada produziu:

- commit [`2faaf62`](https://github.com/felipefrmelo/swim-coach/commit/2faaf62962501f464e2efb419127d6b4fd088512);
- [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1), branch
  `p00-foundation-spikes` contra `main`;
- [GitHub Actions run `31515474864`](https://github.com/felipefrmelo/swim-coach/actions/runs/31515474864);
- job `quality` concluído com sucesso em 1m05s: checkout, toolchains,
  dependências locked, checks/testes, dependency scan, secret scan e build dos
  contêineres verdes.

## Fontes primárias consultadas

- OpenAI, conceitos de plugins: <https://developers.openai.com/plugins/concepts/plugins>
- OpenAI, servidor MCP: <https://developers.openai.com/plugins/concepts/mcp-server>
- OpenAI, autenticação: <https://developers.openai.com/plugins/build/auth>
- OpenAI, criação de plugins: <https://developers.openai.com/plugins/build/plugins>
- OpenAI, MCP no Codex: <https://developers.openai.com/codex/mcp/>
- OpenAI, Secure MCP Tunnel: <https://developers.openai.com/api/docs/guides/secure-mcp-tunnels>
- Auth0, Dynamic Client Registration: <https://auth0.com/docs/get-started/applications/dynamic-client-registration>
- MCP Inspector: <https://github.com/modelcontextprotocol/inspector>
- `python-garminconnect`: <https://github.com/cyberjunky/python-garminconnect>

## Decisão de gate

**BLOCKED / NO-GO para marcar P00 como `DONE`.** Garmin read real e Secure MCP
Tunnel/ChatGPT estão concluídos. O Auth0 real também comprovou authorization
code, PKCE S256 e DCR. Falta uma única evidência: reconstruir a API com o par
issuer/resource HTTPS, repetir o `doctor` até o protected resource metadata ser
descoberto e executar o probe completo com resource binding. Depois disso,
P00-T06 e P00-T09 podem ser concluídas e a fase pode avançar para `DONE`.
