# P05 — MCP autenticado somente leitura

- **Dependências:** P03 e P04
- **Prompt:** `../prompts/p05.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Permitir que ChatGPT/Codex consultem contexto, treinos e atividades reais com OAuth 2.1, schemas estáveis e sem qualquer write.

## Resultados da fase

- endpoint `/mcp` autenticado;
- protected resource metadata;
- McpPrincipal/invocations;
- tools read-only;
- Inspector e host real;
- outputs minimizados/headless.

## Fora do escopo

- sync via tool
- feedback via tool
- proposals/write
- Skills completas
- UI MCP

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P05-T01 — OAuth resource server

Implementar metadata, JWT/JWKS validation, issuer/audience/resource/scopes e mapping subject→user.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T02 — MCP context

Request/correlation/principal, error mapping, result envelope e server instructions.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T03 — Read tools

Implementar get_capabilities, get_training_context, get_today_workout, get_week_plan, list_recent_swims, get_swim_activity, get_goal_progress, get_sync_status.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T04 — Sanitização

DTOs específicos MCP, limits/pagination, truncation, nenhum FIT/token/e-mail desnecessário.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T05 — Observabilidade

McpToolInvocation com args hash, outcome/latency; audit de auth falha sem token.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T06 — Contrato/annotations

Registrar schemas e annotations; validar com `contracts/mcp-tools.yaml`.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T07 — Inspector

Testar cada tool, inputs inválidos, empty, auth, scope, ownership e result content.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T08 — Conexão host

Registrar MCP em developer mode/tunnel ou HTTPS e executar consultas com dados reais.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P05-T09 — Performance

Evitar chamadas Garmin síncronas; medir p95 local de reads e queries N+1.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- OAuth discovery/JWT/scope
- IDOR
- schema contract
- MCP Inspector
- empty/stale/partial outputs
- log redaction
- basic load

## Evidência manual/integrada

- transcript sanitizado de “como foi minha última natação?” via tools
- Inspector report
- OAuth metadata curl
- latency sample

## Critério de gate

**Host consulta dados reais somente leitura com auth e scope; zero write tool disponível; resultados são úteis sem UI.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Revogar conexão/cliente OAuth, desligar `/mcp` por feature flag e preservar REST/PWA.

## Handoff obrigatório

- tasks concluídas e não concluídas;
- arquivos/migrations/contratos alterados;
- comandos e resultados;
- evidência real versus fixture;
- riscos e decisões;
- próximo passo exato.

## Checklist de conclusão

- [ ] todas as tasks aplicáveis concluídas;
- [ ] testes obrigatórios verdes;
- [ ] gate demonstrado;
- [ ] status MD/JSON atualizado;
- [ ] changelog atualizado;
- [ ] ADR/contratos atualizados;
- [ ] nenhum segredo/dado pessoal anexado;
- [ ] handoff escrito.
