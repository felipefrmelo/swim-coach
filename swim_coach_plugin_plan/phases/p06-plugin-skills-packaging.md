# P06 — Skills, pacote e evals do plugin read-only

- **Dependências:** P05
- **Prompt:** `../prompts/p06.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Transformar o MCP read-only em um plugin pessoal instalável, com Skills confiáveis e testes de seleção/orquestração.

## Resultados da fase

- plugin v0.1.0;
- manifest e `.app.json` gerado;
- marketplace pessoal;
- Skills read-only;
- eval suite;
- release record.

## Fora do escopo

- write MCP
- publicação Garmin via chat
- planejamento adaptativo
- UI MCP

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P06-T01 — Release matrix

Definir quais Skills entram em v0.1.0: review-latest-swim, goal-progress, diagnose-sync em modo leitura e consulta de treino/semana. Não empacotar Skills que exigem tools futuras.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T02 — Skill authoring

Escrever frontmatter/gatilhos/passos/fallback/output; referências mínimas; sem duplicar regras de domínio.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T03 — Manifest

Gerar/revisar plugin.json, metadados e prompts iniciais; sem URLs/assets falsos.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T04 — Connection mapping

Usar plugin-creator com ID real para gerar `.app.json`; definir política de versionamento/ignorar por ambiente conforme conteúdo.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T05 — Marketplace

Criar repo/personal marketplace e instalar cópia correta; documentar cache/upgrade.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T06 — Evals

Criar dataset direto/indireto/follow-up/empty/auth/adversarial; asserts de tool order e forbidden tools.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T07 — Compatibility

Testar host/superfície disponível, idioma pt-BR e fallback sem UI.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P06-T08 — Release

Semver, hashes, changelog, PluginRelease/SkillRelease opcional no banco e smoke em conversa nova.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- frontmatter/static validation
- manifest/marketplace JSON
- eval suite
- tool selection negatives
- install/upgrade manual
- read-only permissions

## Evidência manual/integrada

- plugin instalado e invocado
- eval report
- manifest hash
- release note

## Critério de gate

**Plugin pessoal v0.1.0 é instalável, ativa Skills corretas e não expõe/call writes inexistentes.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Desinstalar/desabilitar plugin, remover marketplace entry e manter MCP read-only acessível para diagnóstico.

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
