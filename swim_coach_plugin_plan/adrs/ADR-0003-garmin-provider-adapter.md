# ADR-0003 — Encapsular Garmin em provider

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

A integração pessoal inicial usa biblioteca/endpoints não oficiais, sujeitos a mudanças. O domínio não pode depender desses payloads.

## Decisão

Definir `GarminProvider` e DTOs internos. Implementação não oficial fica em infraestrutura. Futuras APIs oficiais implementam a mesma porta ou uma versão compatível.

## Consequências

- troca/mocks/fixtures facilitados;
- normalização de erros centralizada;
- custo de mapping explícito;
- capability matrix obrigatória;
- smoke tests reais ficam separados de unit/contract tests.
