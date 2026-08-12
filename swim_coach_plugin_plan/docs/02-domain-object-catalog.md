# Catálogo completo de objetos

Este catálogo é normativo para nomes e responsabilidades. Nem todo objeto é tabela: há value objects, agregados, DTOs, comandos, queries, resultados e objetos de integração.

## 1. Value objects fundamentais

| Objeto | Campos | Invariantes/uso |
|---|---|---|
| `UserId` | UUID | não vazio; escopo de todas as entidades pessoais |
| `EntityId` | UUID | identificador interno genérico quando aceitável |
| `ExternalId` | `provider`, `value` | provider/value não vazios; nunca PK interna |
| `CorrelationId` | string/UUID | propagado ponta a ponta |
| `IdempotencyKey` | string | única por usuário, operação e janela |
| `SchemaVersion` | semver/string | presente em contratos públicos |
| `RevisionNumber` | int | inicia em 1 e cresce monotonicamente |
| `ConcurrencyToken` | int/etag | controle otimista |
| `Checksum` | algoritmo, digest | conteúdo imutável e formato válido |
| `ContentHash` | digest | hash canônico de payload/ação |
| `EncryptedSecret` | ciphertext, key version, nonce | não serializável para API/log |
| `SecretReference` | vault/key id | aponta, não contém segredo em texto |
| `DateRange` | start/end | start ≤ end |
| `InstantRange` | start/end UTC | start < end |
| `LocalDateTime` | local + timezone | timezone IANA obrigatório |
| `TimeWindow` | start/end local | início < fim |
| `Distance` | `meters: int` | `meters >= 0` |
| `PoolLength` | `meters: int` | `meters > 0`; inicial 20 |
| `Duration` | `seconds: Decimal` | `>= 0` |
| `Pace` | `seconds_per_100m: Decimal` | `> 0` |
| `PaceRange` | min/max | `0 < min <= max` |
| `Speed` | meters_per_second | `>= 0` |
| `Percentage` | Decimal | limites definidos pelo contexto |
| `Ratio` | numerator/denominator | denominator != 0 |
| `Rpe` | int | 1..10 |
| `HeartRate` | bpm | faixa plausível configurada; não diagnóstico |
| `HeartRateRange` | min/max | min ≤ max |
| `Cadence` | strokes_per_minute | `>= 0` |
| `Swolf` | score | inteiro/decimal não negativo |
| `StrokeCount` | int | `>= 0` |
| `LengthCount` | int | `>= 0` |
| `TrainingLoad` | value + method | método explícito (`sRPE`, etc.) |
| `Confidence` | 0..1 | não confundir com probabilidade clínica |
| `ActionHash` | digest | vincula aprovação ao conteúdo exato |
| `ApprovalExpiry` | instant | futuro no momento da emissão |
| `OAuthScope` | string | catálogo fechado e documentado |
| `Audience` | URI | corresponde ao resource server |
| `Cursor` | opaque string | não expõe offset interno |
| `PageSize` | int | 1..100 |
| `SortSpec` | field/direction | campo allowlisted |
| `StorageKey` | string | sem path traversal |
| `MimeType` | string | allowlist por artefato |

## 2. Identidade e atleta

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `AppUser` | aggregate | id, email, locale, timezone, status | conta local e isolamento |
| `AuthIdentity` | entity | provider, subject, claims snapshot | vínculo OIDC |
| `AthleteProfile` | aggregate | level, sessions/week, preferences | parâmetros do treinador |
| `AthleteConstraint` | entity | type, severity, dates, notes | restrição/preferência; não diagnóstico |
| `AvailabilityRule` | entity | weekday, windows, exceptions | disponibilidade recorrente |
| `Pool` | aggregate | name, length, location, default | local de natação |
| `Device` | entity | provider id, model, capabilities | dispositivo conhecido |
| `UserPreference` | entity/value map | key, value, source | preferências explicitamente persistidas |
| `ConsentRecord` | entity | purpose, version, accepted_at | consentimento para integração/dados |

