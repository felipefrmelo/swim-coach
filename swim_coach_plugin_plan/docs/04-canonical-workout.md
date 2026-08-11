# Modelo canônico de treino

O modelo interno não deve copiar o formato do Garmin. Ele representa o significado do treino e é compilado para cada provider.

## 1. Exemplo canônico

```json
{
  "schema_version": 1,
  "name": "Técnica + ritmo — 1.600 m",
  "sport": "pool_swim",
  "objective": "Manter técnica estável e desenvolver ritmo sustentável",
  "pool_length_m": 20,
  "estimated_total_seconds": 2520,
  "nodes": [
    {
      "node_type": "step",
      "order": 1,
      "kind": "warmup",
      "end": {"type": "distance", "value": 200, "unit": "meter"},
      "stroke": "freestyle",
      "target": {"type": "rpe", "min": 2, "max": 3},
      "instruction": "Leve e alongado"
    },
    {
      "node_type": "repeat",
      "order": 2,
      "iterations": 4,
      "children": [
        {
          "node_type": "step",
          "order": 1,
          "kind": "drill",
          "end": {"type": "distance", "value": 40, "unit": "meter"},
          "stroke": "drill",
          "instruction": "Educativo definido no app"
        },
        {
          "node_type": "step",
          "order": 2,
          "kind": "recovery",
          "end": {"type": "distance", "value": 40, "unit": "meter"},
          "stroke": "freestyle",
          "target": {"type": "rpe", "min": 2, "max": 3}
        }
      ]
    },
    {
      "node_type": "repeat",
      "order": 3,
      "iterations": 4,
      "children": [
        {
          "node_type": "step",
          "order": 1,
          "kind": "main",
          "end": {"type": "distance", "value": 100, "unit": "meter"},
          "stroke": "freestyle",
          "target": {
            "type": "pace_range",
            "min_seconds_per_100m": 140,
            "max_seconds_per_100m": 150
          }
        },
        {
          "node_type": "step",
          "order": 2,
          "kind": "rest",
          "end": {"type": "time", "value": 20, "unit": "second"}
        }
      ]
    },
    {
      "node_type": "repeat",
      "order": 4,
      "iterations": 4,
      "children": [
        {
          "node_type": "step",
          "order": 1,
          "kind": "interval",
          "end": {"type": "distance", "value": 80, "unit": "meter"},
          "stroke": "freestyle",
          "target": {"type": "rpe", "min": 7, "max": 8}
        },
        {
          "node_type": "step",
          "order": 2,
          "kind": "rest",
          "end": {"type": "time", "value": 20, "unit": "second"}
        }
      ]
    },
    {
      "node_type": "repeat",
      "order": 5,
      "iterations": 4,
      "children": [
        {
          "node_type": "step",
          "order": 1,
          "kind": "interval",
          "end": {"type": "distance", "value": 40, "unit": "meter"},
          "stroke": "freestyle",
          "target": {"type": "rpe", "min": 8, "max": 9}
        },
        {
          "node_type": "step",
          "order": 2,
          "kind": "rest",
          "end": {"type": "time", "value": 30, "unit": "second"}
        }
      ]
    },
    {
      "node_type": "step",
      "order": 6,
      "kind": "cooldown",
      "end": {"type": "distance", "value": 200, "unit": "meter"},
      "stroke": "freestyle",
      "target": {"type": "rpe", "min": 1, "max": 2}
    }
  ]
}
```

Distância total:

```text
200 + 4×(40+40) + 4×100 + 4×80 + 4×40 + 200 = 1.600 m
```

## 2. Invariantes obrigatórias

1. `pool_length_m > 0`.
2. Toda etapa cujo fim é distância deve satisfazer:

```text
distance_m % pool_length_m == 0
```

