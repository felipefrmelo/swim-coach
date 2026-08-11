# P02 — Garmin somente leitura e sincronização

- **Dependências:** P01
- **Prompt:** `../prompts/p02.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Conectar a conta Garmin pessoal com segredo protegido e importar atividades de natação de forma incremental, idempotente e observável.

## Resultados da fase

- GarminProvider interno;
- bootstrap local seguro e token cifrado;
- SyncRun/SyncCursor;
- Activity e raw provider payload;
- job real de sync sem duplicatas.

## Fora do escopo

- parsing FIT profundo
- analytics
- publicação de treino
- MCP privado

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P02-T01 — Porta e DTOs Garmin

Definir provider, capabilities, DTOs e categorias de erro sem importar tipos da biblioteca no domínio/aplicação.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T02 — Criptografia de segredo

Implementar key version, AEAD, redaction e testes. Definir rotação e variável/secret store por ambiente.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T03 — Bootstrap CLI

Login/MFA local, export cifrado/import autenticado, destruição de temporários e status de conexão.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T04 — Schema de sync

Migrations para GarminConnection, SyncCursor, SyncRun, ActivityImport, RawProviderPayload e Activity summary.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T05 — Listagem incremental

Implementar cursor/lookback, filtros de pool swimming, paginação, dedupe por external ID/checksum e raw JSON sanitizado.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T06 — Jobs e backoff

Job `garmin.sync_activities`, lock por usuário, rate limit, retry categories e cancelamento seguro.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T07 — REST/PWA Garmin

Tela conexão/status/dispositivos, botão sync e timeline de run; senha nunca no browser.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P02-T08 — Smoke real

Importar ao menos uma atividade real, mascarar IDs na evidência e reexecutar sem duplicação.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- provider contract fixtures
- encryption roundtrip/tamper/rotation
- sync pagination/dedupe
- retry/rate-limit
- disconnect revokes local access
- real smoke manual

## Evidência manual/integrada

- contagem antes/depois/replay
- checksum ou ID mascarado
- logs sem segredo
- status da conexão

## Critério de gate

**Uma atividade real é importada uma vez, replay não duplica, token está cifrado e falhas são classificadas.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Desconectar, apagar segredo cifrado e dados de sync importados por script user-scoped; não depender de senha para rollback.

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
