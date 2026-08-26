# Produto e escopo

## 1. Visão

O Swim Coach transforma o ciclo de treinamento em uma sequência única e auditável:

```text
planejar → revisar → publicar → nadar → sincronizar → analisar → adaptar
```

Na P13, “revisar” é uma decisão conversacional, não um protocolo técnico. O
usuário pede a intenção ao ChatGPT e o backend salva, agenda ou publica em um
comando direto. Propostas, hashes, versões e chaves de idempotência não aparecem
na experiência. O site é editor e painel auxiliar; ChatGPT é a interface principal.

A interface conversacional principal vive em ChatGPT/Codex. O plugin ensina os workflows com Skills e acessa o backend pelo MCP. A PWA resolve fluxos visuais e operacionais. O relógio executa e mede.

## 2. Persona inicial

| Atributo | Valor inicial |
|---|---|
| Atleta | Felipe |
| Experiência | triathlon/natação recreativa em evolução |
| Dispositivo | Garmin Forerunner 265 |
| Ambiente principal | piscina de 20 m |
| Objetivo | nadar 2.000 m em 45 min |
| Ritmo-alvo | 135 s/100 m (`2:15/100 m`) |
| Sessões esperadas | configurável; baseline de 3/semana |
| Idioma | pt-BR |
| Timezone | America/Sao_Paulo |

## 3. Jobs to be done

### Conversacionais

- “O que tenho para nadar hoje?”
- “Como foi minha última natação?”
- “Compare o treino de hoje com o que executei.”
- “Só tenho 30 minutos; proponha um ajuste.”
- “Monte a próxima semana sem aumentar demais o volume.”
- “Envie este treino para o Garmin.”
- “Por que meu ritmo caiu no final?”
- “Registre esforço 7, técnica pior no fim e sem dor.”

### Operacionais

- conectar/desconectar Garmin;
- sincronizar histórico;
- corrigir pareamento de uma atividade;
- revisar e editar um treino estruturado;
- confirmar uma publicação;
- consultar logs de uma ação;
- exportar e apagar dados;
- restaurar backup.

## 4. Objetivos mensuráveis

- importar uma nova atividade sem duplicatas;
- mostrar análise em até um ciclo de sincronização;
- criar qualquer treino válido para piscina de 20 m;
- impedir etapas que não terminem na parede;
- publicar uma única vez apesar de retries;
- responder perguntas com IDs e dados do backend, não por memória inventada;
- exigir confirmação para efeitos externos;
- manter toda alteração rastreável por `correlation_id` e `audit_event`.

## 5. Requisitos funcionais

### FR-PROFILE

- `FR-PROFILE-001`: manter perfil, timezone, idioma e preferências.
- `FR-PROFILE-002`: manter piscinas e selecionar uma padrão.
- `FR-PROFILE-003`: manter restrições e disponibilidade.
- `FR-PROFILE-004`: manter dispositivos e capacidades conhecidas.

### FR-GOAL

- `FR-GOAL-001`: criar metas de distância/tempo/data.
- `FR-GOAL-002`: calcular ritmo-alvo e progresso.
- `FR-GOAL-003`: registrar milestones e testes.

### FR-GARMIN-READ

- `FR-GARMIN-001`: bootstrap de autenticação sem persistir senha.
- `FR-GARMIN-002`: listar/importar atividades incrementalmente.
- `FR-GARMIN-003`: preservar payload e FIT com checksum.
- `FR-GARMIN-004`: reexecutar sincronização de forma idempotente.
- `FR-GARMIN-005`: normalizar erros e rate limit.

### FR-ACTIVITY

- `FR-ACT-001`: normalizar sessão, laps, intervalos e extensões.
- `FR-ACT-002`: calcular ritmo, descansos, stroke rate, SWOLF e consistência quando os dados existirem.
- `FR-ACT-003`: associar atividade ao treino planejado.
- `FR-ACT-004`: permitir correção manual do pareamento.
- `FR-ACT-005`: registrar feedback pós-treino.

### FR-WORKOUT

