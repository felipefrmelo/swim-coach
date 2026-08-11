# P01 — evidências de domínio, persistência e identidade

- Execução: 2026-08-11, `America/Sao_Paulo`
- Estado da fase: `DONE`
- Conclusão local: 2026-08-11T20:10:22-03:00
- Publicação/CI: 2026-08-11T20:21:01-03:00
- Regra: resultados reais locais, fixtures e contratos criptográficos são
  distinguidos; nenhuma integração futura é promovida como pronta.

## Resultado por task

| Task | Estado | Evidência |
|---|---|---|
| P01-T01 | concluída | value objects e erros com unit/property tests, incluindo round-trip Decimal |
| P01-T02 | concluída | entidades e repositories tipados para identidade e contexto do atleta |
| P01-T03 | concluída | meta 2.000 m/2.700 s calcula exatamente 135 s/100 m; seed idempotente |
| P01-T04 | concluída | SQLAlchemy async, Alembic `000001`, 16 tabelas, 55 constraints e Testcontainers |
| P01-T05 | concluída | transaction boundary, outbox/audit/idempotência e lease concorrente com TTL |
| P01-T06 | concluída | BFF OIDC/PKCE, allowlist, sessão opaca, CSRF e logout; dev principal local explícito |
| P01-T07 | concluída | health, `/me`, pools, availability e goals com Problem Details/correlation ID |
| P01-T08 | concluída | PWA mobile-first sem chat, com loading/error/empty/success e configuração inicial |
| P01-T09 | concluída | segundo usuário, ownership em repository/REST e IDOR respondendo 404 |

## Gate automatizado

```text
make check
  ruff format/check: passou (72 arquivos formatados)
  mypy: passou (50 arquivos fonte)
  pytest: 39 passaram
  eslint + TypeScript: passaram
  vitest: 2 passaram
  repository validator: passou
  plan validator: checks=8 warnings=0 errors=0

make dependency-scan
  pip-audit: nenhuma vulnerabilidade conhecida
  pnpm audit --audit-level high: nenhuma vulnerabilidade conhecida

make secret-scan
  gitleaks git: 5 commits, nenhum vazamento
  gitleaks dir: nenhum vazamento

GitHub Actions run 31546007309
  commit: 2e1e72274fe08137911959208e7b6c4ed22523ea
  job quality: passou em 1m34s
```

Os testes Python incluem propriedades dos value objects, contratos OIDC,
migration `up/down/up`, repositories PostgreSQL, autenticação positiva/negativa,
IDOR, idempotência transacional e lease concorrente de job. Após um workaround
localizado no factory para a referência futura do MCP SDK 1.29, a suíte focal
também passou com warnings tratados como erro.

## Persistência real local

`docker compose up --build -d` construiu as quatro imagens P01. O serviço
one-shot `migrate` terminou com sucesso antes da API e do worker; PostgreSQL,
API e web ficaram saudáveis e o worker permaneceu em execução.

Resultado estrutural, sem consulta a linhas de usuário:

```text
alembic current: 000001 (head)
base tables: 16
constraints in public schema: 55

alembic_version, api_idempotency_record, app_user, athlete_constraint,
athlete_profile, audit_event, auth_identity, availability_rule, device,
goal_milestone, job, oidc_login_attempt, outbox_event, pool, training_goal,
web_session
```

O fixture Testcontainers usa PostgreSQL 16.10-alpine descartável, aplica
`upgrade head`, `downgrade base` e novo `upgrade head`. O downgrade não foi
executado no volume local persistente. Email é `text` com índice único
funcional em `lower(email)`, preservando a invariável case-insensitive sem
instalar uma extensão global.

O seed sanitizado foi executado duas vezes contra a stack local e retornou o
mesmo contexto em ambas:

```json
{
  "initial_context_seed": "passed",
  "pool_length_m": 20,
  "target_distance_m": 2000,
  "target_duration_seconds": 2700,
  "target_pace_seconds_per_100m": 135
}
```

## Autenticação e isolamento

- OIDC usa Authorization Code + PKCE S256, state e nonce server-side.
- Discovery exige issuer/endpoints HTTPS exatos; ID token exige RS256, `kid`,
  JWKS, `iss`, `aud`, `exp`, `iat`, `sub`, nonce e email verificado.
- Tokens do IdP não são persistidos; sessão e CSRF entram no banco somente como
  hashes e cookies usam os atributos definidos na ADR-0010.
- Produção rejeita `dev-auth` e base PWA insegura durante o bootstrap.
- Todas as leituras/mutações de contexto recebem `user_id`; IDs de outro usuário
  retornam 404 e não revelam existência.
- Creates de pool/meta exigem `Idempotency-Key`; updates usam versionamento
  otimista e audit/outbox no mesmo commit.

Os testes OIDC são de contrato com chaves RSA e HTTP controlado, não um login
real no tenant Auth0. O E2E usa somente `local-swimmer@example.test`, fixture
explicitamente allowlisted fora de produção. Nenhum email pessoal, token ou
claim sensível foi anexado.

## PWA e smoke real em Chrome

Playwright executou em Google Chrome com viewport 375×812 contra Nginx/API/
PostgreSQL reais locais. O fluxo autenticou o fixture, alterou perfil, criou ou
reutilizou piscina, registrou disponibilidade, salvou a meta e voltou ao
dashboard. Resultado: `1 passed (2.3s)`.

Captura sanitizada: [dashboard mobile](p01-pwa-dashboard.png).

Os smokes loopback retornaram:

```json
{"status":"ok","service":"swim-coach-api"}
{"status":"ready","checks":{"application":"ready","database":"ready"}}
{"oidc_enabled":false,"dev_auth_enabled":true}
```

O terceiro payload comprova que o ambiente E2E não fingiu OIDC externo. A PWA
declara manifest/icon, navegação em thumb zone e estados honestos; workout
editor/calendário permanecem explicitamente reservados para P04.

## Limites e próxima fase

- nenhuma leitura/escrita Garmin foi executada na P01;
- nenhuma tool MCP privada foi liberada; `get_capabilities` continua sendo a
  única superfície pública e inofensiva;
- nenhum dado real do atleta foi necessário para o gate;
- login Auth0 end-to-end de usuário não foi alegado; a implementação OIDC está
  pronta para receber issuer/client/secret por canal seguro;
- P02 pode iniciar a importação Garmin real e idempotente sem alterar a base de
  identidade/contexto entregue aqui.

## Publicação

- Implementação: commit [`2e1e722`](https://github.com/felipefrmelo/swim-coach/commit/2e1e72274fe08137911959208e7b6c4ed22523ea).
- Revisão: [PR #2](https://github.com/felipefrmelo/swim-coach/pull/2).
- CI: [run `31546007309`](https://github.com/felipefrmelo/swim-coach/actions/runs/31546007309),
  `quality=success` em clone limpo.
- O PR #2 está empilhado sobre `p00-foundation-spikes` para que seu diff contenha
  somente P01. O PR #1 deve ser integrado antes do PR #2.
