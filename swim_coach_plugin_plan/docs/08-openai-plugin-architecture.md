# Arquitetura do plugin OpenAI

> Verificado contra a documentação oficial em 5 de agosto de 2026. Revalidar antes de publicar, porque superfícies e schemas podem evoluir.

## 1. Forma do plugin

O plugin `swim-coach` combina:

- **Skills:** workflows repetíveis, gatilhos, ordem de ferramentas, tratamento de ausência de dados e formato da resposta;
- **MCP remoto:** ferramentas, schemas, autenticação, autorização, structured content e ações;
- **UI MCP opcional:** somente para inspeção, comparação, edição, confirmação e navegação;
- **manifesto:** identidade e referências ao conteúdo do plugin.

## Contrato 2.0 ChatGPT-first

O plugin 2.0 usa somente `get_coach_context`, `get_workouts`, `get_swims`,
`save_workout`, `publish_workout`, `generate_week`, `sync_garmin` e
`save_feedback`, todos sob o scope OAuth `coach`. As Skills expressam intenção e
não ensinam proposal/hash/approve/execute. Tools locais executam imediatamente;
`publish_workout` é chamado quando o pedido do usuário já é claro. Perguntas
adicionais servem apenas para resolver ambiguidade real, não para cumprir rito.

```text
plugin-blueprint/
├── .codex-plugin/plugin.json        # P00 seguro: Read + Skill inofensiva
├── release-skills/
│   └── p00/get-capabilities/SKILL.md
├── skill-library/                   # estado-alvo; não está ativo no manifesto
│   ├── review-latest-swim/SKILL.md
│   ├── plan-swim-week/SKILL.md
│   ├── adapt-workout/SKILL.md
│   ├── publish-to-garmin/SKILL.md
│   ├── post-swim-checkin/SKILL.md
│   ├── goal-progress/SKILL.md
│   └── diagnose-sync/SKILL.md
└── .app.json                        # ausente até registrar a conexão real

# Estrutura materializada no repositório de implementação, a partir da P06
plugins/swim-coach/
├── .codex-plugin/plugin.json
├── skills/                          # somente Skills liberados na release
├── .app.json                        # gerado/revisado pelo fluxo oficial
└── assets/                          # somente quando existirem assets finais
```

## 2. Responsabilidades

### Skill

- reconhecer o objetivo do usuário;
- selecionar queries/tools;
- definir a ordem;
- lidar com resultado vazio, parcial ou stale;
- pedir confirmação antes da fase de aprovação;
- produzir resposta consistente;
- nunca implementar autorização ou regra de negócio.

### MCP

- derivar o usuário do token;
- validar input;
- consultar/persistir;
- aplicar regras e escopos;
- criar proposta;
- executar somente após approval;
- retornar structured content e texto legível;
- observar chamadas.

### UI MCP

- mostrar estrutura que seria difícil revisar só em texto;
- permitir confirmar ação exata;
- chamar ferramentas pela bridge padrão;
- não ser requisito para completar o workflow.

## 3. Manifesto e releases seguras

O arquivo obrigatório é `.codex-plugin/plugin.json`. Caminhos devem ser relativos à raiz do plugin e começar com `./`. O campo de compatibilidade `apps` só deve apontar para `.app.json` depois que a conexão MCP real tiver sido registrada e o mapeamento tiver sido gerado/revisado pelo fluxo oficial.

### Blueprint P00 — inofensivo

O manifesto entregue no pacote representa a release de spike, não o estado final:

```json
{
  "name": "swim-coach",
  "version": "0.0.0-spike",
  "description": "Harmless platform-feasibility workflow for the personal Swim Coach plugin.",
  "skills": "./release-skills/p00/",
  "interface": {
    "displayName": "Swim Coach",
    "shortDescription": "Verify the Swim Coach integration",
    "capabilities": ["Read"],
    "defaultPrompt": [
      "Use Swim Coach to verify which capabilities are connected."
    ]
  }
}
```

Ele não inclui `apps`, não aponta para a biblioteca de Skills e não anuncia `Write`.

### Release P06 — `0.1.0` read-only