## 3. Objetivos e planejamento

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `TrainingGoal` | aggregate | metric, target, deadline, priority, status | objetivo principal |
| `GoalMilestone` | entity | metric, target, due date | checkpoint |
| `GoalProgressSnapshot` | aggregate | as_of, measured, expected, confidence | progresso versionado |
| `TrainingPlan` | aggregate | goal, start/end, status, ruleset version | plano macro |
| `TrainingWeek` | entity | week_start, phase, target volume/intensity | unidade semanal |
| `TrainingDay` | entity/value | date, availability, planned load | contexto diário |
| `TrainingRuleSet` | aggregate imutável | version, rules, effective dates | regras determinísticas |
| `PlanningRun` | aggregate | input snapshot, rule version, output, status | execução reprodutível |
| `TrainingDecision` | aggregate | decision type, evidence, rationale, actor | memória de decisão, não conversa |
| `AdaptationCandidate` | value/DTO | change, reason, impact | alternativa ainda não persistida |
| `RuleViolation` | value | code, severity, path, explanation | resultado de policy |
| `PlanProposalPayload` | DTO | weeks/workouts/revisions | payload de proposta |

## 4. Treinos

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `PlannedWorkout` | aggregate | date, state, current_revision, schedule | identidade da sessão |
| `WorkoutRevision` | entity imutável | revision, definition, totals, hash | snapshot publicável |
| `WorkoutDefinition` | value tree | title, purpose, pool, nodes | modelo canônico |
| `WorkoutNode` | sealed base | id, type, order | nó genérico |
| `ExecutableWorkoutStep` | value/entity | end condition, target, stroke, equipment | etapa executável |
| `RepeatWorkoutStep` | value/entity | repetitions, child nodes | grupo de repetição |
| `EndConditionSpec` | value | distance/time/lap-button/fixed-rest | condição de término |
| `TargetSpec` | value | none/pace/HR/RPE/zone | alvo |
| `StrokeSpec` | value | freestyle/backstroke/etc/drill | estilo |
| `DrillSpec` | value | drill code, side, notes | educativo |
| `EquipmentSpec` | value | board/fins/paddles/pull buoy/etc | equipamento |
| `IntensitySpec` | value | easy/moderate/threshold/fast/custom | intenção fisiológica |
| `RestSpec` | value | fixed/manual/auto | descanso |
| `WorkoutTotals` | value | distance, active, rest, steps, lengths | totais calculados |
| `WorkoutValidationResult` | result | errors, warnings, totals | validação canônica |
| `WorkoutCompilationResult` | result | provider payload, warnings, hash | saída do compiler |
| `WorkoutTemplate` | aggregate | name, tags, current version | reutilização |
| `WorkoutTemplateVersion` | entity imutável | definition + metadata | versão de template |
| `WorkoutSchedule` | entity | local datetime, pool, status | agenda local |
| `ExternalWorkoutBinding` | entity | provider, external ids, revision/hash | vínculo local↔Garmin |
| `DeviceCapabilityMatrix` | value | supported conditions/targets/limits | validação por device/provider |
| `WorkoutExecutionMatch` | aggregate | planned id, activity id, score, source | pareamento |

