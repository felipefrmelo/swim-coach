# P10 — Planejamento e adaptação semanal

- **Dependências:** P03, P04 e P08
- **Prompt:** `../prompts/p10.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Gerar propostas semanais explicáveis e conservadoras a partir de meta, disponibilidade, histórico, aderência e feedback.

## Resultados da fase

- TrainingPlan/Week/RuleSet/PlanningRun/Decision;
- rule engine;
- propose_week_plan tool;
- plan Skill;
- goal progress avançado;
- plugin v0.4.0.

## Fora do escopo

- ML preditivo
- diagnóstico
- aprovação automática
- outros esportes

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P10-T01 — Rule schema

Versionar regras, priorities, limits e defaults; persistir content hash.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T02 — Planning context

Snapshot determinístico de goal, availability, recent metrics, feedback, constraints e current plan.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T03 — Week generator

Distribuir sessões/objetivos/volume com regras conservadoras e piscina 20 m.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T04 — Adaptation policies

Tempo reduzido, treino perdido, baixa aderência, fatigue feedback, reschedule e deload.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T05 — Explainability

TrainingDecision ordenada com evidence refs, rule IDs e before/after.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T06 — Proposal integration

Resultado sempre é ActionProposal; revisão e aprovação reutilizam domínio existente.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T07 — MCP/Skill

propose_week_plan + plan-swim-week; não aprovar/publicar em cadeia.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T08 — Goal progress

Distinguir pace/endurance/consistency, confidence e sample size.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T09 — Golden/property tests

Cenários e invariantes de carga/recovery; mesma entrada+ruleset→mesma saída.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P10-T10 — Release

plugin v0.3.0 e evals de planejamento.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- golden weeks
- determinism
- load limits
- constraints priority
- pain conservative behavior
- proposal only
- Skill evals

## Evidência manual/integrada

- semana proposta para dados reais revisada humanamente
- decision trace
- rule version/hash

## Critério de gate

**Plano semanal é reproduzível, explicável, respeita limites e só altera estado após aprovação.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Desativar generator/Skill; manter criação manual e proposals anteriores; não apagar rulesets usados.

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
