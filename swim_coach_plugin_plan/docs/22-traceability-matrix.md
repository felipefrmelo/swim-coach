# Matriz de rastreabilidade

| Requisito | Fase principal | Contrato/teste esperado |
|---|---:|---|
| FR-PROFILE-001..004 | P01 | API/profile tests |
| FR-GOAL-001..003 | P01/P10 | goal service + progress fixtures |
| FR-GARMIN-001 | P02 | bootstrap security test |
| FR-GARMIN-002..005 | P02/P03 | provider contract + idempotency |
| FR-ACT-001..002 | P03 | FIT fixture golden tests |
| FR-ACT-003..005 | P03/P11 | matching/feedback tests |
| FR-WO-001..006 | P04 | canonical schema + property tests |
| FR-WO-007..008 | P07 | compiler/publish/reconcile tests |
| FR-MCP-001..004 | P05 | MCP Inspector + contract suite |
| FR-MCP-005..008 | P08 | approval/security evals |
| FR-SKILL-001..007 | P06 | eval cases por Skill |
| FR-WEB-001..007 | P01/P04/P07 | Playwright flows |
| FR-WEB-008 | P11 | offline E2E |
| FR-PLAN-001..005 | P10 | planning golden/property tests |
| NFR-SEC-001 | todas | secret scan/log tests |
| NFR-SEC-002 | P05 | OAuth discovery/JWT tests |
| NFR-SEC-003 | P02/P12 | encryption/rotation tests |
| NFR-REL-001 | P02/P07/P08 | replay tests |
| NFR-REL-002 | P01/P11 | queue/outbox tests |
| NFR-PERF-001 | P05/P12 | load smoke |
| NFR-PERF-002 | P02/P07 | async job behavior |
| NFR-OBS-001 | P01/P05 | correlation propagation |
| NFR-PORT-001 | P05/P09 | headless fallback eval |
| NFR-DATA-001 | P12 | export/delete E2E |
| NFR-TEST-001 | todas | phase gate |

## Regra de mudança

Novo requisito recebe ID, fase, teste e atualização desta matriz antes de ser considerado planejado.