3. Para Felipe, o padrão é `pool_length_m = 20`.
4. Distância total é derivada; nunca digitada como única fonte.
5. Repetições devem ser inteiras e positivas.
6. O treino deve ter ao menos uma etapa executável.
7. `pace_range.min <= pace_range.max`.
8. Descanso não contribui para a distância.
9. Uma revisão validada não é alterada; cria-se nova revisão.
10. Recursos não suportados pelo Garmin geram erro ou warning explícito; nunca são descartados silenciosamente.

## 3. Validação em camadas

### Validação sintática

- tipos corretos;
- campos obrigatórios;
- enums válidos;
- JSON schema/Pydantic.

### Validação de domínio

- múltiplos da piscina;
- totais coerentes;
- ordem dos passos;
- repetições;
- duração e ritmo positivos;
- fase e objetivo compatíveis.

### Validação de capacidade

- tipo de alvo suportado;
- profundidade de repetição suportada;
- limite de passos;
- tamanho do nome;
- compatibilidade com natação em piscina;
- suporte do dispositivo.

### Validação de segurança esportiva

- volume e intensidade contra política configurada;
- existência de aquecimento e soltura em sessões intensas;
- restrições ativas;
- dor reportada recentemente;
- bloqueios manuais.

## 4. Compilação

```text
WorkoutDefinition
    ↓ validate_domain
ValidatedWorkout
    ↓ apply_device_capabilities
ProviderCompatibleWorkout
    ↓ GarminWorkoutCompiler
GarminWorkoutDTO
    ↓ serialize
Payload Garmin
```

O compilador é determinístico: a mesma revisão e a mesma matriz de capacidade geram o mesmo hash de payload.

---

## 5. Regras adicionais Plugin-first

- Skills nunca montam payload Garmin diretamente; elas chamam `create_workout_draft` ou ferramentas de proposta.
- O MCP aceita o schema canônico versionado em `contracts/canonical-workout.schema.json`.
- O resultado de preview devolve totais e warnings suficientes para confirmação headless.
- `WorkoutRevision` usada em uma proposta é referenciada por ID + `content_hash`; qualquer edição invalida a proposta anterior.
- O compilador Garmin recebe apenas revisão aprovada e `DeviceCapabilityMatrix` atual.

## 6. Exemplo inicial para piscina de 20 m

```json
{
  "schema_version": "1.0",
  "title": "Técnica e base 1.600 m",
  "sport": "POOL_SWIMMING",
  "pool_length_m": 20,
  "purpose": "TECHNIQUE_BASE",
  "nodes": [
    {
      "type": "step",
      "id": "warmup",
      "end_condition": {"type": "distance", "meters": 200},
      "target": {"type": "none"},
      "stroke": {"type": "freestyle"},
      "intensity": "EASY"
    },
    {
      "type": "repeat",
      "id": "drills",
      "repetitions": 4,
      "children": [
        {
          "type": "step",
          "end_condition": {"type": "distance", "meters": 40},
          "stroke": {"type": "drill", "drill": "CATCH_UP"},
          "target": {"type": "rpe", "min": 3, "max": 4}
        },
        {
          "type": "step",
          "end_condition": {"type": "time", "seconds": 20},
          "step_role": "REST"
        }
      ]
    },
    {
      "type": "repeat",
      "id": "main",
      "repetitions": 8,
      "children": [
        {
          "type": "step",
          "end_condition": {"type": "distance", "meters": 100},
          "stroke": {"type": "freestyle"},
          "target": {"type": "pace_range", "min_seconds_per_100m": 145, "max_seconds_per_100m": 155}
        },
        {
          "type": "step",
          "end_condition": {"type": "time", "seconds": 20},
          "step_role": "REST"
        }
      ]
    },
    {
      "type": "step",
      "id": "cooldown",
      "end_condition": {"type": "distance", "meters": 440},
      "target": {"type": "none"},
      "intensity": "EASY"
    }
  ]
}
```

O validador deve detectar totais, múltiplos de 20, limites do Garmin, inconsistências de targets e ausência de aquecimento/soltura como warning configurável.
