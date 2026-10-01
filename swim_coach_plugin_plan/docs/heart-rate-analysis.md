# Frequência cardíaca e comparações de blocos

`get_swims(activity_id=...)` e `GET /api/v2/activities/{id}` retornam:

- `heart_rate`: FC média/máxima da sessão, origem, tempos por zona e avisos;
- `intervals[].heart_rate`: FC média/máxima da volta FIT;
- `main_set_heart_rate`: FC dos intervalos SWIM classificados como WORK,
  média ponderada pelo tempo de timer, cobertura e cada repetição;
- `aerobic_comparisons`: até dez pares históricos em ritmos semelhantes.

O painel auxiliar mostra as mesmas informações. A listagem recente retorna a FC
da sessão; use o detalhe para consultar os blocos e comparações.

## Semântica

A FC de uma volta FIT pode incluir paradas dentro da volta. A média dos blocos
é uma aproximação ponderada pelos tempos de timer, não uma média reconstruída de
amostras de FC durante o nado. Intervalos sem FC não entram no denominador; a
cobertura informa a fração de tempo dos blocos com média disponível. Descanso,
aquecimento, educativos e volta à calma não entram nos blocos principais.
Sem papel WORK conhecido, o app não inventa a identificação de bloco principal.

As zonas vêm de `session.time_in_hr_zone` ou de um único `time_in_zone` que
referencia aquela sessão. Os valores decodificados pelo SDK já estão em segundos.
O percentual usa a soma dos tempos por zona, não a duração total da sessão.
Os índices FIT são preservados, inclusive zero; não se presume uma divisão Z1–Z5.
Limites ausentes ficam nulos, sem fórmulas por idade. A ausência da distribuição
fica explícita; não se calcula tempo nas zonas a partir da FC média.

## Comparação histórica

A consulta considera no máximo vinte atividades anteriores do próprio usuário.
Os pares precisam de piscina, estilo, papel WORK e base de ritmo compatíveis,
FC média disponível e diferença de ritmo de até 3 s/100 m. Ritmo de timer não é
usado para essa comparação. Dados de baixa qualidade, avisos de intervalo,
outliers e erro do relógio declarado pelo atleta impedem o uso na comparação.
São escolhidos os ritmos mais próximos; em empate, o registro mais recente.

Uma repetição de 240 m a 2:49 pode ser comparada descritivamente com uma de
160 m a 2:49. O resultado inclui distâncias, tempos, FC, datas, descanso anterior
quando conhecido e diferenças de FC e ritmo. A distância diferente recebe aviso
explícito sobre duração e resposta da FC. Todos os pares têm confiança LOW e
tipo EXPLORATORY: não são uma tendência validada de eficiência aeróbica.
Sensor, fadiga, posição da repetição no treino, recuperação e RPE precisam ser
considerados pelo treinador antes de interpretar uma melhora.

## Persistência e dados existentes

A migração `000017` adiciona `activity_normalization.heart_rate_json`, com `{}`
para registros anteriores. O parser passa para `swim-coach:2.2.0`, permitindo
reprocessamento versionado e idempotente dos FIT preservados. Sem novos fatos
FIT, a FC da sessão pode usar o resumo Garmin com origem GARMIN_SUMMARY.
Não há reprocessamento automático de atividades antigas nem publicação Garmin.
Use o fluxo de reprocessamento local já existente para recuperar as zonas antigas.