Depois que o MCP real estiver registrado, a implementação deve materializar apenas os três Skills read-only, gerar `.app.json` usando o identificador real e produzir um manifesto equivalente a:

```json
{
  "name": "swim-coach",
  "version": "0.1.0",
  "description": "Review Garmin-backed pool swims and swimming-goal progress.",
  "skills": "./skills/",
  "apps": "./.app.json",
  "interface": {
    "displayName": "Swim Coach",
    "shortDescription": "Review pool swimming training",
    "developerName": "Felipe",
    "category": "Health & Fitness",
    "capabilities": ["Read"],
    "defaultPrompt": [
      "Use Swim Coach to review my latest swim.",
      "Use Swim Coach to show my progress toward 2,000 meters in 45 minutes."
    ]
  }
}
```

### Release P08 — `0.2.0` controlled-write

`Write` só entra após os gates de escopo, proposal, hash, aprovação, idempotência, reconciliação e evals adversariais. Nessa release o manifesto passa a declarar:

```json
{
  "version": "0.2.0",
  "skills": "./skills/",
  "apps": "./.app.json",
  "interface": {
    "capabilities": ["Read", "Write"]
  }
}
```

Esse fragmento não é um manifesto completo; a implementação preserva os demais metadados válidos da release anterior. URLs, assets e dados de publicação só entram quando existirem de verdade.

A fonte de liberação é `contracts/capability-release-matrix.yaml`. A CI deve rejeitar manifesto que anuncie `Write` antes da P08 ou Skill que cite tool indisponível na release.

## 4. Conexão pessoal

Fluxo de desenvolvimento:

1. subir MCP local;
2. conectar via Secure MCP Tunnel ou endpoint HTTPS de desenvolvimento;
3. habilitar developer mode na superfície suportada;
4. registrar a conexão MCP;
5. obter o identificador técnico da conexão;
6. usar `plugin-creator` para gerar o mapeamento `.app.json` e marketplace pessoal;
7. instalar o plugin;
8. testar em conversa nova;
9. guardar prompts e resultados em `tests/evals/`.

A disponibilidade depende da conta, workspace e superfície. Isso é risco de produto, não algo que o backend deve mascarar.

## 5. Servidor MCP

### Transporte

- produção: HTTPS estável + streamable HTTP;
- path recomendado: `/mcp`;
- desenvolvimento: tunnel seguro;
- health REST separado; não confundir `/health` com protocolo MCP.

### Server instructions

As primeiras instruções devem ser curtas e prioritárias:

```text
Swim Coach exposes user-scoped swimming training data and controlled actions.
Use read tools freely when authorized. For any external or schedule-changing action,
create or retrieve a proposal, present its exact impact, obtain explicit user confirmation,
approve the matching action_hash, then execute. Never infer approval.
```

### Tool design

- nomes estáveis em `snake_case`;
- descrição centrada no objetivo;
- input explícito e reduzido;
- output schema versionado;
- IDs estáveis;
- annotations de leitura/destruição/mundo externo;
- falhas distinguem input, auth, conflito, provider e retry.

## 6. Packaging e distribuição

### Pessoal

- marketplace local/pessoal;
- plugin versionado no mesmo repositório;
- auth `ON_INSTALL` ou conforme host gerar;
- conexão MCP registrada por ambiente;
- não publicar tokens/connection IDs sensíveis.

### Público futuro

Só após:

- provider Garmin oficial ou base legal/termos revisados;
- multiusuário e isolamento testados;
- política de privacidade e termos;
- suporte e observabilidade;
- review de metadados, segurança e UX;
- submissão formal.

## 7. Compatibilidade

- tratar UI como capability opcional;
- manter ferramentas úteis sem componente;
- não assumir que todos os hosts suportam os mesmos recursos;
- Skills não devem depender de uma frase exata do usuário;
- contratos do MCP são mais estáveis que instruções de apresentação.

## 8. Fontes oficiais

- https://developers.openai.com/plugins/concepts/plugins
- https://developers.openai.com/plugins/concepts/skills
- https://developers.openai.com/plugins/concepts/mcp-server
- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/build/chatgpt-ui
