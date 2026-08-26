# Skills do plugin

## 1. Filosofia

Cada Skill representa um objetivo reconhecível, não uma ferramenta individual. A descrição é o gatilho; o corpo contém passos, condições, tratamento de falhas e formato final. Skills não inventam dados e não executam regras de domínio.

Na versão 2.0, Skills podem executar diretamente a intenção claramente pedida.
Editar usa `save_workout`; publicar usa `publish_workout`; planejar usa
`generate_week`; sincronizar usa `sync_garmin`. Não há confirmação obrigatória
em outro turno, proposal, hash, aprovação ou execução. A Skill pergunta apenas
quando falta identificação, data ou outro dado que altere materialmente a ação.

## 2. Catálogo

### `review-latest-swim`

**Gatilhos:** analisar, revisar ou explicar a última natação ou uma atividade específica.

Fluxo:

1. obter atividade pedida; se não houver ID, listar a mais recente;
2. buscar detalhe e analytics;
3. verificar qualidade/staleness;
4. comparar com treino planejado quando houver match;
5. destacar 2–4 fatos, não despejar métricas;
6. separar observação de inferência;
7. sugerir feedback se estiver ausente;
8. nunca diagnosticar dor.

### `plan-swim-week`

**Gatilhos:** montar, planejar, reorganizar ou revisar uma semana.

Fluxo:

1. obter contexto, meta, disponibilidade, semana atual e métricas recentes;
2. checar sync stale;
3. chamar `propose_week_plan`;
4. apresentar volume, objetivos por sessão, diferenças e warnings;
5. não aprovar/publicar;
6. permitir revisão por proposta de mudança.

### `adapt-workout`

**Gatilhos:** reduzir, alongar, trocar foco, reagendar por tempo/energia/disponibilidade.

Fluxo:

1. resolver workout;
2. transformar pedido em restrições estruturadas;
3. chamar `propose_workout_change` ou `propose_workout_reschedule`;
4. mostrar antes/depois e o que foi preservado;
5. pedir confirmação apenas quando houver ação posterior.

### `publish-to-garmin`

**Gatilhos:** enviar/publicar/agendar treino no Garmin.

Fluxo obrigatório:

1. resolver treino e revisão;
2. chamar preview;
3. mostrar título, distância, data, device e warnings;
4. pedir confirmação explícita;
5. somente após confirmação, aprovar hash exato;
6. executar;
7. acompanhar job quando assíncrono;
8. relatar IDs/estado sem dizer “deu certo” antes da confirmação do backend.

### `post-swim-checkin`

**Gatilhos:** registrar sensação, esforço, dor, técnica ou observação após treino.

Fluxo:

1. resolver atividade;
2. perguntar somente campos ausentes necessários;
3. estruturar RPE 1–10, técnica, dor e nota;
4. confirmar resumo quando houver dor ou correção relevante;
5. chamar `record_session_feedback`;
6. responder com registro, não prescrição.

### `goal-progress`

**Gatilhos:** progresso para 2 km/45 min, tendência, distância até a meta.

Fluxo:

1. obter meta e progresso;
2. explicar ritmo-alvo 2:15/100 m;
3. mostrar evidência e tamanho da amostra;
4. distinguir velocidade de capacidade de sustentar 2 km;
5. evitar previsão absoluta quando dados insuficientes.

### `diagnose-sync`

**Gatilhos:** atividade ausente, Garmin não sincronizou, job falhou, dados atrasados.

Fluxo:

1. obter status;
2. identificar conexão, cursor, último sucesso e jobs;
3. se seguro, oferecer `sync_garmin_activities`;
4. acompanhar job;
5. recomendar reconexão somente quando necessário;
6. nunca pedir senha no chat.

## 3. Regras comuns

- usar datas absolutas quando houver ambiguidade;
- usar timezone do backend;
- citar números retornados pela ferramenta;
- dizer quando dados estão incompletos;
- não inferir confirmação;
- não chamar approve/execute no mesmo turno sem confirmação humana observável;
- não repetir tool calls que já retornaram um job em andamento;
- preferir uma resposta clara a uma tabela enorme;
- português brasileiro por padrão.

## 4. Falhas e fallback

| Situação | Comportamento da Skill |
|---|---|
| sem atividade | explicar e oferecer sync |
| sync stale | mencionar data e oferecer sync |
| analytics parcial | usar somente métricas disponíveis |
| Garmin down | não gerar sucesso fictício; preservar proposal/job |
| auth ausente | orientar conexão/autorização |
| proposta expirada | criar novo preview |
| revisão mudou | buscar nova revisão e reapresentar impacto |
| dor relevante | registrar e recomendar cautela/profissional, sem diagnóstico |
| UI não suportada | continuar em texto com structured content |

## 5. Evals por Skill

Cada Skill possui ao menos:

- 5 prompts diretos;
- 5 indiretos/paráfrases;
- 3 follow-ups;
- 3 casos de dados ausentes;
- 3 casos de auth/erro;
- 3 prompts adversariais pedindo bypass de confirmação;
- asserts sobre tools chamadas, ordem, ausência de tools indevidas e conteúdo obrigatório.

## 6. Versionamento

Frontmatter mínimo:

```yaml
---
name: review-latest-swim
description: Review and explain the user's latest or selected pool swim using Swim Coach data, including planned-versus-completed comparison when available.
---
```

Versão fica no release do plugin/Skill, não escondida na descrição. Mudanças de workflow que afetem segurança exigem changelog e eval completa.
