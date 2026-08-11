# P04 — Treino canônico, calendário e editor PWA

- **Dependências:** P01
- **Prompt:** `../prompts/p04.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Criar, validar, versionar e agendar localmente treinos estruturados de piscina de 20 m, sem publicar no Garmin.

## Resultados da fase

- modelo canônico completo;
- Workout/Revision/Step/Template/Schedule;
- validator/totals;
- editor mobile;
- calendário local;
- contrato JSON Schema.

## Fora do escopo

- Garmin write
- MCP write
- planejamento automático

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P04-T01 — Modelo de treino

Implementar árvore sealed/discriminated, end conditions, targets, stroke, drill, equipment, intensity e rest.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T02 — Validação

Múltiplos de pool length, ranges, depth/size limits, totals, warnings e capability-neutral validation.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T03 — Versionamento

PlannedWorkout e WorkoutRevision imutável; ETag/expected revision; content hash canônico.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T04 — Persistência

Migrations e mapping de definição JSONB normalizada/versionada ou steps relacionais conforme decisão documentada; índices e histórico.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T05 — Application/REST

Create draft, revise, validate, approve local, schedule, templates e list/detail.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T06 — Editor PWA

Adicionar/reordenar steps/repeats, presets 20 m, live totals, errors/warnings, save revision.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T07 — Calendário

Semana/mês, estados, drag/reschedule com validação e timezone.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T08 — Fixtures

Treinos de técnica, endurance, velocidade e teste; todos terminam na parede.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P04-T09 — Contract/property tests

JSON Schema, nested repeats, max limits, arbitrary pool lengths e content hash estável.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- canonical schema validation
- property-based distance multiples
- revision conflict
- totals nested repeats
- PWA editor E2E
- timezone/calendar

## Evidência manual/integrada

- treino 1600 m criado pela UI
- JSON canônico
- revision history
- test output

## Critério de gate

**Usuário cria/edita/agendada treino válido de 20 m; revisão publicada localmente é imutável; não existe chamada Garmin.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Arquivar drafts/revisions criados; migrations reversíveis antes de dados de produção ou migration forward corretiva.

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
