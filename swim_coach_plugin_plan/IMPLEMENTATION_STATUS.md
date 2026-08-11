# Status de implementação

> Atualizar este arquivo no mesmo commit de cada fase. `DONE` exige evidência. Uma fase pode ficar `BLOCKED` sem comprometer a honestidade do projeto.
> Não existe código legado, banco anterior ou dado de aplicação. A P00 foi
> concluída com evidências locais e integrações externas reais; P01 é a próxima
> fase elegível.

| Fase | Estado | Dependências | Evidência mínima | Commit/PR |
|---:|---|---|---|---|
| P00 | DONE | — | Garmin read, OAuth resource binding, tunnel/ChatGPT e CI reais | [PR #1](https://github.com/felipefrmelo/swim-coach/pull/1) |
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
