# Checkpoint semanal do coach

O incremento conecta o relato do atleta à revisão já existente. Não introduz
um segundo gerador de treinos, editor de FIT ou publicação automática.

## Fluxo no ChatGPT

1. Consultar contexto, plano e sessões recentes.
2. Explicar o propósito e o foco técnico da próxima sessão usando a prescrição
   aprovada, com um critério observável de sucesso. Não inventar conteúdo ausente.
3. Após nadar, aproveitar RPE e sensação importados. Perguntar somente o contexto
   relevante que falta, uma pergunta por vez, e salvar quando solicitado.
4. Ao revisar uma semana encerrada ou resolvida, consumir `coach_checkpoint` de
   `review_training_plan`: execução, resposta do atleta, confiabilidade e dúvidas.
5. O ChatGPT escolhe manter, progredir ou aliviar e explica o motivo. Se houver
   alteração, propõe a revisão completa e aguarda a aprovação exata. Publicar no
   Garmin continua exigindo pedido separado. Não inferir capacidade de 2.000 m
   a partir de tiros curtos; comparar blocos sustentados e equivalentes.

Esse fluxo é sob demanda. Não há novo agendamento, revisão automática em segundo
plano nem alteração das sessões reais durante o desenvolvimento.

## Check-in opcional

`save_feedback` aceita `check_in` com:

| Campo | Significado |
|---|---|
| `completed_as_planned` | O atleta confirmou conclusão integral, parcial ou ainda não informou (`null`). |
| `watch_data_accurate` | O atleta considera o registro correto, incorreto ou não avaliou. |
| `all_freestyle` | Relato sobre o estilo executado, sem sobrescrever a classificação Garmin. |
| `main_difficulty` | Contexto técnico/execução opcional, limitado a 500 caracteres. |

Um erro do relógio não confirma conclusão. A confirmação de conclusão não cria
distância medida, ritmo corrigido, descanso estimado ou carga sRPE. A informação
de estilo também não reclassifica automaticamente comprimentos.

Exemplo sintético:

```json
{
  "activity_id": "<ID interno obtido em get_swims>",
  "check_in": {
    "completed_as_planned": true,
    "watch_data_accurate": false,
    "main_difficulty": "Respiração nas últimas repetições"
  }
}
```

No MCP, um salvamento somente de `check_in` preserva RPE, sensação, dor, técnica
e notas anteriores. Campos omitidos dentro de `check_in` são preservados; `null`
explícito limpa um campo. O restante de `save_feedback` mantém a semântica
anterior de substituição da avaliação: para atualizações de avaliação combinadas,
ler e reenviar os valores que devem permanecer.

No REST v2, `check_in` omitido preserva o anterior; quando enviado substitui o
objeto completo, e `null` remove-o. O painel reenvia o formulário completo. Seu
botão de remoção também elimina o check-in. Pedidos antigos e filas offline sem
esse campo não o apagam inadvertidamente.

## Evidência semanal

- `execution_evidence` acompanha as leituras de atividades, inclusive no contexto.
- `coach_checkpoint.execution` separa presença registrada, conclusão confirmada,
  execução parcial e ausência de confirmação.
- `coach_checkpoint.athlete_response` mostra a avaliação atual e a dificuldade.
- `coach_checkpoint.measurement` identifica as atividades com desempenho excluído.
- `missing_context` aponta perguntas pendentes; não obriga preencher formulário.
- O backend não escolhe uma decisão (`decision: null`).

Se `watch_data_accurate=false`, as métricas de ritmo, distância comparativa,
continuidade, estilo, sets e carga são retiradas da entrada de adaptação daquela
atividade. RPE e sensação continuam disponíveis, com origem explícita. A razão de
aderência de distância da semana fica `null` se houver atividade contestada.
`executed_distance_m` permanece o total bruto com
`distance_basis=RECORDED_GARMIN_UNCORRECTED`, não uma medida corrigida.

`watch_data_accurate=true` não promove qualidade baixa para alta. Os demais
critérios de qualidade e comparabilidade continuam necessários. Revisões já
persistidas são imutáveis; depois de um novo relato, solicitar nova revisão para
obter um novo snapshot. Notas históricas não são convertidas automaticamente em
confirmações estruturadas.

## Entrega e reversão

- Migração `000016`: adiciona uma coluna JSONB anulável a `session_feedback`.
- A mesma identidade, autorização, auditoria, versionamento e idempotência de
  feedback continuam em uso. FIT e payload Garmin não são alterados.
- Exportação de dados inclui o check-in estruturado.
- O downgrade funciona sem check-ins; com relatos persistidos, recusa a operação
  para evitar perda silenciosa de dados. Fazer backup antes de migrar produção.
- Fazer smoke autenticado com uma atividade sintética: salvar, reler, revisar e
  verificar que não houve escrita Garmin. Não usar treinos reais como canários.