## 5. Atividades e analytics

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `Activity` | aggregate | provider ids, sport, start, totals | sessão normalizada |
| `ActivityLap` | entity | order, start/end, metrics | lap lógico do arquivo |
| `ActivityInterval` | entity | work/rest, order, metrics | bloco normalizado |
| `ActivityLength` | entity | length index, stroke, time, strokes | extensão de piscina |
| `RawProviderPayload` | entity | kind, storage/json, checksum | evidência bruta |
| `FileArtifact` | entity | storage key, size, mime, checksum | FIT/GPX/TCX/export |
| `ActivityImport` | aggregate | source, cursor, parser version, status | importação individual |
| `ActivityAnalysis` | aggregate imutável | version, metrics, flags, inputs | análise reprodutível |
| `SessionFeedback` | aggregate | RPE, technique, pain, notes | percepção do atleta |
| `PainReport` | value | location, severity, onset, notes | sinal; nunca diagnóstico |
| `ReadinessSnapshot` | aggregate | source, scores, notes | prontidão contextual |
| `DailyTrainingMetric` | entity | date, volume, load, adherence | agregado diário |
| `WeeklyTrainingMetric` | entity | week, volume, load, distribution | agregado semanal |
| `PerformanceBaseline` | aggregate | window, metrics, sample size | baseline comparável |
| `PersonalBest` | entity | metric, value, activity, date | melhor marca válida |
| `CssEstimate` | aggregate | method, 200/400 times, pace, confidence | CSS/VCN calculada |
| `AdherenceScore` | value | overall + dimensions | aderência planejado/executado |
| `FadeMetric` | value | first vs last, regression | queda dentro da série |
| `ConsistencyMetric` | value | CV/range/split | regularidade |
| `GoalProgressMetric` | value | current pace/endurance gap | progresso da meta |

## 6. Garmin/provider

| Objeto | Tipo | Responsabilidade |
|---|---|---|
| `GarminConnection` | aggregate | estado, conta mascarada, token ref, última validação |
| `GarminAuthBootstrapRequest` | transient DTO | inicia login local/MFA sem persistir senha |
| `GarminTokenBundle` | secret DTO | tokens e validade; só infraestrutura |
| `GarminProviderCapabilities` | value | recursos e versão observada |
| `GarminDeviceDTO` | integration DTO | dispositivo externo |
| `GarminActivitySummaryDTO` | integration DTO | resumo externo |
| `GarminActivityDetailDTO` | integration DTO | detalhe externo |
| `GarminFileReferenceDTO` | integration DTO | arquivo externo |
| `GarminWorkoutDTO` | integration DTO | payload compilado |
| `GarminScheduleDTO` | integration DTO | agendamento |
| `GarminProviderError` | normalized error | categoria, retry, external code sanitizado |
| `GarminRateLimitState` | entity/value | janela e backoff |
| `SyncCursor` | entity | posição incremental por recurso |
| `SyncRun` | aggregate | intervalo, counts, cursor before/after, status |
| `ProviderReconciliationResult` | result | bindings encontrados, ambiguidades, reparos |

## 7. Plugin, Skills e MCP

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `PluginRelease` | aggregate | name, version, manifest hash, released_at | release instalado/publicável |
| `SkillRelease` | entity | skill name/version/hash/compatibility | versionar instruções |
| `PluginInstallation` | entity | user, release, connection id, status | instalação pessoal conhecida |
| `McpPrincipal` | aggregate/entity | subject, user_id, scopes, issuer, audience | identidade autorizada |
| `McpRequestContext` | value | principal, request/correlation id, locale | contexto por chamada |
| `McpToolInvocation` | aggregate | tool, schema version, args hash, outcome, latency | observabilidade/auditoria mínima |
| `ToolResultEnvelope[T]` | DTO | schema_version, request_id, status, data, warnings, next_actions, human_summary | contrato comum |
| `ToolError` | DTO | code, message, retryable, field_errors | erro model-readable |
| `ToolNextAction` | DTO | action, label, required scope | sugestão estruturada |
| `McpUiResource` | DTO | resource URI, mime, version | UI opcional associada |
| `McpUiSession` | entity opcional | principal, resource, started/expires | sessão efêmera de UI |
| `SkillExecutionHint` | DTO | skill/workflow/version | telemetria opcional, sem conversa |
| `CapabilityDescriptor` | DTO | tool, auth, side effects, UI | descoberta própria |

## 8. Propostas, aprovação e execução

