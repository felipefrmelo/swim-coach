# Motor de planejamento e adaptação

## 1. Responsabilidade

O motor não é um modelo de linguagem. Ele é um conjunto de políticas determinísticas e configuráveis que:

- recebe estado atual;
- monta ou valida uma estrutura;
- calcula totais;
- aplica limites;
- produz explicações estruturadas.

A IA pode sugerir parâmetros ou selecionar opções, mas não ultrapassa as regras do motor.

## 2. Entradas

- perfil do atleta;
- piscina e dispositivo;
- meta ativa;
- disponibilidade;
- plano e fase atual;
- volume recente;
- treinos concluídos e perdidos;
- testes e CSS;
- feedback RPE;
- técnica e dor;
- prontidão;
- preferências do plugin/planejador;
- limites configurados.

## 3. Saídas

- rascunho de plano;
- semana de treino;
- sessão estruturada;
- proposta de ajuste;
- justificativa;
- impactos;
- warnings;
- verificações de segurança.

## 4. Tipos de sessão

| Tipo | Objetivo principal |
|---|---|
| `technique` | eficiência, respiração, posição e braçada |
| `aerobic_endurance` | sustentar volume confortável |
| `threshold_css` | desenvolver ritmo próximo à CSS |
| `speed` | potência e velocidade curta |
| `race_pace` | especificidade para 2 km/45 min |
| `recovery` | recuperação ativa |
| `assessment` | teste de 200 m, 400 m, 1.000 m ou 2.000 m |
| `open_water` | futuro, fora do núcleo da piscina |

## 5. Fases do plano

- `baseline`: coleta de dados e testes;
- `base`: técnica e volume sustentável;
- `build`: progressão de volume e intensidade;
- `specific`: foco no ritmo-alvo;
- `taper`: redução de carga antes do teste/prova;
- `recovery`: descarga;
- `assessment`: avaliação;
- `maintenance`: manutenção após a meta.

## 6. Regras configuráveis

Não codificar uma regra universal como verdade. Criar `TrainingPolicy` com:

```json
{
  "max_sessions_per_week": 3,
  "min_hours_between_hard_sessions": 36,
  "max_weekly_volume_increase_pct": 8,
  "recovery_week_frequency": 4,
  "recovery_week_reduction_pct": 20,
  "require_warmup_for_intense_workout": true,
  "require_cooldown_for_intense_workout": true,
  "pain_blocks_intensity_at_or_above": 4,
  "missed_sessions_do_not_roll_forward_automatically": true,
  "pool_distance_multiple_required": true
}
```

Os números são defaults editáveis, não aconselhamento médico imutável.

## 7. Zonas

Criar políticas intercambiáveis:

- `CssRelativeZonePolicy`;
- `GoalPaceZonePolicy`;
- `RpeZonePolicy`;
- `ManualZonePolicy`.

O domínio armazena a zona e o ritmo desejado; o adaptador decide o que consegue enviar ao Garmin.

## 8. CSS

Para teste de 400 m e 200 m:

```text
CSS em segundos/100 m = (tempo_400 - tempo_200) / 2
```

Exemplo:

```text
T400 = 620 s
T200 = 290 s
CSS = (620 - 290) / 2 = 165 s/100 m = 2:45/100 m
```

O cálculo deve registrar:

- atividades usadas;
- protocolo;
- data;
- tempos;
- fórmula;
- resultado;
- validade/expiração sugerida.

## 9. Geração de semana

Algoritmo inicial:

1. escolher fase;
2. calcular orçamento de volume;
3. escolher quantidade de sessões pela disponibilidade;
4. distribuir tipos de sessão;
5. selecionar templates;
6. adaptar distância para a piscina de 20 m;
7. ajustar ritmos por CSS/meta/RPE;
8. validar descanso e intensidade;
9. produzir rascunho;
10. solicitar aprovação antes de ativar/publicar.

## 10. Adaptação pós-treino

Sinais considerados:

- conclusão da distância;
- aderência ao bloco principal;
- diferença de ritmo;
- aumento de descanso;
- RPE acima/abaixo do previsto;
- técnica reportada;
- dor;
- sessões perdidas;
- prontidão;
- tendência de volume.

Exemplos de políticas:

```text
RPE muito maior + queda forte de ritmo
→ não aumentar volume; reduzir intensidade ou aumentar recuperação.

Treino concluído com RPE menor e boa consistência por duas sessões comparáveis
→ permitir pequena progressão dentro do limite semanal.

Dor relevante
→ bloquear proposta intensa e pedir revisão humana/profissional.

Sessão perdida
→ não empilhar automaticamente no dia seguinte.
```

## 11. Safety rails

- Não diagnosticar.
- Não recomendar continuar com dor aguda relevante.
- Não gerar dois treinos intensos consecutivos sem intervalo configurado.
- Não aumentar simultaneamente volume, intensidade e frequência sem aprovação avançada.
- Não alterar treino já iniciado.
- Não usar prontidão incompleta como certeza.
- Sempre permitir override manual com registro do motivo.

---

## 12. Separação entre linguagem e regra

O host/Skill pode interpretar “só tenho meia hora” como uma restrição estruturada. O motor recebe:

```json
{
  "available_duration_seconds": 1800,
  "date": "2026-08-07",
  "preserve_objectives": ["TECHNIQUE"],
  "avoid": ["HIGH_INTENSITY"],
  "reason": "USER_AVAILABILITY"
}
```

A partir daí, todo cálculo é determinístico. A proposta armazena:

- treino original e revisão;
- restrições interpretadas;
- rule set;
- alterações;
- impacto em distância, duração e carga;
- warnings;
- action hash.

## 13. Ordem das regras

1. segurança/restrições ativas;
2. validade estrutural e piscina;
3. disponibilidade;
4. recuperação entre estímulos;
5. objetivo da semana;
6. volume/carga;
7. preferências;
8. variedade.

Regras de nível superior não podem ser violadas para satisfazer preferências.

## 14. Defaults conservadores

Até existir baseline suficiente:

- não aumentar simultaneamente volume e intensidade;
- limitar progressão semanal por configuração, não constante escondida;
- manter ao menos uma sessão técnica;
- evitar dois estímulos intensos consecutivos;
- reduzir ou pausar intensidade quando feedback de dor relevante estiver ativo;
- pedir avaliação profissional para sinais persistentes/graves, sem diagnóstico.

## 15. Explicabilidade

`PlanningRun` deve produzir lista ordenada de `TrainingDecision`:

```text
DEC-001 manteve 3 sessões pela disponibilidade cadastrada.
DEC-002 não aumentou volume porque aderência da semana anterior foi 71%.
DEC-003 preservou técnica porque o feedback indicou degradação no final.
DEC-004 aproximou um bloco do ritmo-alvo de 2:15/100 m sem transformar a sessão em teste máximo.
```
