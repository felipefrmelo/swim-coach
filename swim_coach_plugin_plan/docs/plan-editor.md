# Visualização e edição de planos no PWA

A navegação **Planos** lista os ciclos do atleta e abre a prescrição completa,
semanas detalhadas/esboços/estratégia, sessões, blocos, metas de esforço, instruções
e histórico. O resumo da home também oferece acesso à tela.

Em ciclos ativos dentro do período, **Editar plano** permite modificar foco das
semanas elegíveis, objetivo/notas, agenda, duração e blocos das sessões. O editor
reutiliza os controles canônicos de treino. O total em metros acompanha os blocos.
O coach continua responsável pela prescrição: não há geração automática no PWA.

**Revisar alterações** valida e prepara uma proposta; somente **Aprovar e salvar
revisão** aplica o hash exato. Alterar o rascunho invalida a prévia. Cancelar descarta
as alterações locais. Conflitos de revisão exigem recarregar o plano. Nenhuma dessas
ações publica ou remove treinos Garmin; a materialização local é assíncrona.

REST autenticado:

- `GET /api/v1/coaching/plans/{id}`: documento, proteções e histórico da conta.
- `POST /api/v1/coaching/plans/{id}/proposals`: edição manual com motivo e revisão.
- `POST /api/v1/coaching/plans/{id}/apply`: proposta/hash e revisão esperada.

As escritas exigem sessão e CSRF e reutilizam `CoachCommandService` e
`TrainingCycleService`, com ownership, concorrência, auditoria e aprovação.
`MANUAL_EDIT` distingue alterações explícitas do atleta de decisões de adaptação
baseadas em revisão semanal. Não aceita `review_id` ou decisão esportiva. As
proteções de sessões concluídas, vinculadas a atividade e semanas passadas/revisadas
continuam no serviço, independentemente do estado exibido pelo frontend.

A identidade do ciclo não muda (meta, título, início, duração, timezone). Para
alterar esses campos ou um ciclo encerrado, criar um sucessor pelo treinador.
Semanas não detalhadas exibem seu planejamento; não geramos exercícios ausentes.

Migração `000019`: amplia apenas a constraint dos tipos de revisão. Downgrade
recusa revisões manuais persistidas, evitando perda de histórico. Sem alteração
em tabelas de atividades, FIT ou dados Garmin.

Validação local: testes de interface, contrato, domínio, rotas, lint, tipos e build.
O teste PostgreSQL de proposta/aplicação/histórico está em
`test_coaching_lifecycle.py`; requer o ambiente de integração com Docker.