| Objeto | Tipo | Campos essenciais | Responsabilidade |
|---|---|---|---|
| `ActionProposal` | aggregate | type, payload, impact, hash, status, expires | ação revisável |
| `ActionImpact` | value | before/after, dates, volume, external effects | explicar mudança |
| `ActionApproval` | entity | proposal, actor, hash, scopes, approved_at | consentimento persistido |
| `ApprovalChallenge` | entity/value | nonce, channel, expiry, consumed | confirmação adicional opcional |
| `ActionExecution` | aggregate | proposal, attempt, job, outcome, external refs | execução auditável |
| `SafetyCheckResult` | result | checks, errors, warnings | gate de domínio/segurança |
| `ApiIdempotencyRecord` | entity | key, request hash, response/status | replay seguro |
| `OperationLock` | entity/value | resource, owner, expiry | exclusão mútua com TTL |

Estados típicos de `ActionProposal`:

```text
DRAFT → READY_FOR_REVIEW → APPROVED → QUEUED → EXECUTING → SUCCEEDED
                  └──────→ REJECTED
                  └──────→ EXPIRED
APPROVED/QUEUED/EXECUTING ─→ FAILED | CANCELLED | NEEDS_RECONCILIATION
```

## 9. Operações

| Objeto | Tipo | Responsabilidade |
|---|---|---|
| `Job` | aggregate | tarefa persistente, retry/backoff/lease |
| `OutboxEvent` | aggregate | publicação transacional |
| `DomainEvent` | value | evento de negócio interno |
| `AuditEvent` | aggregate | ator, ação, alvo, diff sanitizado |
| `Notification` | aggregate | canal, template, status, dedupe |
| `WebhookEvent` | aggregate | entrada externa futura, assinatura/replay |
| `FeatureFlag` | entity | rollout e override por usuário |
| `AppSetting` | entity | configuração tipada e versionada |
| `DataExport` | aggregate | bundle, status, expiry |
| `DeletionRequest` | aggregate | revogação e exclusão por etapas |
| `BackupManifest` | value/entity | snapshot, checksum, components |
| `RestoreRun` | aggregate | restore e verificação |
| `HealthProbe` | DTO | status e dependências |
| `DependencyStatus` | DTO | database/storage/garmin/idp |
| `SecretKeyVersion` | entity | versão, status, rotated_at |

## 10. API e aplicação

### DTOs de borda

- `ProblemDetail`
- `ApiError`
- `PageRequest`
- `PageResponse[T]`
- `ActionAcceptedResponse`
- `ActionStatusResponse`
- `HealthResponse`
- `ValidationIssueDTO`
- `WorkoutSummaryDTO`
- `ActivitySummaryDTO`
- `ActivityDetailDTO`
- `TrainingContextDTO`
- `GoalProgressDTO`
- `SyncStatusDTO`

### Commands

- `BootstrapGarminConnection`
- `DisconnectGarmin`
- `SyncGarminActivities`
- `ImportActivityArtifact`
- `NormalizeActivity`
- `AnalyzeActivity`
- `CreateWorkoutDraft`
- `ReviseWorkout`
- `ScheduleWorkout`
- `CreateActionProposal`
- `ApproveActionProposal`
- `ExecuteApprovedAction`
- `RecordSessionFeedback`
- `GenerateWeekProposal`
- `MatchWorkoutExecution`
- `RetryJob`
- `ExportUserData`
- `DeleteUserData`

### Queries

- `GetAthleteProfile`
- `GetTrainingContext`
- `GetTodayWorkout`
- `GetWeekPlan`
- `ListRecentSwims`
- `GetSwimActivity`
- `GetGoalProgress`
- `GetSyncStatus`
- `GetActionProposal`
- `ListPendingApprovals`
- `GetJobStatus`
- `GetAuditTrail`

## 11. Objetos explicitamente proibidos no domínio

- `ChatMessage` ou `Conversation` como fonte de estado do treinamento;
- payload Garmin como entidade central;
- token/senha em DTO público;
- `dict[str, Any]` como contrato público sem schema;
- string de unidade sem tipo explícito;
- recomendação médica automática;
- booleano ambíguo como `is_done` quando existe máquina de estados.