- `FR-WO-001`: criar treino como árvore de passos.
- `FR-WO-002`: suportar repetição, distância, tempo, descanso e lap button.
- `FR-WO-003`: validar unidades e múltiplos da piscina.
- `FR-WO-004`: versionar revisões imutáveis.
- `FR-WO-005`: calcular totais antes de salvar/publicar.
- `FR-WO-006`: agendar localmente e manter estados.
- `FR-WO-007`: compilar para Garmin atrás do provider.
- `FR-WO-008`: publicar/agendar com idempotência.

### FR-PLUGIN/MCP

- `FR-MCP-001`: expor ferramentas de leitura focadas em objetivos do usuário.
- `FR-MCP-002`: retornar schema versionado, texto conciso e structured content.
- `FR-MCP-003`: autenticar e autorizar por escopo.
- `FR-MCP-004`: registrar invocações sem registrar segredos ou conversa integral.
- `FR-MCP-005`: criar propostas de alteração sem executar efeitos externos.
- `FR-MCP-006`: executar somente proposta aprovada e não expirada.
- `FR-MCP-007`: continuar útil em clientes sem UI MCP.
- `FR-MCP-008`: fornecer erros acionáveis e próximos passos.

### FR-SKILLS

- `FR-SKILL-001`: revisar última atividade.
- `FR-SKILL-002`: planejar semana.
- `FR-SKILL-003`: adaptar treino por tempo/disponibilidade.
- `FR-SKILL-004`: publicar no Garmin com confirmação.
- `FR-SKILL-005`: coletar feedback.
- `FR-SKILL-006`: acompanhar meta.
- `FR-SKILL-007`: diagnosticar sincronização.

### FR-PWA

- `FR-WEB-001`: dashboard e treino do dia.
- `FR-WEB-002`: calendário.
- `FR-WEB-003`: editor estruturado.
- `FR-WEB-004`: atividades e análise.
- `FR-WEB-005`: feedback.
- `FR-WEB-006`: Garmin/configurações.
- `FR-WEB-007`: propostas, aprovações, jobs e auditoria.
- `FR-WEB-008`: leitura offline do treino já sincronizado.

### FR-PLANNING

- `FR-PLAN-001`: gerar semana como rascunho.
- `FR-PLAN-002`: aplicar regras de volume, intensidade e recuperação.
- `FR-PLAN-003`: explicar entradas, regras e mudanças.
- `FR-PLAN-004`: considerar aderência, feedback e disponibilidade.
- `FR-PLAN-005`: nunca converter dor em diagnóstico.

## 6. Requisitos não funcionais

- `NFR-SEC-001`: zero segredo em repo/log/resultado MCP.
- `NFR-SEC-002`: OAuth 2.1 em endpoint remoto privado.
- `NFR-SEC-003`: criptografia de tokens em repouso.
- `NFR-REL-001`: idempotência em sync e escrita Garmin.
- `NFR-REL-002`: jobs retomáveis e outbox transacional.
- `NFR-PERF-001`: leitura comum MCP p95 abaixo de 2 s sem chamada Garmin síncrona.
- `NFR-PERF-002`: sincronização longa retorna job, não mantém chamada aberta.
- `NFR-OBS-001`: correlation ID ponta a ponta.
- `NFR-PORT-001`: ferramenta MCP funciona sem UI customizada.
- `NFR-DATA-001`: exportação e exclusão.
- `NFR-TEST-001`: regras de domínio cobertas por testes determinísticos.

## 7. Fora de escopo do MVP

- tratamento, diagnóstico ou prescrição médica;
- alimentação e suplementação;
- análise de vídeo de técnica;
- marketplaces públicos e cobrança;
- suporte garantido a todas as superfícies do ChatGPT/Codex;
- sincronização em tempo real garantida por webhook não oficial;
- edição direta de payload Garmin pelo modelo;
- competição social;
- múltiplos coaches/atletas.

## 8. Política de evolução para outros esportes

O domínio usa `SportType`, mas o primeiro release aceita apenas `POOL_SWIMMING`. Corrida, ciclismo e triathlon só entram após uma ADR e uma fase própria. Não generalizar prematuramente estruturas que são específicas da natação; criar portas explícitas para extensão.
