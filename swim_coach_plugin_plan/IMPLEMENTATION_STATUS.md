# Status de implementação

> Atualizar este arquivo no mesmo commit de cada fase. `DONE` exige evidência. Uma fase pode ficar `BLOCKED` sem comprometer a honestidade do projeto.
> Não existe código legado, banco anterior ou dado de aplicação. A P00 possui
> entregas locais reais, mas está bloqueada enquanto faltarem integrações externas.

| Fase | Estado | Dependências | Evidência mínima | Commit/PR |
|---:|---|---|---|---|
| P00 | BLOCKED | — | plugin inofensivo instalado; CI verde; spikes documentados | [`2faaf62` / PR #1](https://github.com/felipefrmelo/swim-coach/pull/1) |
| P01 | NOT_STARTED | P00 | migrações + testes de domínio + PWA shell | — |
| P02 | NOT_STARTED | P01 | import real Garmin sem duplicata | — |
| P03 | NOT_STARTED | P02 | FIT normalizado e analytics reproduzíveis | — |
| P04 | NOT_STARTED | P01 | treino válido de 20 m criado na PWA | — |
| P05 | NOT_STARTED | P03,P04 | MCP read-only autenticado com dados reais | — |
| P06 | NOT_STARTED | P05 | plugin/Skills instalados e evals aprovadas | — |
| P07 | NOT_STARTED | P04 | publicação Garmin pela PWA com aprovação | — |
| P08 | NOT_STARTED | P06,P07 | escrita MCP com scopes/hash/auditoria | — |
| P09 | NOT_STARTED | P08 | UI MCP opcional e fallback headless | — |
| P10 | NOT_STARTED | P03,P04,P08 | semana adaptativa explicável | — |
| P11 | NOT_STARTED | P10 | automações recuperáveis e PWA offline | — |
| P12 | NOT_STARTED | P11 | restore testado e release pessoal | — |

## Evidências por fase

### P00

- Estado: `BLOCKED`
- Início: 2026-08-11T09:26:48-03:00
- Bloqueio confirmado: 2026-08-11T10:32:43-03:00
- Conclusão:
- Commit/PR: [`2faaf62`](https://github.com/felipefrmelo/swim-coach/commit/2faaf62962501f464e2efb419127d6b4fd088512) / [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1)
- Comandos executados:
  - `make check` → Ruff, mypy, 9 testes backend, ESLint, TypeScript, 1 teste frontend e validadores verdes.
  - `make dependency-scan` → nenhuma vulnerabilidade conhecida após atualizar `pytest` para 9.1.1.
  - `make secret-scan` → histórico e árvore de trabalho sem vazamentos.
  - `docker compose build` e `docker compose up -d --wait` → API, worker, PostgreSQL e web saudáveis.
  - `docker compose down -v` → stack e volume vazio descartável removidos após o smoke test.
  - MCP Inspector `tools/list` e `tools/call get_capabilities` → schema estruturado e `isError=false`.
  - sessão `codex exec` efêmera/read-only → MCP `swim_coach_p00.get_capabilities` descoberto e chamado com sucesso.
  - `codex plugin add swim-coach@personal` → `0.0.0-spike` instalado e habilitado.
  - `gh auth status`, `gh api user` e `git ls-remote` fora do sandbox → conta `felipefrmelo` autenticada via keyring e remote SSH acessível.
  - [GitHub Actions run `31515474864`](https://github.com/felipefrmelo/swim-coach/actions/runs/31515474864) → job `quality` verde em 1m05s.
- Evidências de integração:
  - [`docs/evidence/p00-foundation-evidence.md`](docs/evidence/p00-foundation-evidence.md)
  - [`docs/handoffs/p00.md`](docs/handoffs/p00.md)
- Decisões/ADRs:
  - ADRs existentes preservados; nenhuma divergência arquitetural encontrada.
  - Plugin P00 permanece Skills-only, sem `.app.json` inventado e sem MCP remoto registrado.
  - Conexão local project-scoped do Codex limita o MCP a `get_capabilities`; ela não substitui o tunnel/endpoint remoto.
- Pendências:
  - executar o probe de metadados contra tenant Auth0 real e registrar transcript sanitizado;
  - executar o probe read-only com a conta Garmin do proprietário e registrar apenas contagens/booleanos;
  - testar via Secure MCP Tunnel ou endpoint HTTPS seguro em uma superfície remota suportada;
- Condições de retomada:
  - issuer/resource OAuth reais e publicamente consultáveis;
  - execução local do proprietário com credenciais Garmin via input oculto;
  - `tunnel_id` + API key de runtime/permissões, ou endpoint HTTPS autorizado;

### P01

- Estado: `NOT_STARTED`
- Evidências:

### P02

- Estado: `NOT_STARTED`
- Evidências:

### P03

- Estado: `NOT_STARTED`
- Evidências:

### P04

- Estado: `NOT_STARTED`
- Evidências:

### P05

- Estado: `NOT_STARTED`
- Evidências:

### P06

- Estado: `NOT_STARTED`
- Evidências:

### P07

- Estado: `NOT_STARTED`
- Evidências:

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
