# Status de implementação

> Atualizar este arquivo no mesmo commit de cada fase. `DONE` exige evidência. Uma fase pode ficar `BLOCKED` sem comprometer a honestidade do projeto.
> Não existe código legado, banco anterior ou dado de aplicação. A P00 foi
> concluída com evidências locais e integrações externas reais. A P01 concluiu a
> fundação transacional e a PWA autenticada; P02 segue em validação real e P04
> foi concluída em paralelo sobre a cadeia linear de migrations.

| Fase | Estado | Dependências | Evidência mínima | Commit/PR |
|---:|---|---|---|---|
| P00 | DONE | — | Garmin read, OAuth resource binding, tunnel/ChatGPT e CI reais | [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1) |
| P01 | DONE | P00 | migrações + testes de domínio + PWA shell | [PR #2](https://github.com/felipefrmelo/swim-coach/pull/2) |
| P02 | IN_PROGRESS | P01 | import real Garmin sem duplicata | [draft PR #3](https://github.com/felipefrmelo/swim-coach/pull/3) |
| P03 | NOT_STARTED | P02 | FIT normalizado e analytics reproduzíveis | — |
| P04 | DONE | P01 | treino válido de 20 m criado/revisado/agendado na PWA | [draft PR #4](https://github.com/felipefrmelo/swim-coach/pull/4) |
| P05 | NOT_STARTED | P03,P04 | MCP read-only autenticado com dados reais | — |
| P06 | NOT_STARTED | P05 | plugin/Skills instalados e evals aprovadas | — |
| P07 | IN_PROGRESS | P04 | publicação Garmin pela PWA com aprovação | branch `p07-garmin-write-pwa` |
| P08 | NOT_STARTED | P06,P07 | escrita MCP com scopes/hash/auditoria | — |
| P09 | NOT_STARTED | P08 | UI MCP opcional e fallback headless | — |
| P10 | NOT_STARTED | P03,P04,P08 | semana adaptativa explicável | — |
| P11 | NOT_STARTED | P10 | automações recuperáveis e PWA offline | — |
| P12 | NOT_STARTED | P11 | restore testado e release pessoal | — |

## Evidências por fase

### P00

- Estado: `DONE`
- Início: 2026-08-11T09:26:48-03:00
- Bloqueio confirmado: 2026-08-11T10:32:43-03:00
- Bloqueio reduzido ao resource metadata OAuth: 2026-08-11T17:25:51-03:00
- Conclusão: 2026-08-11T17:37:38-03:00
- Commit/PR: [`2faaf62`](https://github.com/felipefrmelo/swim-coach/commit/2faaf62962501f464e2efb419127d6b4fd088512) / [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1)
- Comandos executados:
  - `make check` → Ruff, mypy, 21 testes backend, ESLint, TypeScript, 1 teste frontend e validadores verdes.
  - `make dependency-scan` → nenhuma vulnerabilidade conhecida após atualizar `pytest` para 9.1.1.
  - `make secret-scan` → histórico e árvore de trabalho sem vazamentos.
  - `docker compose build` e `docker compose up -d --wait` → API, worker, PostgreSQL e web saudáveis.
  - `docker compose down -v` → stack e volume vazio descartável removidos após o smoke test.
  - MCP Inspector `tools/list` e `tools/call get_capabilities` → schema estruturado e `isError=false`.
  - sessão `codex exec` efêmera/read-only → MCP `swim_coach_p00.get_capabilities` descoberto e chamado com sucesso.
  - `codex plugin add swim-coach@personal` → `0.0.0-spike` instalado e habilitado.
  - `probe_garmin_read.py` → login/read reais; 20 atividades, 6 nados em piscina e Forerunner 265 detectado; nenhuma escrita externa.
  - `tunnel-client doctor --profile swim-coach-p00 --explain` → perfil, tunnel, chave por variável de ambiente e MCP local aprovados.
  - ChatGPT web via Secure MCP Tunnel → `@coach` chamou o plugin e descreveu corretamente a superfície P00 com somente `get_capabilities`.
  - `probe_oauth_metadata.py` contra tenant Auth0 real → authorization code, PKCE S256 e DCR anunciados; nenhum token solicitado.
  - rebuild do Compose com a nova rota → stack saudável; metadata sem configuração respondeu 404, confirmando fail-closed.
  - rebuild com issuer Auth0 real e resource loopback → metadata path-aware retornou o vínculo esperado em `/mcp`.
  - rerun OAuth-focused do `tunnel-client doctor` com chave fictícia e control plane loopback → `oauth_metadata PASS`, HTTP 200 no metadata path-aware; a prova real do control plane/tunnel permanece o doctor e a chamada ChatGPT anteriores.
  - probe OAuth completo em modo loopback explícito → `oauth_probe=passed` e `resource_binding=true`, sem obter token.
  - `gh auth status`, `gh api user` e `git ls-remote` fora do sandbox → conta `felipefrmelo` autenticada via keyring e remote SSH acessível.
  - [GitHub Actions run `31515474864`](https://github.com/felipefrmelo/swim-coach/actions/runs/31515474864) → job `quality` verde em 1m05s.
- Evidências de integração:
  - [`docs/evidence/p00-foundation-evidence.md`](docs/evidence/p00-foundation-evidence.md)
  - [`docs/handoffs/p00.md`](docs/handoffs/p00.md)
- Decisões/ADRs:
  - ADRs existentes preservados; nenhuma divergência arquitetural encontrada.
  - Plugin P00 permanece com apenas `get_capabilities`; nenhum dado privado nem efeito externo foi liberado.
  - Secure MCP Tunnel de desenvolvimento comprovou o transporte remoto, sem substituir a URL HTTPS estável de produção.
- Pendências da P00: nenhuma.
- Limite preservado: emissão e validação de access token user-scoped pertencem à
  P05, antes de qualquer tool com dados privados.
- Próxima ação: iniciar P01 pelo prompt `prompts/p01.md`.

### P01

- Estado: `DONE`
- Início: 2026-08-11T19:35:41-03:00
- Conclusão local: 2026-08-11T20:10:22-03:00
- Commit/PR: [`2e1e722`](https://github.com/felipefrmelo/swim-coach/commit/2e1e72274fe08137911959208e7b6c4ed22523ea) / [PR #2](https://github.com/felipefrmelo/swim-coach/pull/2)
- Comandos executados:
  - `make check` → Ruff, mypy (50 arquivos), 39 testes Python, ESLint,
    TypeScript, 2 testes Vitest e validadores verdes (`checks=8 warnings=0 errors=0`).
  - `make dependency-scan` → nenhuma vulnerabilidade conhecida em Python ou pnpm.
  - `make secret-scan` → nenhum vazamento nos 5 commits ou na árvore de trabalho.
  - `docker compose up --build -d` → migration one-shot aplicada; PostgreSQL,
    API e PWA saudáveis; worker em execução.
  - migration `000001 (head)` → 16 tabelas e 55 constraints no schema local;
    Testcontainers comprovou `up/down/up`.
  - seed sanitizado executado duas vezes → 20 m, 2.000 m, 2.700 s e
    135 s/100 m nas duas execuções.
  - Playwright em Chrome, viewport 375×812 → login local, perfil, piscina,
    disponibilidade, meta e dashboard passaram em 2,3 s.
  - smokes loopback → live `ok`, ready com banco `ready`, auth config
    explicitamente `oidc_enabled=false/dev_auth_enabled=true` no ambiente local.
  - [GitHub Actions run `31546007309`](https://github.com/felipefrmelo/swim-coach/actions/runs/31546007309)
    → job `quality` verde em 1m34s no commit `2e1e722`.
- Evidências:
  - [`docs/evidence/p01-domain-persistence-identity.md`](docs/evidence/p01-domain-persistence-identity.md)
  - [`docs/evidence/p01-pwa-dashboard.png`](docs/evidence/p01-pwa-dashboard.png)
  - [`docs/handoffs/p01.md`](docs/handoffs/p01.md)
- Decisões/ADRs:
  - [`ADR-0010`](adrs/ADR-0010-pwa-bff-session.md): BFF OIDC e sessão opaca.
  - Email usa índice funcional único em `lower(email)` para preservar unicidade
    case-insensitive sem exigir extensão global `citext`.
- Limites preservados: o E2E usa principal local sanitizado; o fluxo OIDC é
  coberto por contrato criptográfico, não promovido como login Auth0 real. Garmin,
  FIT, workout editor e MCP privado continuam fora do escopo.
- Pendências da P01: nenhuma bloqueadora.
- Dependência de merge: PR #2 está corretamente baseado na branch do PR #1 e
  mostra somente o commit P01; fazer merge do PR #1 antes do PR #2.
- Próxima ação: após os merges, iniciar P02 pelo prompt `prompts/p02.md`.

### P02

- Estado: `IN_PROGRESS`
- Início: 2026-08-11T20:41:41-03:00
- Commit/PR: [`3319aa7`](https://github.com/felipefrmelo/swim-coach/commit/3319aa7) / [draft PR #3](https://github.com/felipefrmelo/swim-coach/pull/3)
- Implementação local: P02-T01 até P02-T07 concluídas; P02-T08 aguarda smoke
  persistente com credenciais reais e replay.
- Evidências:
  - [`docs/evidence/p02-garmin-read-sync.md`](docs/evidence/p02-garmin-read-sync.md)
  - `make check` → 49 testes Python, 2 Vitest, Ruff, mypy, ESLint,
    TypeScript e validadores passaram.
  - integração PostgreSQL/Testcontainers → migration `000002`, AEAD persistido,
    paginação/replay, disconnect e worker retry/rate-limit passaram.
  - TypeScript, ESLint, 2 Vitest e build Vite passaram para a PWA Garmin.
  - Playwright/Chrome 375×812 → dois fluxos passaram; screenshot P02 sanitizado.
  - [GitHub Actions run `31549934953`](https://github.com/felipefrmelo/swim-coach/actions/runs/31549934953)
    → quality verde em 1m32s, incluindo build das imagens.
  - probe Garmin real anterior → 20 atividades, 6 pool swims e 2 devices sem
    escrita externa; ainda não conta como gate persistente P02.
- Próxima ação exata: configurar a chave mestra somente no ambiente local,
  executar CLI `connect`, rodar `sync-once` duas vezes e anexar somente contagens
  sanitizadas comprovando `created=0` no replay.

### P03

- Estado: `NOT_STARTED`
- Evidências:

### P04

- Estado: `DONE`
- Início: 2026-08-11T21:25:00-03:00
- Conclusão local: 2026-08-11T21:49:43-03:00
- Commit/PR: [`82e9e77`](https://github.com/felipefrmelo/swim-coach/commit/82e9e77184df4c0a57a6e5125737a022d46b9b59) / [draft PR #4](https://github.com/felipefrmelo/swim-coach/pull/4)
- Implementação: P04-T01 até P04-T09 concluídas.
- Evidências:
  - [`docs/evidence/p04-workout-authoring-pwa.md`](docs/evidence/p04-workout-authoring-pwa.md)
  - [`docs/evidence/p04-workout-editor-mobile.png`](docs/evidence/p04-workout-editor-mobile.png)
  - [`docs/handoffs/p04.md`](docs/handoffs/p04.md)
  - `make check` → 60 testes Python, 2 Vitest, Ruff, mypy, ESLint,
    TypeScript e validadores verdes.
  - Testcontainers → migration `000003` e trigger de revisão imutável em
    `up/down/up`.
  - Playwright Chrome 375×812 → quatro fluxos P01/P02/P04 passaram.
  - `make dependency-scan` e `make secret-scan` → limpos.
  - [GitHub Actions run `31551697015`](https://github.com/felipefrmelo/swim-coach/actions/runs/31551697015)
    → job `quality` verde em 1m29s no draft PR #4.
- Limite preservado: aprovação e agenda são somente locais; não há dependência,
  compilação, chamada ou efeito Garmin no contexto P04.

### P05

- Estado: `NOT_STARTED`
- Evidências:

### P06

- Estado: `NOT_STARTED`
- Evidências:

### P07

- Estado: `IN_PROGRESS`
- Início: 2026-08-11T22:01:00-03:00
- Escopo atual: P07-T01..T09 em implementação com provider fake e write real
  fechado por feature flag; o gate externo continuará pendente até canário real.
- Implementação local: P07-T01..T09 concluídas; gate real ainda aberto.
- Evidências:
  - [`docs/evidence/p07-garmin-write-pwa.md`](docs/evidence/p07-garmin-write-pwa.md)
  - [`docs/evidence/p07-garmin-publish-mobile.png`](docs/evidence/p07-garmin-publish-mobile.png)
  - [`docs/handoffs/p07.md`](docs/handoffs/p07.md)
  - 50 testes unitários e 14 integrações PostgreSQL verdes.
  - Playwright Chrome 375×812 → proposta, aprovação, publish/schedule fake e sucesso.
  - Resultado ambíguo reconciliado sem duplicar; IDs fake estáveis entre restarts.
  - `make check` → 75 testes Python, 2 Vitest, Ruff, mypy, TypeScript,
    ESLint e validadores verdes; build Vite aprovado.
  - dependency scan e secret scan (12 commits + árvore) sem achados.
- Limite: nenhuma escrita externa real; `IN_PROGRESS` até treino descartável real
  publicado/agendado uma vez e replay confirmado sem duplicata.

### P08

- Estado: `NOT_STARTED`
- Evidências:

### P09

- Estado: `NOT_STARTED`
- Evidências:

### P10

- Estado: `NOT_STARTED`
- Evidências:

### P11

- Estado: `NOT_STARTED`
- Evidências:

### P12

- Estado: `NOT_STARTED`
- Evidências:
