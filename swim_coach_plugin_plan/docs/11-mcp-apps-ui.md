# UI opcional com MCP Apps

## 1. Decisão

Ferramentas são implementadas e estabilizadas primeiro. UI entra na P09 somente onde melhora inspeção, comparação, edição, confirmação ou navegação. O mesmo workflow deve continuar completo em texto.

## 2. Componentes planejados

### `workout-review-card`

- título, data, piscina e objetivo;
- blocos/repetições colapsáveis;
- distância/duração/descanso;
- warnings;
- revision/hash resumido;
- ações: pedir alteração, abrir PWA, iniciar preview de publicação.

### `week-plan-card`

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

- resource declarado pelo MCP com `_meta.ui.resourceUri`;
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

## 5. Segurança de confirmação

- a UI exibe conteúdo vindo da proposal persistida;
- botão chama `approve_action_proposal` com `proposal_id` e `expected_action_hash`;
- server revalida estado, expiry, ownership e escopo;
- UI não pode alterar payload após preview;
- qualquer mudança de revisão invalida a proposal;
- execução é chamada separadamente ou encadeada somente conforme política explícita.

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
