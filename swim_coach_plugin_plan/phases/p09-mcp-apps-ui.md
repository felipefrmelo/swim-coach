# P09 — UI opcional com MCP Apps

- **Dependências:** P08
- **Prompt:** `../prompts/p09.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Adicionar cartões portáteis para revisar treino, comparar atividade e confirmar proposal sem tornar a UI requisito do workflow.

## Resultados da fase

- UI resources versionados;
- workout/activity/proposal/sync cards;
- bridge padrão;
- fallback headless;
- acessibilidade.

## Fora do escopo

- editor completo substituindo PWA
- lógica de domínio no iframe
- dependência exclusiva de ChatGPT extensions

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P09-T01 — UI resource infra

Servir assets versionados/CSP e associar resource URI aos tools selecionados.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T02 — Workout card

Render steps/totals/warnings e links allowlisted.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T03 — Activity comparison

Planejado/executado, metrics e feedback status.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T04 — Proposal confirmation

Mostrar exact action/hash/expiry e chamar approve/reject tool pela bridge.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T05 — Sync card

Status/job/retry quando permitido.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T06 — Portability

MCP Apps standard first; capability-check extensions; no direct private endpoint/token.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T07 — Fallback/accessibility

Mesmo structured content; keyboard/focus/mobile; expired/tamper states.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P09-T08 — E2E

Bridge mock e host real quando disponível; double-click/idempotency.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- resource contract
- CSP
- bridge calls
- headless parity
- a11y
- tamper/expiry
- host smoke

## Evidência manual/integrada

- screenshots sanitizadas
- fallback transcript
- test report

## Critério de gate

**UI melhora review/confirm, mas desabilitá-la não impede nenhum caso de uso.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Remover `_meta.ui.resourceUri`/desativar resources; tools permanecem inalteradas.

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
