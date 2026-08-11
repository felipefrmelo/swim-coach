# Evals do plugin

`cases/` contém casos iniciais validados pelo schema `contracts/plugin-eval-case.schema.json`. Eles são especificação de aceitação; a implementação deve convertê-los para o runner escolhido sem perder os asserts.

Cobertura atual do blueprint:

- leitura/análise de atividade;
- progresso da meta;
- sync read-only e write-scope;
- publicação em dois turnos;
- tentativa de bypass;
- hash alterado;
- adaptação por tempo;
- feedback e dor sem diagnóstico;
- planejamento semanal apenas como proposta;
- dedupe de job.

Cada Skill deve atingir a quantidade completa prevista em `docs/10-plugin-skills.md` antes de sua release. Estes casos são o núcleo crítico, não o dataset final.
