# Swim Coach — plano de implementação Plugin-first

> **Versão do plano:** 1.0
> **Data-base:** 11 de agosto de 2026
> **Estado:** P00 bloqueada na validação final do resource metadata OAuth
> **Uso inicial:** pessoal
> **Atleta inicial:** Felipe
> **Dispositivo:** Garmin Forerunner 265
> **Piscina padrão:** 20 m
> **Meta inicial:** 2.000 m em 45 min (`2:15/100 m`)

Este diretório contém a especificação inicial de implementação do Swim Coach, organizada em documentos menores, contratos, fases e gates executáveis por LLMs. A arquitetura definida para o produto é **Plugin-first**.

> **Checkpoint:** a P00 está `BLOCKED`. A conta Garmin real, o Auth0 real e o
> Secure MCP Tunnel em ChatGPT já foram exercitados. Falta republicar e validar
> pelo tunnel o protected resource metadata OAuth recém-implementado. A primeira
> CI remota está verde no PR #1. Veja
> [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

```text
ChatGPT / Codex
       │
       │ plugin instalado
       ▼
Skills ───────────────► instruções de fluxo
       │
       ▼
MCP remoto ───────────► dados, validações e ações controladas
       │
       ├── domínio e serviços de aplicação
       ├── PostgreSQL + worker
       ├── Garmin Connect (adaptador não oficial no uso pessoal)
       └── UI MCP opcional, somente onde acrescentar valor

PWA operacional
       ├── calendário
       ├── editor de treinos
       ├── configurações e Garmin
       ├── feedback pós-treino
       └── contingência quando o host conversacional não estiver disponível
```

## Decisão central

O MVP **não terá um chat próprio nem chamará a OpenAI Responses API**. A conversa será hospedada por ChatGPT/Codex. O backend expõe um MCP seguro; o plugin empacota os Skills e a conexão MCP. A PWA continua necessária para fluxos visuais, configuração, aprovação alternativa e operação independente.

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
| `plugins/swim-coach/` | plugin P00 instalável, restrito ao Skill de capacidades |
| `backend/` | API/MCP, worker, probes e testes da fundação P00 |
| `apps/web/` | shell PWA operacional, sem chat próprio |
| `examples/` | fixtures de referência e payloads válidos |
| `evals/` | casos de avaliação de seleção de tools e segurança |
| `tools/` | geração de índices e validação automática do plano |

## Ordem de implementação

`P00 → P01 → P02 → P03 → P04 → P05 → P06 → P07 → P08 → P09 → P10 → P11 → P12`

A primeira prova de conceito do plugin acontece já na **P00**, com ferramentas sem dados pessoais. A primeira fatia útil com dados reais chega na **P05/P06**. Escritas no Garmin via plugin só entram depois do fluxo de proposta, aprovação, escopos e idempotência.

## Executar a fundação P00

Requer Python 3.12, Node 24 com Corepack, `uv`, Docker e Docker Compose.

```bash
make bootstrap
make check
make dependency-scan
make secret-scan
docker compose up --build --wait
```

A API fica em `http://127.0.0.1:18000`, a PWA em
`http://127.0.0.1:14173` e o PostgreSQL em `127.0.0.1:55432`. As portas
podem ser sobrescritas pelas variáveis documentadas em [`.env.example`](.env.example).
O único tool MCP liberado é `get_capabilities`; ele não acessa dados pessoais e
não produz efeitos externos.

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
- [Handoff atual da P00](docs/handoffs/p00.md)

## Entregáveis para execução

- use [`phases/p00-foundation-and-spikes.md`](phases/p00-foundation-and-spikes.md) como primeiro escopo de implementação;
- use [`prompts/p00.md`](prompts/p00.md) para delegar essa fase a uma LLM;
- use [`contracts/capability-release-matrix.yaml`](contracts/capability-release-matrix.yaml) para impedir liberação precoce de tools e Skills;
- use [`evals/`](evals/) como suíte mínima de comportamento do plugin;
- use [`examples/`](examples/) como fixtures canônicas;

O arquivo `.app.json` de conexão MCP **não é inventado no blueprint**. Ele deve ser gerado na P06 depois que a conexão real for registrada e fornecer o identificador oficial do ambiente.

## Regras de autoridade

Em caso de conflito, use esta prioridade:

1. ADR aceita mais recente.
2. Contrato versionado em `contracts/`.
3. Documento durável em `docs/`.
4. Arquivo da fase em `phases/`.
5. Prompt de execução.
6. Comentário de código.

Depois que houver implementação, nunca altere um contrato público de forma incompatível sem nova versão, ADR e um plano explícito de compatibilidade ou migração de dados.
