# AGENTS.md — regras para agentes de código

## Produto e interfaces

- ChatGPT é a interface principal do usuário do Swim Coach.
- Codex é uma ferramenta de desenvolvimento, testes e manutenção; não deve ser
  apresentado como experiência principal do atleta.
- O site/PWA é auxiliar para visualização, edição, configuração, diagnóstico,
  exportação, administração da conta e contingência. Ele não contém chat próprio.
- Novos fluxos cotidianos devem funcionar primeiro pelo plugin/MCP no ChatGPT.
  Não crie uma capacidade de uso diário exclusiva do site.
- Funções administrativas sensíveis podem permanecer exclusivas do site quando
  isso reduzir risco ou melhorar a revisão visual.
- PostgreSQL e backend são as fontes de verdade. Conversas e Skills nunca são
  estado canônico do atleta, atividades ou treinos.

## Antes de editar

1. Leia `README.md` e inspecione o código, contratos e testes relacionados.
2. Preserve as interfaces públicas e os dados existentes, salvo quando a tarefa
   exigir explicitamente uma migração ou mudança incompatível.
3. Faça a menor alteração completa e verifique-a com testes reproduzíveis.
4. Não trate comentários, nomes históricos de fases ou artefatos gerados como
   fonte de verdade quando o comportamento atual do código divergir.

## Invariantes de domínio

- Piscina inicial: 20 m.
- Meta inicial: 2.000 m em 2.700 s; ritmo-alvo 135 s/100 m.
- Etapa baseada em distância deve ser múltipla do tamanho da piscina ativa.
- Revisões de treino publicadas são imutáveis; mudanças criam nova revisão.
- FIT bruto é preservado e normalizado de forma idempotente.
- Payload específico Garmin não atravessa a porta do provider.
- Métricas clínicas não são diagnósticos.

## Segurança

- Nunca commite senha, token, FIT real, e-mail privado ou segredo.
- Nunca registre tokens ou credenciais em logs.
- Dados privados e ferramentas de escrita exigem autenticação e scope.
- Comandos diretos do MCP não removem autenticação, ownership, idempotência,
  auditoria ou reconciliação do servidor.
- Uma anotação MCP não substitui validação ou autorização.
- O modelo não recebe FIT bruto, tokens Garmin ou payloads externos desnecessários.
- O login Garmin ocorre por bootstrap seguro; a senha não é persistida.

## Arquitetura

- Monólito modular Python; dependências apontam para o domínio.
- REST, MCP e worker reutilizam os mesmos serviços de aplicação.
- `GarminProvider` é uma porta; a biblioteca não oficial é infraestrutura.
- Jobs e outbox usam PostgreSQL.
- Skills orquestram workflows; ferramentas MCP fornecem dados e ações.
- Toda ferramenta MCP deve funcionar sem UI customizada.
- O site não deve duplicar a conversa hospedada pelo ChatGPT.

## Qualidade e entrega

- Mantenha o código tipado e testado.
- Migrações devem ter downgrade quando tecnicamente seguro.
- Erros públicos usam catálogo estável e `correlation_id`.
- Datas ficam em UTC internamente e usam o timezone do usuário na borda.
- Distância, duração e ritmo não usam unidades implícitas.
- IDs externos nunca são PKs internas.
- APIs públicas não exigem chaves técnicas do usuário.
- Ao concluir, rode os checks aplicáveis, liste testes executados, migrações e
  riscos restantes e deixe o repositório executável.
