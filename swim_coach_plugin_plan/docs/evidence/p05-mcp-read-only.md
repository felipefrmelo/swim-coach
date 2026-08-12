# P05 — evidência do MCP autenticado somente leitura

Estado: implementação local concluída; Inspector/host real e dados Garmin reais pendentes.

Publicação: commit [`ec86e8c`](https://github.com/felipefrmelo/swim-coach/commit/ec86e8c6d4fe44ff6a382ba3b78ffa0ebddc0504),
[draft PR #7](https://github.com/felipefrmelo/swim-coach/pull/7) empilhado sobre
`p03-fit-normalization-analytics` e GitHub Actions
[run 31601391000](https://github.com/felipefrmelo/swim-coach/actions/runs/31601391000)
com `quality` aprovado em 1m46s.

## Escopo comprovado

- P05-T01: resource metadata anuncia os seis scopes read-only; JWT RS256 valida
  discovery, JWKS com cache/rotação, issuer, audience/resource, `exp`, `nbf`,
  `iat`, tipo, subject e scopes; falhas registram somente a classe sanitizada;
- P05-T02: principal deriva exclusivamente do access token, subject resolve uma
  identidade OIDC existente e ativa, request ID é limitado/normalizado, erros têm
  código estável e todas as respostas usam envelope `1.0` headless;
- P05-T03: `get_capabilities`, `get_training_context`, `get_today_workout`,
  `get_week_plan`, `list_recent_swims`, `get_swim_activity`, `get_goal_progress`
  e `get_sync_status` foram registrados; nenhuma tool de write/sync/proposal existe;
- P05-T04: DTOs omitem e-mail, IDs Garmin, token, FIT, checksum de entrada e chave
  de storage; textos importados são normalizados/truncados, lista limita 1–20,
  intervalos 1–100 e lengths 100;
- P05-T05: migration `000006` persiste somente tool, usuário interno, request ID,
  SHA-256 dos argumentos, outcome, latência e código sanitizado;
- P05-T06: schemas fechados (`additionalProperties=false`), annotations read-only
  e inputs são comparados automaticamente com `contracts/mcp-tools.yaml`;
- P05-T07: cliente MCP Streamable HTTP automatizado cobriu oito tools, auth ausente,
  scope insuficiente, subject não vinculado, IDOR, input extra, empty/partial e
  structured content. A execução pelo aplicativo MCP Inspector ainda está pendente;
- P05-T09: reads usam somente PostgreSQL local. Lista com analysis executa duas
  queries fixas; plano semanal executa no máximo cinco; amostra de 30 reads exige
  p95 local abaixo de 500 ms e passou.

## Provas executadas

- `make check` → Ruff, mypy em 85 arquivos, ESLint, TypeScript, 91 testes Python,
  2 Vitest e validadores do repositório/plano verdes;
- PostgreSQL/Testcontainers → migration `000006` em `up/down/up`, auth/scopes/IDOR,
  fixture FIT normalizada, paginação, schemas, telemetria por hash e contagens de
  atividade/treino idênticas antes/depois das calls;
- testes JWT → token válido aceito e audience expirada/discovery hostil rejeitados;
  o bearer completo nunca entra no `AccessToken` resolvido nem no log;
- metadata sem OAuth → 404 e superfície reduzida ao P00 inofensivo; metadata com
  OAuth → issuer/resource canônicos e somente scopes read-only;
- challenge sem bearer → HTTP 401 com `WWW-Authenticate` apontando para protected
  resource metadata.
- `make dependency-scan` → nenhuma vulnerabilidade conhecida em Python/pnpm;
- `make secret-scan` → 16 commits e worktree sem vazamentos;
- Compose rebuild/up → API, worker, web e PostgreSQL saudáveis; migration `000006`
  aplicada. Como OAuth não está injetado no stack atual, metadata retorna 404 e a
  superfície runtime permanece corretamente reduzida ao P00 inofensivo.

## Transcript sanitizado por fixture

Fluxo equivalente a “como foi minha última natação?”:

1. `list_recent_swims(limit=1)` retornou uma atividade sintética de 120 m;
2. `get_swim_activity(activity_id=<uuid-sintético>)` retornou normalização,
   qualidade, métricas e intervalos estruturados;
3. o resultado não contém `external_activity_id`, FIT, `storage_key`,
   `input_checksum`, e-mail ou token;
4. a tentativa de usar o UUID de outro usuário retornou `RESOURCE_NOT_FOUND`.

Isso é evidência de integração local por fixture, não substitui a consulta a uma
atividade Garmin real no ChatGPT/Codex.

## Fonte oficial revalidada

A implementação segue a
[documentação oficial OpenAI de autenticação de plugins MCP](https://developers.openai.com/plugins/build/auth),
revalidada em 2026-08-12: OAuth 2.1, protected resource metadata, Authorization
Code + PKCE S256 e validação do access token em toda requisição.

## Limite honesto

P05 permanece `IN_PROGRESS`. P05-T08 e a parte manual de P05-T07 exigem um access
token real do Auth0 emitido para o resource correto e a conexão do host/Inspector.
Além disso, a pergunta com natação real depende do gate persistente P02 e da
atividade real normalizada do P03. Até essas provas, fixture e testes não contam
como gate de host real.
