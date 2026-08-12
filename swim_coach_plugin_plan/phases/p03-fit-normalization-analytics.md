# P03 — FIT, normalização e analytics

- **Dependências:** P02
- **Prompt:** `../prompts/p03.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Preservar o arquivo bruto, normalizar a atividade de piscina e produzir métricas reproduzíveis úteis para o treinador.

## Resultados da fase

- object storage e FileArtifact;
- parser versionado;
- laps/intervals/lengths;
- ActivityAnalysis;
- matching inicial e feedback;
- tela de atividade.

## Fora do escopo

- editor de treino
- MCP
- planejamento de semana
- Garmin write

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P03-T01 — Download e storage

Buscar FIT quando disponível, validar tamanho/mime/checksum, armazenar atomicamente e deduplicar.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T02 — Fixtures anonimizadas

Criar arquivos/representações de teste sem dados pessoais ou produzir sanitização reproduzível. Documentar licenças dos fixtures.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T03 — Parser e normalização

Mapear session/lap/length/record para ActivityLap, ActivityInterval e ActivityLength; tratar piscina 20 m, descansos e missing data.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T04 — Versionamento

Persistir parser version/input checksum; reprocessar criando versão/estado coerente.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T05 — Analytics

Ritmo, moving/elapsed, SWOLF/strokes quando presentes, consistência, fade, volume e data quality.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T06 — Match

Heurística inicial por data/distance/duration; persistir confidence/source; correção manual.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T07 — Feedback

SessionFeedback com RPE/técnica/dor/notes; endpoints e validação; nenhuma inferência médica.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T08 — PWA

Lista e detalhe, intervals, planned-vs-completed placeholder, feedback e quality warnings.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P03-T09 — Golden tests

Resultados esperados por fixture e property tests para fórmulas/unidades/divisão por zero.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- checksum/dedupe
- parser golden
- missing FIT/fields
- 20m length count
- metric formulas
- version reprocessing
- feedback auth/validation
- Playwright activity detail

## Evidência manual/integrada

- atividade real normalizada com dados mascarados
- golden output versionado
- comparação manual de métricas com Garmin

## Critério de gate

**Atividade real/fixture gera análise reproduzível, com qualidade explícita e sem FIT em logs/API conversacional.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Manter raw artifact; remover somente versão de normalização/análise defeituosa e apontar current version anterior.

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
