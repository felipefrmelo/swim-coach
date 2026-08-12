# UI opcional com MCP Apps

## 1. Decisão

Ferramentas são implementadas e estabilizadas primeiro. UI entra na P09 somente onde melhora inspeção, comparação, edição, confirmação ou navegação. O mesmo workflow deve continuar completo em texto.

## 2. Componentes P09

### `workout-card`

- título, data, piscina e objetivo;
- blocos/repetições colapsáveis;
- distância/duração/descanso;
- warnings;
- revision/hash resumido;
- ações: pedir alteração, abrir PWA, iniciar preview de publicação.

O mesmo resource também renderiza a visão semanal quando o render tool recebe
`view=week`:

- sessões por dia;
- volume total e distribuição;
- comparação com semana anterior;
- avisos de disponibilidade/recuperação;
- ações: revisar uma sessão, abrir calendário.

### `activity-comparison-card`

- planejado vs executado;
- splits e fade;
- aderência;
- feedback ausente/presente;
- não renderizar centenas de lengths sem interação explícita.

### `goal-progress-card`

- alvo e melhor resultado recente;
- ritmo e tamanho/qualidade da amostra;
- link allowlisted para a PWA.

### `proposal-confirmation-card`

- ação externa exata;
- before/after;
- treino/revisão/data/device;
- action hash abreviado;
- expiração;
- botões Approve/Reject;
- chamada de tool, não endpoint oculto.

### `sync-status-card`

- última sync;
- conexão;
- job atual;
- erro sanitizado;
- ação retry quando permitida.

## 3. Arquitetura

- cinco render tools read-only são separados das tools de dados/ação;
- somente os render tools declaram `_meta.ui.resourceUri`;
- resources usam `text/html;profile=mcp-app` e URIs `ui://` versionadas;
- iframe isolado;
- comunicação via bridge MCP Apps JSON-RPC sobre `postMessage`;
- inputs/resultados vêm do host;
- chamadas de tool pela bridge;
- sem token Garmin, bearer token ou segredo no componente;
- CSP estrita e assets versionados.

## 4. Regras de portabilidade

- implementar padrão MCP Apps antes de extensões específicas;
- testar ausência de `window.openai`;
- detectar capability, não user agent;
- manter `structuredContent` equivalente ao que a UI mostra;
- links externos e navegação passam por allowlist;
- UI não cria uma API paralela.

O template usa o protocolo `ui/*` e `tools/call` como caminho principal. A API
`window.openai` é detectada apenas para abrir links externos quando o host a
oferece; links HTML comuns continuam sendo o fallback.

## 5. Segurança de confirmação

- a UI exibe conteúdo vindo da proposal persistida;
- botão chama `approve_action_proposal` com `proposal_id` e `expected_action_hash`;
- server revalida estado, expiry, ownership e escopo;
- UI não pode alterar payload após preview;
- qualquer mudança de revisão invalida a proposal;
- execução sempre exige uma chamada separada fora do card P09.

## 6. Acessibilidade e mobile

- teclado, foco e labels;
- contraste e números legíveis;
- unidades sempre visíveis;
- layout estreito sem scroll horizontal;
- resumo textual equivalente;
- estados loading/error/expired claros.

## 7. Testes

- contract test do resource URI;
- bridge mock;
- Playwright no host de teste quando disponível;
- snapshot sem dados pessoais;
- fallback headless;
- tampering de hash;
- proposal expirada;
- double click/idempotência;
- CSP e links.

## 8. Ativação e rollback

`SWIM_COACH_MCP_UI_ENABLED=true` exige OAuth completo e
`SWIM_COACH_MCP_WRITE_ENABLED=true`. Se qualquer pré-condição faltar, nenhum
resource nem render tool é registrado. Desativar a flag restaura exatamente a
superfície headless P08.
