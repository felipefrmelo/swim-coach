# P00 — evidências da fundação e dos spikes

- Execução: 2026-08-11, `America/Sao_Paulo`
- Estado da fase: `BLOCKED`
- Regra: resultados reais são identificados como reais; caminhos preparados,
  fixtures e integrações pendentes não são promovidos a evidência de gate.

## Resultado por task

| Task | Estado | Evidência |
|---|---|---|
| P00-T01 | concluída | workspace Python/TypeScript, versões, lockfiles e comandos reproduzíveis |
| P00-T02 | concluída localmente | Compose subiu PostgreSQL, API, worker e web; healthchecks verdes |
| P00-T03 | concluída | limites arquiteturais, health endpoints e encerramento gracioso do worker testados |
| P00-T04 | parcial | MCP real validado pelo Inspector e por sessão Codex local; Secure MCP Tunnel/HTTPS remoto pendente |
| P00-T05 | concluída no modo permitido pela fase | plugin Skills-only instalado e conexão de teste project-scoped exercitada; nenhuma `.app.json` foi inventada |
| P00-T06 | parcial | probe e testes de contrato prontos; tenant Auth0 real não estava configurado no ambiente |
| P00-T07 | parcial | biblioteca real e modelo local de natação de 20 m validados; login/read reais pendentes |
| P00-T08 | parcial | todos os gates locais verdes e workflow criado; primeira execução remota/URL pendente |
| P00-T09 | parcial | versões, limitações e decisão no-go do gate geral registradas neste documento e no handoff |

## Ambiente validado

- Python 3.12.13 via `uv` 0.11.29;
- FastAPI 0.141.1, MCP Python SDK 1.29.0, Pydantic 2.13.4 e pytest 9.1.1;
- Node 24.14.1, pnpm 11.21.0 e Vite 8.2.1;
- Docker 29.7.1 e Docker Compose 5.3.1;
- Codex CLI 0.147.0;
- PostgreSQL 16.10-alpine na imagem fixada pelo Compose;
- `garminconnect[workout]` 0.3.10 no grupo opcional `spike`.

## Checks automatizados reais

Executados a partir da raiz deste pacote:

```text
make check
  ruff format/check: passou
  mypy strict: 16 arquivos passaram
  pytest: 9 passaram
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

Esta evidência fecha a chamada em uma superfície Codex local suportada, mas não
prova ChatGPT web nem transporte remoto. O Secure MCP Tunnel atual exigiria um
`tunnel_id`, API key de runtime e permissões de Platform; nenhum desses inputs
estava presente no ambiente.

## OAuth — compatibilidade e prova pendente

O probe `backend/scripts/probe_oauth_metadata.py` valida somente metadados
públicos e exige:

- issuer HTTPS com correspondência exata;
- authorization code;
- PKCE S256;
- DCR ou CIMD anunciado;
- quando informado, protected resource metadata RFC 9728 com `resource` e issuer
  esperados.

Ele não solicita nem imprime tokens. Não havia variável/configuração de Auth0,
OAuth ou Swim Coach no ambiente; portanto nenhum tenant real foi testado e a
task não está concluída. A documentação atual do Auth0 também informa que DCR
precisa ser explicitamente habilitado no tenant.

Reprodução segura, depois de publicar os metadados:

```bash
uv run python backend/scripts/probe_oauth_metadata.py \
  --issuer 'https://TENANT/' \
  --resource 'https://HOST/mcp' \
  --resource-metadata-url 'https://HOST/.well-known/oauth-protected-resource'
```

## Garmin — compatibilidade e prova pendente

O probe `backend/scripts/probe_garmin_read.py`:

- recebe email, senha e MFA somente por input oculto;
- usa diretório temporário owner-only e o apaga por padrão;
- lê somente atividades recentes e dispositivos;
- emite apenas contagens, booleanos e hash do modelo local;
- constrói localmente um treino de natação de 20 m;
- nunca chama upload/create/update/delete remoto.

O teste automatizado comprovou somente a construção local do modelo. A conta
Garmin real não foi acessada porque credenciais não estavam disponíveis por um
canal local seguro; portanto o read real continua pendente. Execute o comando
abaixo no terminal do proprietário — nunca envie credenciais no prompt:

```bash
uv sync --group spike --frozen
uv run python backend/scripts/probe_garmin_read.py
```

## GitHub/CI — workflow pronto, publicação pendente

O remote configurado é `git@github.com:felipefrmelo/swim-coach.git`.
`git ls-remote --heads origin` respondeu com `refs/heads/main`, comprovando que
o repositório é alcançável por SSH. Uma verificação fora do sandbox confirmou
`gh` autenticado via keyring como `felipefrmelo`, protocolo Git SSH e scope
`repo`; `gh api user --jq .login` também retornou `felipefrmelo`. A verificação
anterior que reportou token inválido refletia o isolamento do sandbox, não o
estado real da máquina. As alterações permanecem locais e não commitadas porque
nenhuma autorização para commit/push/PR foi inferida. Portanto o workflow existe em
`.github/workflows/ci.yml`, mas ainda não há run ou URL remota que satisfaça o
gate.

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

**BLOCKED / NO-GO para marcar P00 como `DONE`.** A fundação e todas as partes independentes
estão prontas, mas o critério da fase exige evidência externa real de OAuth,
Garmin read, Secure MCP Tunnel/HTTPS remoto e CI remota. Fixtures, testes de
contrato e compatibilidade documental não substituem essas provas. Três auditorias
consecutivas encontraram os mesmos inputs externos ausentes; não há trabalho
independente restante dentro da P00 que possa produzir essas evidências.
