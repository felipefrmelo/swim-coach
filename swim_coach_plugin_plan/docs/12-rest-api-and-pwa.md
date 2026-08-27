# REST API e PWA operacional

## 1. Papel

A PWA não tenta replicar ChatGPT. Ela é uma ferramenta auxiliar para visualizar,
editar, configurar e recuperar operações. REST e MCP chamam os mesmos serviços
de aplicação; não existe regra exclusiva em controller.

O editor vigente usa `POST /api/v1/workouts/save`: “Salvar” cria/revisa e agenda;
“Salvar e enviar ao Garmin” acrescenta o upsert externo na mesma ação. A UI não
mostra proposta, hash, aprovação, execução, versão esperada ou canário. Rotas de
ações legadas não são montadas quando MCP v2 está ativo.

No `StepEditor`, cada etapa comum ou filha de uma repetição expõe diretamente o
tipo de meta, seus valores e notas. As opções são “Sem objetivo”, “Baseado no
esforço (RPE 1–10)” e “Ritmo desejado (`mm:ss/100 m`)”. Notas aceitam até 600
caracteres. A UI valida faixas antes de habilitar os botões de salvamento e usa
os campos canônicos `target` e `instructions`, portanto criar, editar e recarregar
não exige migração adicional. Quando há publicação, `garmin.warnings` expõe
qualquer conversão ou fallback; o editor também antecipa a conversão da faixa RPE
para uma categoria Garmin sem esconder o intervalo original.

## 2. Rotas da PWA

| Rota | Tela |
|---|---|
| `/` | dashboard |
| `/today` | treino de hoje |
| `/calendar` | calendário semanal/mensal |
| `/workouts/new` | editor de rascunho |
| `/workouts/:id` | detalhe e revisões |
| `/activities` | lista de atividades |
| `/activities/:id` | detalhe/analytics/feedback |
| `/goals` | meta e progresso |
| `/proposals` | propostas pendentes/histórico |
| `/jobs` | sincronizações e ações |
| `/settings/profile` | perfil e disponibilidade |
| `/settings/pools` | piscinas |
| `/settings/garmin` | conexão/dispositivos/sync |
| `/settings/plugin` | status MCP/plugin e instruções |
| `/settings/privacy` | exportação/exclusão |
| `/admin/audit` | auditoria pessoal |

## 3. Componentes centrais

- `TodayWorkoutCard`
- `GoalProgressCard`
- `WeeklyVolumeCard`
- `RecentSwimsList`
- `WorkoutTreeEditor`
- `StepEditor`
- `RepeatGroupEditor`
- `WorkoutTotalsPanel`
- `WorkoutValidationPanel`
- `RevisionHistory`
- `CalendarBoard`
- `ActivitySummaryCard`
- `IntervalTable`
- `PlannedVsCompleted`
- `FeedbackForm`
- `ProposalImpactView`
- `ApprovalPanel`
- `JobTimeline`
- `GarminConnectionPanel`
- `PluginConnectionHelp`

## 4. REST resources

Base `/api/v1`.

### Perfil e metas

```text
GET    /me
PATCH  /me/profile
GET    /pools
POST   /pools
PATCH  /pools/{id}
GET    /availability
PUT    /availability
GET    /goals
POST   /goals
PATCH  /goals/{id}
GET    /goals/{id}/progress
```

### Atividades

```text
GET    /activities
GET    /activities/{id}
GET    /activities/{id}/intervals
GET    /activities/{id}/lengths
GET    /activities/{id}/analysis
PUT    /activities/{id}/feedback
POST   /activities/{id}/match
DELETE /activities/{id}/match
```

### Garmin/sync

```text
GET    /integrations/garmin
POST   /integrations/garmin/bootstrap-import
POST   /integrations/garmin/disconnect
GET    /integrations/garmin/devices
POST   /sync/garmin/activities
GET    /sync/runs
GET    /sync/runs/{id}
```

### Treinos

```text
GET    /workouts
POST   /workouts
GET    /workouts/{id}
POST   /workouts/{id}/revisions
POST   /workouts/{id}/validate
POST   /workouts/{id}/schedule
GET    /workout-templates
POST   /workout-templates
```

### Propostas e execução

```text
POST   /proposals
GET    /proposals
GET    /proposals/{id}
POST   /proposals/{id}/approve
POST   /proposals/{id}/reject
POST   /proposals/{id}/execute
POST   /proposals/{id}/cancel
GET    /jobs/{id}
POST   /jobs/{id}/retry
```

### Privacidade/operação

```text
POST   /exports
GET    /exports/{id}
POST   /deletion-requests
GET    /audit-events
GET    /health/live
GET    /health/ready
```

## 5. Headers e concorrência

- `Authorization: Bearer`;
- `Idempotency-Key` em writes relevantes;
- `If-Match`/ETag em revisões editáveis;
- `X-Correlation-Id` aceito/gerado;
- `Content-Type: application/json`;
- Problem Details em erro.

## 6. Offline

Cache permitido:

- shell da aplicação;
- treino de hoje já carregado;
- semana atual resumida;
- assets estáticos.

Não cachear:

- tokens;
- FIT;
- tela de segredo/bootstrap;
- propostas executáveis depois da expiração;
- dados de auditoria completos.

Feedback offline pode ser enfileirado localmente apenas na P11, com idempotency key e indicação visual de não sincronizado.

## 7. UX de ações

- preview sempre mostra before/after;
- botão de execução menciona verbo e alvo: “Publicar 1.600 m no Garmin”, não “Confirmar” isolado;
- estado assíncrono visível;
- retry só quando classificado como seguro;
- ambiguidade externa vira “reconciliação necessária”;
- usuário pode cancelar proposal, não apagar auditoria.

## 8. Design responsivo

Prioridade iPhone:

- navegação inferior com Hoje, Calendário, Atividades, Configurações;
- editor usa cards e reorder acessível;
- inputs de meta e notas mantêm alvo mínimo de toque de 44 px e ficam expostos
  no próprio card, sem modal adicional;
- números de ritmo em `tabular-nums`;
- 20 m e unidade exibidos no cabeçalho;
- confirmação crítica sem gesto acidental;
- sem dependência exclusiva de hover.
