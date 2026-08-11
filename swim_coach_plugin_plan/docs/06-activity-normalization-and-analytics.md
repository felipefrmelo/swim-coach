# Normalização de atividades e analytics

## 1. Fonte de verdade

- Payload externo bruto: preservado.
- Arquivo FIT: preservado quando disponível.
- Modelo normalizado: usado pelo produto.
- Métricas derivadas: versionadas.

## 2. Pipeline

```mermaid
flowchart LR
    LIST[Listagem Garmin] --> SUMMARY[Resumo bruto]
    SUMMARY --> DETAIL[Detalhes Garmin]
    DETAIL --> FIT[Download FIT]
    FIT --> PARSE[Garmin FIT SDK]
    PARSE --> NORMALIZE[Normalizador]
    NORMALIZE --> ACT[(Activity)]
    ACT --> MATCH[Associação ao planejado]
    MATCH --> ANALYZE[Análise versionada]
    ANALYZE --> AGG[Agregados diário/semanal]
```

## 3. Mensagens FIT relevantes

O parser deve estar preparado para mensagens como:

- file_id;
- session;
- lap;
- length;
- record;
- event;
- device_info;
- activity;
- developer_data_id e field_description quando existirem.

Nem todo dispositivo ou firmware produzirá todos os campos. O normalizador deve tolerar ausência e registrar `completeness`.

## 4. Regras de normalização

- preferir valores explícitos da sessão quando coerentes;
- calcular distância por extensões × pool length quando necessário;
- preservar valor original e valor normalizado em caso de divergência relevante;
- não inventar braçadas ou frequência cardíaca ausentes;
- separar atividade, intervalo ativo e descanso;
- distinguir drill quando o FIT indicar;
- converter unidades para metros, segundos, bpm e segundos/100 m;
- manter timezone da atividade quando disponível;
- guardar versão do perfil FIT e versão do parser.

## 5. Storage

Interface:

```python
class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str, checksum: str) -> StoredObject: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str, checksum: str | None = None) -> bool: ...
```

Implementações:

- `FilesystemObjectStorage` para início;
- `S3ObjectStorage` para Magalu Object Storage ou outro S3 compatível.

Chave sugerida:

```text
garmin/{user_id}/activities/{external_activity_id}/{checksum}.fit
```

## 6. Reprocessamento

Quando `normalization_version` mudar:

1. selecionar atividades antigas;
2. ler FIT bruto;
3. gerar modelo novo em transação;
4. recalcular análises;
5. comparar resultados;
6. promover versão;
7. registrar auditoria.

---

## 7. Métricas básicas

### Ritmo

```text
pace_sec_per_100m = timer_seconds / distance_m × 100
```

### Meta

```text
2.000 m em 2.700 s
pace = 2.700 / 2.000 × 100 = 135 s/100 m = 2:15/100 m
```

### Conclusão de distância

```text
completion_ratio = actual_distance / planned_distance
```

Exibir o valor real; uma barra visual pode limitar em 100%, mas o dado não deve ser truncado.

### Carga sRPE

```text
session_load = duration_minutes × RPE
```

### Coeficiente de variação

```text
CV = desvio_padrão(ritmos) / média(ritmos)
```

Usar apenas séries comparáveis.

### Fade

```text
fade = (ritmo_médio_último_terço - ritmo_médio_primeiro_terço)
       / ritmo_médio_primeiro_terço
```

Valor positivo indica desaceleração.

## 8. Métricas por atividade

- distância;
- duração total, timer e movimento;
- ritmo médio;
- ritmo por intervalo;
- melhor ritmo comparável;
- descanso total e por repetição;
- frequência cardíaca média/máxima;
- braçadas por extensão;
- frequência de braçadas;
- SWOLF;
- consistência;
- fade;
- negative/positive split;
- carga sRPE;
- completude do dado;
- aderência ao planejado.

## 9. SWOLF

SWOLF deve ser comparado preferencialmente:

- na mesma piscina;
- no mesmo estilo;
- em esforço semelhante;
- em blocos comparáveis.

Como a piscina padrão é 20 m, comparações internas ficam mais consistentes, mas o app ainda deve mostrar contexto.

## 10. Associação planejado versus realizado

### Etapa 1 — candidatos

- mesmo usuário;
- mesmo esporte;
- data próxima;
- treino ainda não associado;
- atividade ainda não associada.

### Etapa 2 — score

```text
score =
  peso_data × proximidade_data
+ peso_distância × proximidade_distância
+ peso_duração × proximidade_duração
+ peso_horário × proximidade_horário
+ peso_estrutura × similaridade_intervalos
```

### Etapa 3 — decisão

- score alto: associação automática;
- score intermediário: sugerir ao usuário;
- score baixo: não associar.

### Etapa 4 — alinhamento de etapas

Expandir grupos de repetição em folhas e usar alinhamento por custo:

- diferença de distância;
- ordem;
- tipo de etapa;
- descanso;
- ritmo;
- possibilidade de extensão não detectada.

Uma abordagem de programação dinâmica evita exigir correspondência perfeita.

## 11. Aderência

A aderência deve ser multidimensional:

```json
{
  "distance": 1.0,
  "main_set_completion": 0.95,
  "pace_target": 0.82,
  "rest_target": 0.75,
  "structure": 0.91,
  "overall": 0.89
}
```

Não resumir tudo a um único percentual sem mostrar componentes.

## 12. Progresso da meta

Exibir:

- melhor 2.000 m;
- melhor ritmo sustentável comparável;
- tendência de 400 m, 1.000 m e 2.000 m;
- CSS atual;
- diferença para 2:15/100 m;
- volume semanal;
- consistência;
- confiança da estimativa.

Não prometer data de conclusão. Caso haja previsão, apresentar faixa e pressupostos.

## 13. Resumo semanal

Estrutura:

```json
{
  "planned_sessions": 3,
  "completed_sessions": 3,
  "planned_distance_m": 6200,
  "completed_distance_m": 6040,
  "completion_rate": 0.974,
  "average_rpe": 6.3,
  "hard_sessions": 1,
  "pain_flags": 0,
  "key_progress": ["Melhor regularidade no bloco de 100 m"],
  "attention_points": ["Descansos aumentaram no último bloco"],
  "next_week_recommendation": "Manter volume e progredir apenas uma série"
}
```

---

## 14. Contratos de reprodutibilidade

Cada `ActivityAnalysis` registra:

- `analysis_version`;
- `parser_version`;
- IDs/checksums dos inputs;
- configuração de piscina;
- regras de exclusão de pausas/valores inválidos;
- métricas e flags;
- warnings por campo ausente.

A análise nunca sobrescreve versão anterior; a “atual” é um ponteiro.

## 15. Métricas mínimas para respostas MCP

`get_swim_activity` pode expor:

- distância e duração;
- ritmo médio em movimento e total;
- splits/intervalos resumidos;
- consistência e fade;
- descansos;
- strokes/SWOLF se presentes;
- aderência ao planejado;
- feedback;
- qualidade/confiança dos dados;
- limites da interpretação.

Não expor FIT bruto nem arrays de centenas de extensões por padrão. Para detalhe, usar paginação ou recursos específicos.

## 16. Fórmulas normativas iniciais

```text
pace_100m = moving_seconds / distance_m * 100
completion_ratio = completed_distance / planned_distance
sRPE_load = session_minutes * RPE
fade_pct = (mean(last_segment) - mean(first_segment)) / mean(first_segment) * 100
CSS_sec_100m = (T400 - T200) / 2
```

Cada fórmula deve declarar arredondamento, tratamento de zero, amostra mínima e se “menor é melhor”.
