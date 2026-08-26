# Matriz de liberação de capacidades

Esta matriz impede que uma Skill seja empacotada antes de suas tools existirem e evita expor writes antes dos controles de segurança.

## 1. Releases planejados

| Fase | Versão | Perfil | Resultado |
|---|---|---|---|
| P00 | `0.0.0-spike` | inofensivo | prova de instalação/conexão e `get_capabilities` |
| P06 | `0.1.0` | read-only | análise, progresso e diagnóstico de sync sem disparar ação |
| P08 | `0.2.0` | controlled-write | sync, feedback, proposals, aprovação e Garmin com confirmação |
| P09 | `0.3.0` | UI opcional | MCP Apps para revisar/comparar/confirmar, sem dependência de UI |
| P10 | `0.4.0` | planejamento | proposta semanal adaptativa e explicável |
| P12 | `1.0.0-personal` | hardened | release pessoal operável, recuperável e auditável |
| P13 | `2.0.0` | ChatGPT-first | oito comandos diretos, scope `coach`, Garmin upsert e site auxiliar |

As versões são alvos. A implementação pode ajustar SemVer por ADR, mas não pode antecipar capacidade de risco.

### P13 — superfície pública vigente

- `get_coach_context`;
- `get_workouts`;
- `get_swims`;
- `save_workout`;
- `publish_workout`;
- `generate_week`;
- `sync_garmin`;
- `save_feedback`.

Todas usam `coach`. Tools P00–P10 permanecem somente como histórico/compatibilidade
interna e não são anunciadas quando `SWIM_COACH_MCP_V2_ENABLED=true`.

## 2. Tools por fase

### P00

- `get_capabilities` somente com dados públicos/inofensivos.

### P05/P06 — release read-only

- `get_training_context`;
- `get_today_workout`;
- `get_week_plan`;
- `list_recent_swims`;
- `get_swim_activity`;
- `get_goal_progress`;
- `get_sync_status`.

Nenhuma tool de escrita, sync manual, proposal ou job externo é registrada nessa release.

### P08 — release de escrita controlada

- `get_action_proposal`;
- `get_job_status`;
- `sync_garmin_activities`;
- `record_session_feedback`;
- `create_workout_draft`;
- `propose_workout_change`;
- `propose_workout_reschedule`;
- `preview_garmin_publish`;
- `cancel_action_proposal`;
- `approve_action_proposal`;
- `execute_approved_action`;
- `retry_failed_job`.

A tool `execute_approved_action` não recebe o payload da ação; ela executa somente a proposal persistida, aprovada, não expirada e com hash atual.

### P10 — planejamento adaptativo

- `propose_week_plan`.

Ela gera proposal revisável; não ativa nem publica a semana automaticamente.

## 3. Skills por release

| Skill | Primeira release | Condição |
|---|---:|---|
| `review-latest-swim` | 0.1.0 | analytics/read tools concluídas |
| `goal-progress` | 0.1.0 | meta e progresso com qualidade da amostra |
| `diagnose-sync` | 0.1.0 | somente diagnóstico; sem disparar sync |
| `adapt-workout` | 0.2.0 | revisions/proposals e conflito otimista |
| `publish-to-garmin` | 0.2.0 | preview → follow-up explícito → approval → execute |
| `post-swim-checkin` | 0.2.0 | feedback validado e sem diagnóstico |
| `diagnose-sync` upgrade | 0.2.0 | pode oferecer/disparar sync com scope |
| `plan-swim-week` | 0.4.0 | ruleset versionado e planning run reprodutível |

## 4. UI MCP

Somente P09:

- `render_workout_card` → workout/week card;
- `render_activity_comparison_card` → comparação planejado versus realizado;
- `render_goal_progress_card` → progresso da meta;
- `render_proposal_confirmation_card` → revisão e decisão, nunca execução;
- `render_sync_status_card` → sync/job status e retry somente quando permitido.

As tools de dados/ação não carregam UI. Cada render tool retorna texto e
`structuredContent` suficientes, e toda operação continua disponível sem UI.

## 5. Gates automáticos

A CI deve falhar quando:

- Skill referencia tool ausente da release;
- manifest anuncia `Write` antes de P08;
- tool de write não possui scope/annotations/testes;
- UI é o único caminho para concluir workflow;
- release remove ou altera contrato sem compatibilidade;
- Skill read-only chama tool de write.

A fonte estruturada desta matriz é [`../contracts/capability-release-matrix.yaml`](../contracts/capability-release-matrix.yaml).
