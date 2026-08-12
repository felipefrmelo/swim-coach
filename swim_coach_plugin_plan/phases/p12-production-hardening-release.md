# P12 — Hardening, privacidade e release pessoal

- **Dependências:** P11
- **Prompt:** `../prompts/p12.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Tornar o sistema pessoal recuperável, seguro e operável: deploy estável, backup/restore, export/delete, observabilidade, documentação e release final.

## Resultados da fase

- infra HTTPS estável;
- backup e restore drill;
- export/delete;
- security/performance review;
- runbooks;
- release pessoal 1.0;
- readiness pública separada.

## Fora do escopo

- publicação pública automática
- SLA comercial
- multiusuário/billing

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P12-T01 — Deploy

Imagens non-root, reverse proxy, TLS, health/readiness, migrations controladas e secrets do ambiente.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T02 — Backup

Postgres + object storage + manifests/checksums + criptografia + retenção.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T03 — Restore drill

Restaurar em ambiente isolado, verificar counts/checksums/login/atividade/treino e documentar RPO/RTO.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T04 — Export/delete

Export estruturado + FIT; deletion staged revoga plugin/Garmin, cancela jobs e apaga dados conforme ordem.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T05 — Observabilidade

Dashboards/alerts para errors, queue, sync, disk, backups, OAuth e provider.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T06 — Security review

Threat model, dependency/SBOM/image/secret scans, scopes, IDOR, rate limits, headers, incident runbook.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T07 — Performance/capacity

Load smoke MCP/REST, DB indexes, storage growth e retention.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T08 — Release 1.0 pessoal

Versionar backend/PWA/plugin, smoke completo e changelog.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T09 — Documentação operacional

Install/update/rollback/reconnect Garmin/plugin/OAuth/backup/restore.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P12-T10 — Public readiness assessment

Checklist separado; não submeter sem revisão de Garmin, privacidade, suporte e multiuser.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- full E2E
- restore drill
- export/delete
- security suite
- load smoke
- upgrade/rollback
- plugin install clean

## Evidência manual/integrada

- restore report
- release manifest/hashes
- security checklist
- smoke cycle completo

## Critério de gate

**Sistema pessoal pode ser instalado, atualizado, usado, recuperado e apagado com documentação e evidência.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Runbook de rollback de imagem/migration/plugin; restore do último backup verificado; kill switches Garmin/MCP writes.

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
