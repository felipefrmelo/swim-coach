# P00 — Fundação e spikes de risco

- **Dependências:** nenhuma
- **Prompt:** `../prompts/p00.md`
- **Status inicial:** `NOT_STARTED`

## Objetivo

Criar um repositório executável e provar, antes de construir o domínio, que o caminho Plugin/MCP, OAuth e Garmin é viável no ambiente real do usuário.

## Resultados da fase

- repositório/monorepo com backend, PWA e plugin skeleton;
- tooling, lockfiles, Docker Compose e CI;
- servidor MCP inofensivo com `get_capabilities`;
- plugin Skills-only ou conexão de teste instalado em superfície suportada;
- spike OAuth documentado;
- spike Garmin somente leitura documentado, sem tokens no repo.

## Fora do escopo

- dados reais persistidos
- modelo completo de domínio
- sync de produção
- UI final
- qualquer escrita Garmin

## Pré-condições

- dependências marcadas `DONE` com evidência;
- repositório limpo ou mudanças existentes compreendidas;
- contratos/ADRs relevantes lidos;
- backups quando a fase toca dados reais;
- secrets disponíveis por canal seguro, nunca no prompt/commit.

## Tasks

### P00-T01 — Bootstrap do repositório

Criar layout alvo, `pyproject.toml`, workspace frontend, lockfiles, `.editorconfig`, `.gitignore`, `.env.example` e comandos padronizados. Fixar versões suportadas após verificar documentação oficial.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T02 — Ambiente local

Docker Compose com PostgreSQL e serviços mínimos; healthcheck; volumes claros; nenhuma credencial real. Criar `make`/`just`/scripts equivalentes para setup, lint, test e dev.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T03 — Skeleton arquitetural

Criar pacotes domain/application/infrastructure/interfaces sem lógica fictícia. FastAPI com liveness/readiness. Worker inicia e encerra com graceful shutdown.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T04 — Spike MCP público inofensivo

Montar SDK Python MCP em `/mcp`; expor `get_capabilities` sem dados pessoais; structured result; annotations; testar com MCP Inspector e tunnel seguro.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T05 — Spike de plugin

Copiar manifesto/Skill mínimo, registrar conexão quando aplicável, gerar marketplace pessoal com fluxo oficial e instalar. Guardar evidência sanitizada da invocação por `@Swim Coach` ou superfície equivalente.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T06 — Spike OAuth

Validar Auth0/IdP com protected resource metadata, authorization code + PKCE, resource/audience e um método de client registration suportado. Não desenvolver auth custom se IdP atende. Registrar callbacks e gaps sem segredos.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T07 — Spike Garmin

Em script local descartável, autenticar com MFA quando necessário, listar atividades/dispositivo e confirmar capacidade de criar modelo de natação. Não publicar treino. Apagar tokens temporários ou guardá-los fora do repo com permissão segura.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T08 — CI e segurança básica

Lint/typecheck/test/backend/frontend, validação JSON/YAML/Markdown, secret scan e dependency scan. Criar primeiro pipeline verde.

**Aceite da tarefa:** código, testes e evidência específica registrados.
### P00-T09 — Decisões e evidências

Atualizar ADRs se o ambiente real divergir; registrar versões, comandos, resultados, limitações de superfície e decisão go/no-go.

**Aceite da tarefa:** código, testes e evidência específica registrados.

## Ordem recomendada de PRs

1. contratos/domínio/migrations;
2. infraestrutura/adapters;
3. interfaces REST/MCP/PWA;
4. testes/evals/evidência;
5. documentação/status/release.

A fase pode dividir mais, mas cada PR deve permanecer utilizável e sem implementação falsa.

## Testes obrigatórios

- unit smoke do backend
- MCP Inspector lista/chama `get_capabilities`
- manifest JSON válido
- marketplace JSON válido
- CI em clone limpo
- secret scan do histórico atual

## Evidência manual/integrada

- captura/log sanitizado do plugin instalado
- transcript do Inspector
- resultado do OAuth discovery/PKCE sem token
- resultado Garmin com IDs mascarados
- commit/CI URL

## Critério de gate

**Plugin/MCP inofensivo funciona em uma superfície real; OAuth possui caminho viável; Garmin read é viável; repo sobe do zero; nenhum segredo vazou.**

## Segurança e privacidade

- executar checklist aplicável de `docs/13-security-auth-privacy.md`;
- verificar logs/resultados antes de anexar evidência;
- testar ownership/scopes quando houver dados;
- tratar efeito externo e dado sensível como risco elevado;
- atualizar threat model se surgir caminho novo.

## Rollback/contingência

Remover tunnel/conexão de teste, revogar clientes/tokens de spike, destruir volumes e manter somente ADR/evidências sanitizadas.

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
