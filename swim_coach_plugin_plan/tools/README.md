# Ferramentas do pacote

## Atualizar índices e checksums

```bash
python tools/update_indexes.py
```

O comando também regenera `CHECKSUMS.sha256` e ignora dependências instaladas,
caches, builds e material local sensível.

## Validar

Dependências recomendadas para validação completa:

```bash
python -m pip install pyyaml jsonschema
python tools/validate_plan.py --write-report
```

Sem essas dependências, o script ainda verifica estrutura, Markdown e JSON, mas avisa que pulou validações semânticas de YAML/JSON Schema.

Os scripts não acessam internet, Garmin ou credenciais.
