# Registro de riscos

| ID | Risco | Prob. | Impacto | Sinal | Mitigação | Owner/fase |
|---|---|---:|---:|---|---|---|
| R-001 | endpoints Garmin não oficiais mudam | alta | alta | auth/sync falha | adapter, fixtures, flags, fallback, API oficial futura | P02/P07 |
| R-002 | termos Garmin limitam uso/distribuição | média | alta | revisão jurídica/conta | uso pessoal, não publicar publicamente sem revisão | P00/P12 |
| R-003 | plugin/developer mode indisponível na superfície usada | média | alta | não instala no iPhone/conta | spike P00, PWA fallback, suporte declarado | P00 |
| R-004 | OAuth IdP incompatível com fluxo MCP atual | média | alta | discovery/registration falha | spike CIMD/DCR/predefined; trocar IdP por port | P00/P05 |
| R-005 | modelo chama write com intenção ambígua | média | alta | eval falha/tool log | tool de intenção estreita, pergunta quando há múltiplos alvos, ownership e evals | P13 |
| R-006 | replay/double publish | média | alta | bindings duplicados | chave derivada no servidor, binding estável por treino e reconcile | P07/P13 |
| R-007 | timeout após Garmin criar treino | média | alta | estado ambíguo | `NEEDS_RECONCILIATION`, buscar antes de retry | P07 |
| R-008 | FIT incompleto/inconsistente | alta | média | lengths faltando | qualidade de dados, parser version, partial outputs | P03 |
| R-009 | piscina errada distorce distância | média | média | mismatch lengths | pool explícita por activity/workout; warning | P03/P04 |
| R-010 | token Garmin vaza em logs/backup | baixa | crítica | secret scan/incidente | encryption, redaction, key rotation, access control | P02/P12 |
| R-011 | single-user esconde IDOR | média | alta | teste cruzado falha | user_id em tudo e testes com segundo fixture user | P01/P05 |
| R-012 | Skills ficam desatualizadas do tool schema | média | média | eval/erro de args | compat matrix, contract CI, release hash | P06 |
| R-013 | UI MCP prende produto a um host | média | média | headless falha | UI opcional, MCP Apps padrão, fallback | P09 |
| R-014 | planejamento aumenta carga inadequadamente | média | alta | fadiga/dor/aderência cai | regras conservadoras, feedback e limites | P10/P13 |
| R-021 | compatibilidade legada reaparece na UX | média | média | tools/rotas de proposal voltam | MCP v2 com allowlist exata, router legado desmontado e contract tests | P13 |
| R-015 | produto é interpretado como conselho médico | média | alta | linguagem clínica | disclaimers contextuais, não diagnosticar, escalation | todos |
| R-016 | PWA offline executa ação expirada | baixa | alta | stale proposal | não cachear approval executável; revalidar servidor | P11 |
| R-017 | jobs acumulam e ocupam banco | média | média | queue age/disk | retention, metrics, dead letter status | P11/P12 |
| R-018 | backup existe mas restore falha | média | alta | drill falha | restore automático testado, checksum, runbook | P12 |
| R-019 | custos/complexidade crescem cedo | média | média | muitos serviços | modular monolith, Postgres queue, ADR para escalar | todos |
| R-020 | publicação pública exige requisitos novos | alta | baixa no MVP | portal/review | fora do MVP; readiness checklist separado | P12 |

## Regras de tratamento

- risco crítico sem mitigação bloqueia a fase;
- risco aceito exige ADR ou registro explícito;
- falha real atualiza probabilidade e adiciona teste;
- risco de plataforma deve ter fallback operacional;
- uso pessoal permite reduzir cerimônia, não remover controles contra perda de
  dados, vazamento de segredo ou duplicação externa.
