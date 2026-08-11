# P08 — Ferramentas MCP de escrita e aprovação

- **Dependências:** P06 e P07
- **Prompt:** `../prompts/p08.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Permitir sync, feedback, propostas e publicação Garmin pelo plugin, mantendo confirmação explícita, escopos, hash, idempotência e auditoria.

## Resultados da fase

- write tools MCP;
- scopes granulares;
- Skills adapt/publish/check-in;
- evals de confirmação;
- plugin v0.2.0.

## Fora do escopo

- planejamento adaptativo de semana
- UI MCP obrigatória
- delete de dados

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P08-T01 — Scopes/consent

Habilitar bundles de write e testar upgrade/re-auth de conexão.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T02 — Tools local write

sync_garmin_activities, record_session_feedback, create_workout_draft e proposal change/reschedule.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T03 — Preview/approval/execute

preview_garmin_publish, get proposal, approve exact hash e execute approved action.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T04 — Dynamic action scope

Execução verifica escopo específico da proposal além de `proposals:approve`.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T05 — Skill publish

Implementar hard turn boundary: preview e pedir confirmação; approval/execute somente no follow-up explícito.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T06 — Skills adapt/check-in/sync

Adicionar workflows e fallback; nunca pedir senha.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T07 — Safety evals

Bypass prompts, “faça sem perguntar”, stale hash, expired, other user, duplicate, ambiguous provider.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T08 — Audit/telemetry

Ligar tool invocation→proposal→approval→job→binding por correlation/causation.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P08-T09 — Release v0.2.0

Atualizar manifest/Skills/hashes/changelog e instalar upgrade.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- scope matrix
- proposal/approval contract
- same-turn forbidden eval
- idempotency
- IDOR
- provider ambiguity
- real plugin smoke with disposable workout

## Evidência manual/integrada

- transcript em dois turnos com confirmação
- tool trace sanitizada
- Garmin result/binding
- eval report

## Critério de gate

**Plugin executa write apenas após confirmação explícita e hash válido; replay/ataque não causam efeito duplicado.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Revogar scopes/connection, desligar MCP writes por flags, manter PWA write e plugin read-only.

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
