# Ciclos, metas e agenda confiáveis

ChatGPT prescreve; os serviços validam e persistem. O fluxo de propostas existente
continua único. Este documento descreve mudanças de software; não cria um ciclo
nem publica treinos reais do atleta.

## Diagnóstico comprovado e solução

| Problema | Causa no código anterior | Alteração mínima | Teste / prioridade |
|---|---|---|---|
| Pausa não libera novo ciclo | `get_live` inclui ACTIVE e PAUSED, mas erro orientava pausar | Sucessor explícito com predecessor, versão, diff e aprovação atômica | `test_coaching_lifecycle`, P0 |
| Plano vencido continua ativo | Estado não considera data local na leitura | `lifecycle_state` derivado ENDED_NEEDS_REVIEW, sem encerrar automaticamente | domínio e integração, P0 |
| Concluir não acessível | Serviço/MCP só aceitavam pausa/retomada | COMPLETED/CANCELLED explícitos, pausa distinta e replay sem efeito | domínio/integração, P0 |
| Meta e título histórico confundidos | Plano aponta para meta mutável sem snapshot | Snapshot do objetivo para novos ciclos, meta atual versionada e relação CURRENT/PREVIOUS_OR_UNVERIFIED | meta 1000/1380=138, P0 |
| Semana seguinte escolhida por engano | Nenhum resolvedor comum de datas relativas | CalendarRequest com período, weekday explícito, data local e timezone | 02/11→03/11 e 05/11, DST, ano/mês, P0 |
| Movimentação exigia várias escritas | `save_workout` + publicação eram transações separadas | `reschedule_workout` grava revisão, agenda, auditoria/outbox e job juntos | move publicado preserva identidade, P0 |
| Atualização remota antiga pode sobrescrever data nova | Job validava revisão, mas não data local | Worker rejeita job com data obsoleta | integração Garmin, P0 |
| Avulso não pode ser incorporado | Binding existia apenas na materialização | Associação exata ao intento aprovado, sem republicar; materialização serializada | adoção/concorrência, P0 |
| Calendário depende de revisão esportiva | Só ADAPTATION e MATERIALIZATION | RESCHEDULE preserva conteúdo e usa mesma proposta/hash | validador, P1 |
| Erro de schema difícil de reparar | Falha Pydantic antes do envelope e REST só contava erros | Paths, ação, dica e no máximo um retry; exemplos step_role e duração | contrato e repair, P1 |
| Tempo subestimado | Distância sem pace contribuía zero no total parcial | Faixa por targets + pausas, quantidade sem pace e duração incompleta explícita | 1040 m = 1836–2148 s no fixture, P1 |
| Queued confundido com sucesso | Job e binding separados sem consulta v2 por treino | Status por lote com estado local/job/remoto e último ack confirmado | batch/status, P1 |
| 403 confundido com Garmin | Sem classificação por camada/evidência | diagnose_connection + runbook; edge só com firewallCustom/origin=0 | diagnóstico, P1 |
| Conta errada em escrita | Scope garantia ownership, mas agente podia trocar conexão | account_ref estável e expected_account_ref nas escritas | erro ACCOUNT_MISMATCH antes da mutação, P1 |

Já existiam e foram preservados: CanonicalWorkout com `step_role`; alinhamento à
parede; FIT bruto e normalização versionada; feedback ATHLETE; evidência de
execução independente do desempenho; FC por bloco/zonas; revisões imutáveis;
controle otimista, jobs, outbox e auditoria; provider por porta e kill switches.
Não há um novo planejador, ruleset esportivo ou chat no PWA.

## Jornadas MCP

1. `get_coach_context` ou `get_coach_operations`: confirmar conta, meta atual,
   ciclo, atividades recentes e horários. A disponibilidade vem do banco.
2. `preview_calendar`: informar a intenção temporal, por exemplo TOMORROW e
   THIS_WEEK/THURSDAY. Mostrar datas absolutas antes de salvar/publicar.
3. Volta de viagem/meta nova: `set_current_goal` se solicitado; elaborar um
   sucessor completo usando `predecessor_plan_id` e versão atual. A proposta não
   fecha o anterior. O diff explicita que futuras sessões locais são retiradas
   desde o início do sucessor e que o Garmin não é alterado.
