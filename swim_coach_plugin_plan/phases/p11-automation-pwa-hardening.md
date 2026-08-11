# P11 — Automações, notificações e resiliência da PWA

- **Dependências:** P10
- **Prompt:** `../prompts/p11.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Reduzir trabalho manual sem remover controle: sync periódica, pipeline automático, lembretes, offline seguro e recuperação de jobs.

## Resultados da fase

- scheduler/jobs recorrentes;
- pipeline import→analyze→match;
- notificações;
- offline do treino;
- feedback queue;
- retention e dashboards operacionais.

## Fora do escopo

- monitoramento 24x7 comercial
- push obrigatório
- ação Garmin automática sem approval

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P11-T01 — Scheduler

Cron/periodic jobs com lock/dedupe/timezone; sync e aggregations.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T02 — Pipeline

Eventos/outbox encadeiam file→normalize→analyze→match→metrics sem duplicação.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T03 — Draft semanal

Gerar proposal draft em dia configurado, nunca aprovar/publicar.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T04 — Notifications

Treino, sync falha, feedback pendente e proposal pronta; dedupe/preferences.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T05 — Offline PWA

Cache shell/treino atual; indicador stale; nenhuma approval expirada offline.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T06 — Feedback offline

Fila local com idempotency e reconciliação visual.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T07 — Job operations

Retention, retry UI, queue age, dead/terminal states e runbooks.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P11-T08 — Performance/UX

N+1, payload sizes, lazy detail, iPhone E2E.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- scheduler dedupe/timezone
- pipeline replay
- notification dedupe
- offline E2E
- feedback sync conflict
- job retention

## Evidência manual/integrada

- ciclo automatizado em ambiente pessoal
- PWA offline screenshot
- metrics queue

## Critério de gate

**Nova atividade percorre pipeline automaticamente; usuário recebe estados úteis; offline não executa ação insegura.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Desativar schedules/notifications/Service Worker por flags; processos manuais continuam disponíveis.

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
