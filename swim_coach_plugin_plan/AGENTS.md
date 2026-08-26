# AGENTS.md — regras para qualquer LLM ou agente de código

## Missão

Implementar o Swim Coach de forma incremental, verificável e segura, obedecendo à fase atual e preservando os contratos do pacote de planejamento.

## Antes de editar código

1. Leia `README.md`, `MASTER_PLAN.md` e `IMPLEMENTATION_STATUS.md`.
2. Descubra a primeira fase elegível.
3. Leia o arquivo da fase, o prompt correspondente, os ADRs e os documentos listados no `docs/20-context-map.md`.
4. Inspecione o repositório real; não suponha que o esqueleto já exista.
5. Registre qualquer divergência entre plano e código em `CHANGELOG.md` e, quando arquitetural, em um novo ADR.

## Escopo

- Implemente somente a fase solicitada.
- Não antecipe uma fase posterior “porque é fácil”.
- É permitido criar interfaces ou stubs necessários à fase atual, mas não lógica futura simulada como concluída.
- Não marque uma tarefa como concluída sem evidência reproduzível.

## Invariantes de domínio

- Piscina inicial: 20 m.
- Meta inicial: 2.000 m em 2.700 s; ritmo-alvo 135 s/100 m.
- Etapa baseada em distância deve ser múltipla do tamanho da piscina ativa.
- Revisões de treino publicadas são imutáveis; mudanças criam nova revisão.
- FIT bruto é preservado e normalizado de forma idempotente.
- Payload específico Garmin não atravessa a porta do provider.
- A conversa/Skill nunca é fonte de verdade do estado de treino.
- Métricas clínicas não são diagnósticos.

## Invariantes de segurança

- Nunca commitar senha, token, FIT real, e-mail privado ou segredo.
- Nunca registrar tokens ou credenciais em logs.
- Dados privados e ferramentas de escrita exigem autenticação e escopo.
- Na superfície v2 pessoal, a própria chamada `publish_workout` expressa a
  intenção de efeito externo; proposta/hash/aprovação não são expostos. O
  servidor ainda exige autenticação, ownership, idempotência derivada, auditoria
  e reconciliação, conforme ADR-0011.
- Uma anotação MCP não substitui validação, autorização nem confirmação.
- O modelo não recebe FIT bruto, tokens Garmin ou payloads externos desnecessários.
- O login Garmin ocorre por bootstrap seguro; a senha não é persistida.

## Arquitetura

- Monólito modular Python; dependências apontam para o domínio, nunca ao contrário.
- REST, MCP e worker reutilizam os mesmos serviços de aplicação.
- `GarminProvider` é uma porta. A biblioteca não oficial é detalhe de infraestrutura.
- Jobs e outbox usam PostgreSQL até nova ADR.
- A PWA não contém chat no MVP.
- Skills orquestram workflows; ferramentas MCP fornecem dados e ações controladas.
- Toda ferramenta MCP deve funcionar sem UI customizada.

## Qualidade

- Código tipado e testado.
- Migrações forward e downgrade quando tecnicamente seguras.
- Erros públicos usam catálogo estável e `correlation_id`.
- Datas/horários em UTC internamente; timezone do usuário na borda.
- Dinheiro, duração, distância e ritmo não usam unidades implícitas.
- IDs externos nunca são usados como PK interna.
- APIs públicas não exigem chaves técnicas do usuário. Idempotência e controle
  de concorrência são derivados no servidor quando aplicável.

## Entrega de fase

Ao concluir:

1. rode todos os comandos de verificação definidos na fase;
2. salve evidências no bloco da fase em `IMPLEMENTATION_STATUS.md`;
3. atualize `implementation-status.json`;
4. atualize `CHANGELOG.md`;
5. liste arquivos alterados, testes executados, migrações e riscos restantes;
6. não esconda falhas nem use mocks como evidência de integração real;
7. deixe o repositório executável para o próximo agente.

## Quando o plano estiver incorreto

Não contorne silenciosamente. Faça a menor mudança segura, escreva uma ADR com contexto, alternativas, decisão e consequências, atualize os documentos afetados e preserve rastreabilidade.
