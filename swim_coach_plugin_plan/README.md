# Swim Coach — plano de implementação Plugin-first

> **Versão do plano:** 1.0
> **Data-base:** 11 de agosto de 2026
> **Estado:** P14 em implementação sobre a P13 ChatGPT-first implantada
> **Uso inicial:** pessoal
> **Atleta inicial:** Felipe
> **Dispositivo:** Garmin Forerunner 265
> **Piscina padrão:** 20 m
> **Meta inicial:** 2.000 m em 45 min (`2:15/100 m`)

Este diretório contém a especificação inicial de implementação do Swim Coach, organizada em documentos menores, contratos, fases e gates executáveis por LLMs. A arquitetura definida para o produto é **Plugin-first**.

> **Checkpoint:** o plugin pessoal 2.1 reúne oito Skills e nove comandos MCP sob
> o scope `coach`. Salvar, editar, agendar, planejar, sincronizar, registrar
> feedback e publicar são diretos; revisão, idempotência e reconciliação ficam
> internas. A PWA é auxiliar. Veja
> [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

```text
ChatGPT / Codex
       │
       │ plugin instalado
       ▼
Skills ───────────────► instruções de fluxo
       │
       ▼
MCP remoto ───────────► nove comandos de intenção
       │
       ├── domínio e serviços de aplicação
       ├── PostgreSQL + worker
       ├── Garmin Connect (adaptador não oficial no uso pessoal)
       └── revisões, idempotência e reconciliação invisíveis

PWA operacional
       ├── calendário
       ├── editor de treinos
       ├── configurações e Garmin
       ├── feedback pós-treino
       └── contingência quando o host conversacional não estiver disponível
```

## Decisão central

O MVP **não terá um chat próprio nem chamará a OpenAI Responses API**. A conversa será hospedada por ChatGPT/Codex. O backend expõe um MCP com nove comandos diretos; o plugin empacota as Skills e a conexão MCP. A PWA é auxiliar para edição visual, calendário, configuração e diagnóstico.

## Como uma LLM deve começar

1. Abra [`LLM_START_HERE.md`](LLM_START_HERE.md) e siga o algoritmo de início.
2. Leia [`AGENTS.md`](AGENTS.md) e [`MASTER_PLAN.md`](MASTER_PLAN.md).
3. Confira o checkpoint em [`implementation-status.json`](implementation-status.json).
4. Execute apenas a primeira fase `NOT_STARTED` cujas dependências estejam `DONE`.
5. Carregue somente os documentos indicados no mapa de contexto da fase.
6. Valide o pacote antes e depois da alteração com `python tools/validate_plan.py`.
7. Atualize status, evidências, decisões, índices e changelog ao concluir o gate.

## Mapa do pacote

| Caminho | Finalidade |
|---|---|
| `LLM_START_HERE.md` | algoritmo de retomada para qualquer LLM |
| `MASTER_PLAN.md` | visão integrada, ordem e gates |
| `AGENTS.md` | regras permanentes para agentes de código |
| `IMPLEMENTATION_STATUS.md` | checkpoint humano por fase |
| `implementation-status.json` | checkpoint estruturado para automação |
| `TASK_INDEX.md` | índice das 115 tasks e respectivas fases |
| `FILE_INDEX.md` | mapa navegável de todos os arquivos |
| `docs/` | especificações duráveis de produto e arquitetura |
| `phases/` | planos executáveis, um por fase |
| `prompts/` | prompts prontos para delegar cada fase a uma LLM |
| `contracts/` | schemas e contratos de API/MCP/domínio |
| `adrs/` | decisões arquiteturais imutáveis ou versionadas |
| `plugin-blueprint/` | esqueleto do plugin, Skills e instruções de registro |
| `plugins/swim-coach/` | plugin pessoal P14 `2.1.0`, com oito Skills ChatGPT-first e app mapping real |
| `backend/` | API/MCP, worker, probes e testes da fundação P00 |
| `apps/web/` | shell PWA operacional, sem chat próprio |
| `examples/` | fixtures de referência e payloads válidos |
| `evals/` | casos de avaliação de seleção de tools e segurança |
| `tools/` | geração de índices e validação automática do plano |

## Ordem de implementação

`P00 → P01 → P02 → P03 → P04 → P05 → P06 → P07 → P08 → P09 → P10 → P11 → P12 → P13 → P14`

A primeira prova de conceito do plugin aconteceu na **P00**. A P13 substitui a
superfície histórica por oito comandos e mantém autenticação, ownership,
idempotência e reconciliação no servidor, sem expor proposal/hash/approval.

## Executar o stack pessoal 2.0

Requer Python 3.12, Node 24 com Corepack, `uv`, Docker e Docker Compose.

```bash
make bootstrap
make check
make dependency-scan
make secret-scan
docker compose up --build --wait
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome make e2e
```

A API fica em `http://127.0.0.1:18000`, a PWA em
`http://127.0.0.1:14173` e o PostgreSQL em `127.0.0.1:55432`. As portas
podem ser sobrescritas pelas variáveis documentadas em [`.env.example`](.env.example).
Sem `SWIM_COACH_OAUTH_ISSUER`/`SWIM_COACH_OAUTH_RESOURCE`, o MCP falha fechado e
libera somente `get_capabilities`. Com OAuth, escrita e v2 ativos, anuncia
exatamente `get_coach_context`, `get_workouts`, `get_swims`, `save_workout`,
`publish_workout`, `delete_workout`, `generate_week`, `sync_garmin` e `save_feedback`, todos com
`coach`. Garmin externo continua dependente do kill switch do servidor. A PWA
usa BFF/cookie opaco, allowlist e ownership.

O Git root contém `../.codex/config.toml`, uma configuração
project-scoped que conecta clientes Codex locais ao MCP e aplica allowlist apenas
para `get_capabilities`. Com o stack ativo, confirme-a a partir do Git root:

```bash
cd ..
codex mcp get swim_coach_p00
```

## Documentos mais importantes

- [Produto e escopo](docs/00-product-and-scope.md)
- [Arquitetura Plugin-first](docs/01-architecture.md)
- [Catálogo completo de objetos](docs/02-domain-object-catalog.md)
- [Modelo de dados](docs/03-data-model.md)
- [Arquitetura do plugin OpenAI](docs/08-openai-plugin-architecture.md)
- [Contratos das ferramentas MCP](docs/09-mcp-tool-contracts.md)
- [Skills do plugin](docs/10-plugin-skills.md)
- [Segurança, OAuth e privacidade](docs/13-security-auth-privacy.md)
- [Protocolo de entrega entre LLMs](docs/21-llm-handoff-protocol.md)
- [Matriz de rastreabilidade](docs/22-traceability-matrix.md)
- [Convenções de nomes e versões](docs/23-naming-and-versioning.md)
- [Matriz de liberação de capacidades](docs/24-capability-release-matrix.md)
- [Relatório de validação do pacote](PLAN_VALIDATION_REPORT.md)
- [Evidências da P00](docs/evidence/p00-foundation-evidence.md)
- [Evidências da P01](docs/evidence/p01-domain-persistence-identity.md)
- [Evidências da P13](docs/evidence/p13-chatgpt-first.md)
- [Handoff atual da P13](docs/handoffs/p13.md)

## Entregáveis para execução

- use [`phases/p00-foundation-and-spikes.md`](phases/p00-foundation-and-spikes.md) como primeiro escopo de implementação;
- use [`prompts/p00.md`](prompts/p00.md) para delegar essa fase a uma LLM;
- use [`contracts/capability-release-matrix.yaml`](contracts/capability-release-matrix.yaml) para impedir liberação precoce de tools e Skills;
- use [`evals/`](evals/) como suíte mínima de comportamento do plugin;
- use [`examples/`](examples/) como fixtures canônicas;

O `.app.json` foi materializado a partir da conexão real já registrada. Ele
contém apenas o identificador técnico do app; credenciais e tokens continuam fora
do repositório.

## Regras de autoridade

Em caso de conflito, use esta prioridade:

1. ADR aceita mais recente.
2. Contrato versionado em `contracts/`.
3. Documento durável em `docs/`.
4. Arquivo da fase em `phases/`.
5. Prompt de execução.
6. Comentário de código.

Depois que houver implementação, nunca altere um contrato público de forma incompatível sem nova versão, ADR e um plano explícito de compatibilidade ou migração de dados.
