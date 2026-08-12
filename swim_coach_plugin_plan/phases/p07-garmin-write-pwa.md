# P07 — Publicação Garmin pela PWA com aprovação

- **Dependências:** P04
- **Prompt:** `../prompts/p07.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Implementar o caminho seguro de compilação, proposta, aprovação, execução e reconciliação Garmin, inicialmente apenas pela PWA.

## Resultados da fase

- ActionProposal/Approval/Execution;
- compiler Garmin;
- publish/schedule jobs;
- bindings/idempotência;
- PWA review/approve;
- feature flag de write.

## Fora do escopo

- MCP write
- modelo decidindo aprovação
- UI MCP

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P07-T01 — Action domain

Implementar states, canonical action payload/hash, impact, expiry, approval e execution.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T02 — Migrations/constraints

Proposal/approval/execution/binding e uniques de idempotência/ownership.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T03 — Garmin compiler

Mapear canonical workout para provider, capability validation e fixtures; warnings explícitos.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T04 — Preview REST

Criar proposal sem chamar Garmin; mostrar payload resumido, date/device e hash.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T05 — Approval PWA

Review exact impact, approve/reject, expiry/conflict e verbo explícito.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T06 — Execution jobs

Publish e schedule separados, idempotency, binding persistido, outbox/audit.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T07 — Reconciliation

Timeout/ambiguous outcome busca externo antes de retry; `NEEDS_RECONCILIATION` e runbook.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T08 — Feature flags

Read/write separados; kill switch; treino descartável para smoke.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P07-T09 — Delete/cancel scope

Implementar somente o necessário e sempre por proposal; evitar delete remoto no MVP se não for seguro.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- hash canonical/tamper
- expiry/revision conflict
- double click/replay
- provider contract
- ambiguous timeout
- PWA E2E proposal→success
- smoke treino descartável

## Evidência manual/integrada

- binding externo mascarado
- antes/depois PWA
- replay não duplica
- audit trail

## Critério de gate

**Treino descartável é publicado/agendado uma vez pela PWA após confirmação; falhas ambíguas não duplicam.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Kill switch write, cancelar jobs seguros, reconciliar bindings; não tentar apagar automaticamente sem proposal.

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
