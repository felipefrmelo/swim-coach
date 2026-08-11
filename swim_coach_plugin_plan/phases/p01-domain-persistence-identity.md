# P01 — Domínio base, persistência e identidade

- **Dependências:** P00
- **Prompt:** `../prompts/p01.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Construir a fundação transacional e user-scoped: identidade, atleta, piscina, meta, disponibilidade, jobs, outbox, auditoria e shell da PWA.

## Resultados da fase

- schema inicial com migrations;
- perfil Felipe, piscina 20 m e meta 2 km/45 min configuráveis;
- auth PWA e ownership;
- job/outbox/audit/idempotency base;
- PWA autenticada com dashboard vazio honesto.

## Fora do escopo

- Garmin
- FIT
- workout editor
- MCP com dados privados
- planejamento adaptativo

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P01-T01 — Value objects e erros

Implementar IDs, Distance, PoolLength, Duration, Pace, RPE, ranges, correlation/idempotency e erros do domínio com testes.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T02 — Entidades de identidade/atleta

Implementar AppUser, AuthIdentity, AthleteProfile, Pool, AvailabilityRule, AthleteConstraint, Device e repositories/ports.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T03 — Metas

Implementar TrainingGoal e GoalMilestone; seed/CLI cria meta inicial de 2000 m/2700 s e calcula 135 s/100 m.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T04 — Persistência

Criar migrations, SQLAlchemy mappings e repositories. Incluir `user_id`, timestamps, version e constraints/índices.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T05 — Infra transacional

Criar Job, OutboxEvent, AuditEvent e ApiIdempotencyRecord; transaction boundary; worker lease básico sem jobs de negócio.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T06 — OIDC PWA

Configurar login, principal local, allowlist e logout. Adotar estratégia BFF/cookie ou token em memória conforme ADR complementar.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T07 — REST inicial

`/me`, pools, availability, goals e health; Problem Details e correlation ID.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T08 — PWA shell

Rotas, navegação mobile, perfil/piscina/meta e estados empty/loading/error; sem chat.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P01-T09 — Isolamento

Criar segundo usuário fixture e testes de IDOR/ownership em repositories e endpoints.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- value objects/property tests
- migrations up/down/up
- repositories com Testcontainers
- auth positivo/negativo
- IDOR segundo usuário
- outbox/job lease concorrente
- Playwright login e configuração

## Evidência manual/integrada

- schema/migration IDs
- screenshot sanitizado da PWA
- comandos de teste
- dump de constraints sem dados pessoais

## Critério de gate

**Usuário autenticado gerencia contexto inicial; dados são isolados; migrations e worker base estão verdes.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Downgrade das migrations em banco descartável; em ambiente persistente, backup antes de rollback de schema.

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
