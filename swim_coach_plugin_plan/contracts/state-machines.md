# Máquinas de estado

## PlannedWorkout

```text
DRAFT → APPROVED → SCHEDULED → PUBLISHED → COMPLETED
  │         │          │          │
  ├──────→ CANCELLED ←─┴──────────┘
  └──────→ ARCHIVED
```

- edição de `APPROVED+` cria nova revision;
- estado do workout e estado de publicação são correlatos, mas não colapsados num booleano.

## ExternalWorkoutBinding

```text
NOT_CREATED → CREATING → CREATED → SCHEDULING → SCHEDULED
                  │          │            │
                  └→ FAILED  └→ FAILED    └→ FAILED
qualquer operação ambígua → NEEDS_RECONCILIATION
```

## SyncRun

```text
QUEUED → RUNNING → SUCCEEDED
             ├──→ PARTIAL
             ├──→ FAILED_RETRYABLE
             └──→ FAILED_TERMINAL
QUEUED/RUNNING → CANCELLED
```

## Job

```text
QUEUED → LEASED → RUNNING → SUCCEEDED
                    ├──→ RETRY_SCHEDULED → QUEUED
                    ├──→ FAILED_TERMINAL
                    └──→ NEEDS_RECONCILIATION
```

## ActionProposal

```text
DRAFT → READY_FOR_REVIEW → APPROVED → QUEUED → EXECUTING → SUCCEEDED
  │            │               │         │          ├→ FAILED
  │            ├→ REJECTED      │         │          └→ NEEDS_RECONCILIATION
  │            └→ EXPIRED       │         └→ CANCELLED
  └→ CANCELLED                  └→ EXPIRED (antes de queue)
```

## GarminConnection

```text
DISCONNECTED → PENDING_BOOTSTRAP → CONNECTED → DEGRADED
      ↑                                  │          │
      └──────────────── REVOKED ←────────┴──────────┘
```
