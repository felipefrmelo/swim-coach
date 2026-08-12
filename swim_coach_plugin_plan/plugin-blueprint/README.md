# Blueprint do plugin `swim-coach`

Este diretório é uma especificação inicial, não uma conexão MCP pronta.

## Estado seguro versionado

O manifesto em `.codex-plugin/plugin.json` representa somente a release **P00 `0.0.0-spike`**:

- aponta para `release-skills/p00/`;
- declara apenas capacidade `Read`;
- inclui uma única Skill inofensiva;
- não contém `apps`, `.app.json`, conexão MCP, token ou identificador inventado;
- não expõe os Skills de escrita do estado-alvo.

O diretório `skill-library/` documenta os sete workflows finais. Ele **não é o diretório ativo do manifesto** e não deve ser copiado integralmente para uma release anterior ao seu gate.

## Caminho de implementação

Na P00:

1. copie o blueprint seguro para `plugins/swim-coach/` no repositório real;
2. implemente o MCP inofensivo com `get_capabilities`;
3. registre a conexão de teste em developer mode quando a superfície permitir;
4. use `plugin-creator` para gerar o wiring da conexão e o marketplace pessoal;
5. instale e execute apenas o eval de descoberta da plataforma.

Na P06:

1. materialize somente `review-latest-swim`, `goal-progress` e a variante **read-only** de `diagnose-sync` em `skills/`;
2. mude a versão para `0.1.0` e mantenha `capabilities: ["Read"]`;
3. registre o MCP real do ambiente;
4. use `plugin-creator` para gerar/revisar `.app.json`;
5. adicione `"apps": "./.app.json"` ao manifesto;
6. gere marketplace pessoal, instale e rode os evals read-only.

Na P08, somente após os gates de proposal, approval, scopes, idempotência e reconciliação:

- materialize os Skills de escrita liberados;
- mude a versão para `0.2.0`;
- acrescente `Write` às capabilities;
- rode toda a suíte adversarial de confirmação.

Não invente o schema de `.app.json`. Não versione tokens. Trate o identificador da conexão conforme a política do ambiente e nunca o confunda com credencial.
