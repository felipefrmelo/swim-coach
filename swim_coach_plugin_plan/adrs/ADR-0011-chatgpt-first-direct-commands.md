# ADR-0011 — ChatGPT-first com comandos diretos e segurança invisível

- **Status:** Accepted
- **Data:** 2026-08-26
- **Substitui:** ADR-0004 na interface de produto

## Contexto

O fluxo P07/P08 expôs ao usuário detalhes de implementação — proposal, hash,
aprovação, execução e chaves idempotentes — e transformou tarefas comuns em
várias rodadas de conversa. No uso pessoal isso impediu a função principal do
produto: pedir ao ChatGPT para criar, editar, agendar ou publicar um treino de
forma natural. A PWA também repetiu o mesmo protocolo e passou a competir com a
conversa em vez de auxiliá-la.

## Decisão

O ChatGPT é a interface primária e a PWA é uma ferramenta visual auxiliar. A
superfície MCP pública passa a oferecer poucos comandos orientados a intenção:

1. `get_coach_context`;
2. `get_workouts`;
3. `get_swims`;
4. `save_workout`;
5. `publish_workout`;
6. `generate_week`;
7. `sync_garmin`;
8. `save_feedback`.

Todos usam um único escopo customizado `coach`. Criar, editar e agendar estado
local não exige confirmação adicional. `publish_workout` representa a intenção
explícita de publicar e executa/agenda em uma única tool call. A plataforma pode
continuar apresentando a confirmação que deriva das annotations de efeito
externo, mas o Swim Coach não adiciona outra cerimônia.

As seguintes proteções permanecem obrigatórias e invisíveis:

- autenticação e ownership;
- credenciais Garmin criptografadas;
- validação do modelo canônico e capacidades do dispositivo;
- revisões append-only;
- idempotência derivada no servidor;
- binding estável por treino e upsert no Garmin;
- jobs, auditoria e reconciliação de resultado ambíguo.

Proposal, action hash, approval, execution, expected revision e idempotency key
não fazem parte do contrato MCP v2 nem da experiência principal da PWA. As
tabelas P07/P08 podem ser lidas durante a migração e retenção histórica, mas não
são a fonte de autorização do novo fluxo.

## Consequências

- pedidos comuns passam de três a seis chamadas para uma chamada de intenção;
- o modelo escolhe entre oito ferramentas semanticamente distintas;
- uma reconexão OAuth é necessária para conceder `coach`;
- mutações concorrentes usam a revisão atual do servidor e continuam criando
  revisões imutáveis;
- efeitos Garmin continuam recuperáveis e deduplicados, sem expor o protocolo;
- clientes legados são descontinuados na major v2 e não são anunciados.

## Alternativas rejeitadas

- manter a superfície antiga e apenas mudar as Skills;
- juntar preview/approve/execute numa Skill ainda visível;
- remover idempotência, autenticação ou histórico por ser um sistema pessoal;
- fazer da PWA a interface principal.
