# Status de implementação

> Atualizar este arquivo no mesmo commit de cada fase. `DONE` exige evidência. Uma fase pode ficar `BLOCKED` sem comprometer a honestidade do projeto.
> Não existe código legado, banco anterior ou dado de aplicação. A P00 foi
> concluída com evidências locais e integrações externas reais. A P01 concluiu a
> fundação transacional e a PWA autenticada; P02 segue em validação real e P04
> foi concluída em paralelo sobre a cadeia linear de migrations. A implementação
> P03 está completa por fixture e integração PostgreSQL, mas aguarda a atividade
> real persistida pelo gate P02 para comparação manual com a Garmin.

| Fase | Estado | Dependências | Evidência mínima | Commit/PR |
|---:|---|---|---|---|
| P00 | DONE | — | Garmin read, OAuth resource binding, tunnel/ChatGPT e CI reais | [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1) |
| P01 | DONE | P00 | migrações + testes de domínio + PWA shell | [PR #2](https://github.com/felipefrmelo/swim-coach/pull/2) |
| P02 | IN_PROGRESS | P01 | import real Garmin sem duplicata | [draft PR #3](https://github.com/felipefrmelo/swim-coach/pull/3) |
| P03 | IN_PROGRESS | P02 | FIT normalizado e analytics reproduzíveis | [draft PR #6](https://github.com/felipefrmelo/swim-coach/pull/6) |
| P04 | DONE | P01 | treino válido de 20 m criado/revisado/agendado na PWA | [draft PR #4](https://github.com/felipefrmelo/swim-coach/pull/4) |
| P05 | IN_PROGRESS | P03,P04 | MCP read-only autenticado com dados reais | [draft PR #7](https://github.com/felipefrmelo/swim-coach/pull/7) |
| P06 | IN_PROGRESS | P05 | plugin/Skills instalados e evals aprovadas | branch `p06-plugin-read-only` |
| P07 | IN_PROGRESS | P04 | publicação Garmin pela PWA com aprovação | [draft PR #5](https://github.com/felipefrmelo/swim-coach/pull/5) |
| P08 | IN_PROGRESS | P06,P07 | escrita MCP com scopes/hash/auditoria | [draft PR #9](https://github.com/felipefrmelo/swim-coach/pull/9) |
| P09 | IN_PROGRESS | P08 | UI MCP opcional e fallback headless | [draft PR #10](https://github.com/felipefrmelo/swim-coach/pull/10) |
| P10 | IN_PROGRESS | P03,P04,P08 | semana adaptativa explicável | [draft PR #11](https://github.com/felipefrmelo/swim-coach/pull/11) |
| P11 | IN_PROGRESS | P10 | automações recuperáveis e PWA offline | [draft PR #12](https://github.com/felipefrmelo/swim-coach/pull/12) |
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

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T08:15:00-03:00
- Implementação local: P03-T01 até P03-T09 concluídas; gate por fixture aprovado.
- Evidências:
  - [`docs/evidence/p03-fit-normalization-analytics.md`](docs/evidence/p03-fit-normalization-analytics.md)
  - [`docs/handoffs/p03.md`](docs/handoffs/p03.md)
  - FIT sintético binário gerado e decodificado pelo SDK oficial Garmin, com CRC.
  - golden sanitizado de piscina 20 m e property tests de métricas/unidades.
  - PostgreSQL/Testcontainers → migration `000005` em `up/down/up`, replay
    idempotente, feedback versionado e ownership seguro.
  - `make check` → 87 testes Python, 2 Vitest, Ruff, mypy, ESLint, TypeScript e
    validadores verdes; dependency/secret scans sem achados.
  - REST público prova ausência de FIT, storage key e input checksum.
  - PWA mobile-first mostra qualidade antes da interpretação e feedback sem
    inferência médica; 6 E2Es Chrome 375×812 passaram, com P03 identificado como fixture.
- Limite: o FIT real não foi anexado nem exposto. Comparação manual mascarada com
  a Garmin aguarda conexão persistente + dois syncs do P02; a fase não é `DONE`.
- Correções encontradas pelo gate: decoder reiniciado após CRC; volume Docker
  inicializado como UID 10001/mode 0700; marker P07 único por revisão para impedir
  colisão entre treinos de conteúdo idêntico em banco persistente.
- Próxima ação: concluir o gate P02, processar uma das atividades importadas e
  registrar somente métricas agregadas mascaradas e o checksum parcial.

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

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T09:53:04-03:00
- Commit/PR: [`ec86e8c`](https://github.com/felipefrmelo/swim-coach/commit/ec86e8c6d4fe44ff6a382ba3b78ffa0ebddc0504) / [draft PR #7](https://github.com/felipefrmelo/swim-coach/pull/7)
- Implementação local: P05-T01..T06 e P05-T09 concluídas; P05-T07 automatizada
  mas aguarda MCP Inspector; P05-T08/host real pendente.
- Evidências:
  - [`docs/evidence/p05-mcp-read-only.md`](docs/evidence/p05-mcp-read-only.md)
  - [`docs/handoffs/p05.md`](docs/handoffs/p05.md)
  - documentação oficial OpenAI de autenticação MCP revalidada em 2026-08-12;
  - JWT/JWKS/issuer/audience/expiry/scopes e redaction cobertos por testes;
  - migration `000006` em `up/down/up` para invocation sanitizada por args hash;
  - oito tools read-only comparadas com `contracts/mcp-tools.yaml`; zero write tool;
  - cliente MCP Streamable HTTP → auth ausente, scope, subject mapping, IDOR,
    inputs inválidos, resultados empty/partial/normalizados e headless aprovados;
  - performance local: duas queries fixas para swims+analysis, até cinco para
    semana e p95 de 30 reads abaixo do limite de 500 ms;
  - `make check` → 91 testes Python, 2 Vitest, Ruff, mypy, ESLint, TypeScript e
    validadores verdes.
  - Compose rebuild/up → API, worker, web e PostgreSQL saudáveis, migration
    `000006`; runtime sem OAuth segue fail-closed no tool P00.
  - dependency scan e gitleaks (16 commits + worktree) sem achados.
  - GitHub Actions [run 31601391000](https://github.com/felipefrmelo/swim-coach/actions/runs/31601391000)
    → `quality` aprovado em 1m46s.
- Gate pendente: consulta no host com token real user-scoped, scopes mínimos e
  dados Garmin reais persistidos; fixture e cobertura automatizada não substituem
  essa prova.

### P06

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T10:34:52-03:00
- Commit/PR: [`4528e59`](https://github.com/felipefrmelo/swim-coach/commit/4528e593c26594b915e4d12baf26e350b0f3ae9e) / [draft PR #8](https://github.com/felipefrmelo/swim-coach/pull/8)
- Escopo: P06-T01..T08; implementação independente iniciada enquanto o gate
  externo P05 permanece pendente.
- Implementação local: P06-T01..T04 e P06-T06 concluídas; P06-T05/T07/T08
  aguardam upgrade da cópia pessoal e smoke em conversa nova.
- Evidências:
  - [`docs/evidence/p06-plugin-read-only.md`](docs/evidence/p06-plugin-read-only.md)
  - [`docs/handoffs/p06.md`](docs/handoffs/p06.md)
  - conexão real encontrada localmente como mapeamento técnico
    `plugin_asdk_app_6a7b7fbeceec819196c168888a9494b6`;
  - marketplace pessoal já contém `swim-coach@personal` instalado/ativo na
    versão spike;
  - manifesto e três Skills aprovados pelos validadores oficiais; capability
    exclusiva `Read`, sem Skill/tool futura empacotada;
  - 66 evals contratuais aprovadas: 22 por Skill, cobrindo direct, indirect,
    follow-up, empty, auth e adversarial com todas as writes proibidas;
  - `make check` → 94 testes Python, 2 Vitest, lint, tipos e validadores verdes;
  - dependency scan sem vulnerabilidades conhecidas e gitleaks sem achados em
    19 commits + worktree;
  - flake AES-GCM corrigido no commit [`dfd68b3`](https://github.com/felipefrmelo/swim-coach/commit/dfd68b3),
    sem alteração na implementação criptográfica;
  - GitHub Actions [run 31603753428](https://github.com/felipefrmelo/swim-coach/actions/runs/31603753428)
    → `quality` aprovado em 1m33s.
  - release candidate [`releases/plugin-0.1.0.json`](releases/plugin-0.1.0.json)
    registra hashes de manifesto, app mapping e Skills.
- Gate pendente: duas tentativas de mover a cópia pessoal para backup expiraram
  na aprovação externa sem alterar a instalação; ela permanece em `0.0.0-spike`.
  Depois do upgrade, falta smoke em conversa nova e host OAuth P05 com dado real.

### P07

- Estado: `IN_PROGRESS`
- Início: 2026-08-11T22:01:00-03:00
- Commit/PR: [`c88d660`](https://github.com/felipefrmelo/swim-coach/commit/c88d660) / [draft PR #5](https://github.com/felipefrmelo/swim-coach/pull/5)
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
  - draft PR #5 publicado, empilhado sobre o P04; CI iniciada no run
    `31553966600`.
- Limite: nenhuma escrita externa real; `IN_PROGRESS` até treino descartável real
  publicado/agendado uma vez e replay confirmado sem duplicata.

### P08

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T10:58:49-03:00
- Escopo: P08-T01..T09, usando a implementação P07 fake/kill-switch e o pacote
  P06 como base; gates externos P06/P07 permanecem pendentes.
- Implementação local: P08-T01..T09 concluídas; gate automatizado aprovado e
  gate real de host/Garmin pendente.
- Commit/PR: [`ee728f0`](https://github.com/felipefrmelo/swim-coach/commit/ee728f0) / [draft PR #9](https://github.com/felipefrmelo/swim-coach/pull/9)
- Evidências:
  - branch `p08-mcp-controlled-write` criada sobre o PR #8 com todo o histórico
    P07/P05/P06 presente.
  - [`docs/evidence/p08-mcp-write-approvals.md`](docs/evidence/p08-mcp-write-approvals.md)
  - [`docs/handoffs/p08.md`](docs/handoffs/p08.md)
  - approval e execution separados; replay cria uma única execução/job;
  - scope dinâmico, hash adulterado, execução prematura, IDOR e retry ambíguo
    cobertos por integração PostgreSQL;
  - migration `000007` adiciona correlation/causation sanitizados;
  - plugin `0.2.0` validado com seis Skills e 132 evals, 22 por Skill;
  - gate final decomposto: 81 unit/property/contract + 7 integrações PostgreSQL
    do delta + 2 web; lint, tipos, dependency scan e gitleaks verdes;
  - release candidate [`releases/plugin-0.2.0.json`](releases/plugin-0.2.0.json).
- Gate pendente: instalar a cópia pessoal, conversa nova em dois turnos com OAuth
  real e um canário Garmin descartável seguido de replay sem duplicata.

### P09

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T11:30:00-03:00
- Escopo: P09-T01..T08 sobre a superfície P08; gates externos anteriores seguem
  pendentes e não são promovidos por fixture.
- Implementação local: P09-T01..T07 concluídas; P09-T08 aprovada no bridge host
  de teste e pendente no host real do ChatGPT.
- Commit/PR: [`48729a9`](https://github.com/felipefrmelo/swim-coach/commit/48729a9) / [draft PR #10](https://github.com/felipefrmelo/swim-coach/pull/10)
- Evidências:
  - [`docs/evidence/p09-mcp-apps-ui.md`](docs/evidence/p09-mcp-apps-ui.md)
  - [`docs/handoffs/p09.md`](docs/handoffs/p09.md)
  - cinco resources `ui://` versionados com MIME MCP Apps e CSP fechada;
  - cinco render tools read-only desacopladas das tools de dados/ação;
  - flag independente fail-closed e paridade exata da superfície P08 sem UI;
  - bridge mock, viewport móvel, expiração e double-click cobertos por Playwright;
  - documentação oficial OpenAI revalidada em 2026-08-12 para o protocolo e
    metadados atuais.
  - [GitHub Actions run `31611210574`](https://github.com/felipefrmelo/swim-coach/actions/runs/31611210574)
    → job `quality` verde em 1m33s.
- Gate pendente: carregar os cards pela conexão real do ChatGPT, testar revisão e
  decisão em proposal descartável e salvar screenshot/transcript sanitizados.

### P10

- Estado: `IN_PROGRESS`
- Início: 2026-08-12T12:15:00-03:00
- Commit/PR: [`543e3f9`](https://github.com/felipefrmelo/swim-coach/commit/543e3f9) / [draft PR #11](https://github.com/felipefrmelo/swim-coach/pull/11)
- Escopo: P10-T01..T10 implementado localmente; gate automatizado aprovado e
  revisão humana com dados reais pendente.
- Evidências:
  - [`docs/evidence/p10-adaptive-planning.md`](docs/evidence/p10-adaptive-planning.md)
  - [`docs/handoffs/p10.md`](docs/handoffs/p10.md)
  - migration `000008` em `up/down/up` com ruleset, planning run e decisões;
  - gerador puro com golden hash fixo, 40 casos property e limites conservadores;
  - MCP Streamable HTTP + PostgreSQL provaram schema/scopes/ownership/replay e
    aprovação sem criar treino, agenda, execução ou efeito Garmin;
  - progresso da meta separado em endurance, pace, consistency e confidence;
  - plugin `0.4.0` com sete Skills e 154 evals, 22 por Skill;
  - release candidate [`releases/plugin-0.4.0.json`](releases/plugin-0.4.0.json).
  - [GitHub Actions run `31614812787`](https://github.com/felipefrmelo/swim-coach/actions/runs/31614812787)
    → job `quality` verde em 1m41s.
- Gate pendente: proposta gerada de atividades reais persistidas, revisada
  humanamente no ChatGPT com decision trace e hashes sanitizados.

### P11

- Estado: `IN_PROGRESS`
- Escopo: P11-T01..T08 implementado na branch `p11-automation-offline`;
  automação continua desabilitada por padrão e nunca aprova/publica.
- Evidências:
  - scheduler por fuso/dedupe, sync e proposta semanal revisável;
  - pipeline automático existente import→FIT→normalize→match→analyze preservado;
  - notification inbox para treino, feedback, falha e proposal pronta;
  - migration `000009` em `up/down/up`, metrics/retention/retry seguro;
  - PWA com cache estreito, stale explícito e feedback IndexedDB idempotente;
  - CI limpo → 119 Python, 4 Vitest, lint, tipos, scans, validadores e builds verdes;
  - `make build` → Vite e quatro imagens Compose verdes;
  - detalhes em [`docs/evidence/p11-automation-offline.md`](docs/evidence/p11-automation-offline.md)
    e [`docs/handoffs/p11.md`](docs/handoffs/p11.md).
  - [GitHub Actions run `31617300086`](https://github.com/felipefrmelo/swim-coach/actions/runs/31617300086)
    → job `quality` verde em 1m40s.
- Gate pendente: ciclo automático no ambiente pessoal, screenshot offline em
  viewport/iPhone real e fila ao vivo retornando a idade zero sem ação insegura.

### P12

- Estado: `NOT_STARTED`
- Evidências:
