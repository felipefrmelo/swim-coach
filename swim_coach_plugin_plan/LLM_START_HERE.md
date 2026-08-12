# Comece aqui — instruções para a LLM implementadora

Este pacote é uma especificação executável por fases. Não tente implementar tudo em um único contexto ou PR.

## Algoritmo de início

1. Leia [`AGENTS.md`](AGENTS.md) por completo.
2. Leia [`implementation-status.json`](implementation-status.json).
3. Escolha a primeira fase `NOT_STARTED` cujas dependências estejam `DONE`.
4. Abra o arquivo correspondente em [`phases/`](phases/) e o prompt em [`prompts/`](prompts/).
5. Consulte somente o contexto indicado em [`docs/20-context-map.md`](docs/20-context-map.md), acrescentando outros documentos apenas quando necessário.
6. Confirme contratos e ADRs antes de escrever código.
7. Implemente dentro do escopo da fase; não crie stubs que finjam capacidades futuras.
8. Rode testes e gere as evidências exigidas.
9. Atualize `IMPLEMENTATION_STATUS.md`, `implementation-status.json`, `CHANGELOG.md` e o handoff.
10. Pare no gate da fase. A próxima execução começa do checkpoint persistido.

## Ordem de autoridade

1. ADR aceita mais recente;
2. contrato versionado em `contracts/`;
3. documento durável em `docs/`;
4. fase;
5. prompt;
6. comentário de código.

## Restrições que não podem ser reinterpretadas

- piscina padrão de 20 m;
- meta inicial de 2.000 m em 45 min;
- ChatGPT/Codex via Plugin é a interface conversacional principal;
- a PWA não possui chat próprio no MVP;
- o domínio é fonte de validade, não a resposta do modelo;
- Garmin fica atrás de `GarminProvider`;
- nenhuma senha ou token vai para prompt, Git, log ou resultado MCP;
- writes externos usam proposal → revisão → aprovação por hash → execução idempotente → reconciliação;
- UI MCP é opcional e toda tool precisa funcionar sem UI;
- dor não recebe diagnóstico automático.

## Arquivos de navegação

- [`MASTER_PLAN.md`](MASTER_PLAN.md): resultado final e gates;
- [`TASK_INDEX.md`](TASK_INDEX.md): todas as tasks;
- [`FILE_INDEX.md`](FILE_INDEX.md): mapa do pacote;
- [`docs/24-capability-release-matrix.md`](docs/24-capability-release-matrix.md): quando cada tool/Skill é liberada;
- [`PLAN_VALIDATION_REPORT.md`](PLAN_VALIDATION_REPORT.md): integridade do pacote;
- [`tools/validate_plan.py`](tools/validate_plan.py): validação local.

## Comando inicial recomendado

```bash
python tools/validate_plan.py
```

A implementação só começa com o plano válido e o repositório em estado conhecido.