4. Exibir diff/hash, obter aprovação exata e usar `apply_plan_revision`. O commit
   encerra/supersede o anterior e ativa o sucessor na mesma transação.
5. Usar `associate_workout_to_plan` para aproveitar um avulso publicado cujo
   conteúdo/piscina/data/hora coincidam com o intento aprovado. Uma materialização
   puramente local pode ser arquivada; materialização com estado externo é
   protegida. Histórico de publicações/execuções do avulso permanece intacto.
6. Mudança apenas de data numa sessão de ciclo: deep-copy de `data.revision`,
   `kind=RESCHEDULE`, nenhuma alteração esportiva, proposta e aprovação. Semanas
   passadas, sessões realizadas e metadados continuam imutáveis. Para cruzar
   semanas ou alterar duração do ciclo, propor sucessor quando necessário.
7. `publish_workout`/`publish_workouts` só após pedido expresso. Primeiro consultar
   `get_publication_status` para avisos de conversão Garmin. Depois consultar de
   novo para confirmar cada item; queued não significa publicado.
8. Avulso já publicado: prévia → `reschedule_workout` com versão/hash de agenda →
   `get_publication_status`. Falha remota mantém agenda local e estado pendente.
   Para desfazer antes de executar, mover a mesma identidade à data original.

O servidor não controla a lista de conexões do host ChatGPT. A Skill mantém a
conexão escolhida e envia a referência obtida no preflight; mismatch bloqueia a
escrita. Clientes antigos mantêm compatibilidade com o parâmetro opcional.

## Contratos e telas

- Migração **000018**, aditiva: predecessor FK RESTRICT e snapshot JSON do
  objetivo; estados SUPERSEDED e tipo RESCHEDULE. Snapshots antigos vazios
  significam informação histórica não verificada; não reconstruímos um objetivo
  passado usando a meta atual.
- MCP mantém scope coach e adiciona visão operacional, calendário, status,
  reagendamento, meta, adoção, lote, validação e diagnóstico.
- REST `/api/v1/coaching/overview`, `/calendar/preview`,
  `/workouts/{id}/reschedule`, `/publication-status` usam os mesmos serviços.
- PWA: ciclo e meta distintos, próxima sessão, agenda, piscina, avulso/ciclo,
  confirmação Garmin, pendências e preview antes de reagendar. Não contém chat.
- Estimativas conhecidas incluem pausas e extremos dos targets. Etapas sem pace
  ou abertas deixam `duration_complete=false` e teto desconhecido. O total
  numérico histórico é preservado; limites derivados são calculados na leitura.
  O coach deve fornecer ritmo/faixa ou estimativa explícita antes de garantir
  encaixe numa janela de 45 minutos; não existe pace implícito.

## P2: ergonomia e observabilidade

A prévia aceita lote semanal sem efeitos, conflitos e hash de agenda. Desfazer
é uma nova revisão da mesma identidade. Overview expõe timeline de ciclos,
origem dos treinos e pendências; o diagnóstico existente mantém métricas de fila
e invocações MCP por ferramenta/código/latência. Notificações deduplicadas cobrem
falha terminal/ambígua e recuperação Garmin. Não foi adicionado outro dashboard.
Eventos de borda só podem ser medidos no Cloudflare; ver o runbook.

## Rollback e limites operacionais

O pipeline existente faz dump PostgreSQL, verifica o catálogo com pg_restore,
retém imagens anteriores e somente então migra. Para rollback imediato antes do uso dos novos estados,
manter o schema aditivo 000018 e restaurar imagens anteriores conforme
`ops/deploy-vm.sh`. Depois de gravar SUPERSEDED/RESCHEDULE, o binário antigo
não entende esses valores: preferir correção para frente; qualquer recuperação
por backup exige validação isolada e decisão explícita sobre dados posteriores.
Downgrade de schema recusa execução quando há snapshots,
linhagem ou revisões RESCHEDULE: restaurar um backup verificado em ambiente
isolado e validar antes de qualquer recuperação de dados. Não descartar esses
dados para satisfazer uma constraint antiga.

A regra Cloudflare real não vive neste repositório e não pode ser alterada por
uma mudança de backend. Não há credencial Cloudflare no fluxo de release. O
runbook orienta uma correção restrita do endpoint autenticado, sem desligar WAF.
