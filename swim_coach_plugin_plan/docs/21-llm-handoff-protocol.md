# Protocolo de handoff entre LLMs

## Objetivo

Permitir que agentes diferentes implementem fases sucessivas sem depender de memória de conversa, inferência ou contexto implícito.

## Artefatos obrigatórios de entrada

- plano da fase;
- status atual;
- ADRs relevantes;
- contratos;
- código e testes existentes;
- último changelog.

## Saída obrigatória de cada execução

```markdown
## Handoff

### Escopo entregue
- ...

### Arquivos relevantes
- `path`: motivo

### Comandos executados
- `command` → resultado

### Migrações
- ...

### Contratos alterados
- ...

### Evidências manuais
- ...

### Riscos/limitações restantes
- ...

### Próxima ação recomendada
- ...
```

## Regras

- não usar “funciona” sem comando/evidência;
- distinguir fixture, fake, sandbox e integração real;
- incluir IDs de task;
- listar decisões não óbvias;
- atualizar status estruturado e humano;
- manter commits pequenos e intencionais;
- não apagar contexto anterior útil; resumir e apontar para arquivos.

## Estado de tarefa

- `NOT_STARTED`
- `IN_PROGRESS`
- `BLOCKED`
- `DONE`
- `SKIPPED` somente por ADR/escopo.

## Evidência aceitável

- saída de teste/CI;
- migration aplicada em banco descartável;
- screenshot/log sanitizado de plugin instalado;
- ID de atividade real mascarado + checksum;
- resultado do MCP Inspector;
- restore drill;
- request/response sanitizados.

## Evidência não aceitável

- “revisei mentalmente”;
- mock quando o gate exige integração real;
- código não executado;
- screenshot sem contexto/reprodução;
- teste desabilitado;
- sucesso presumido após timeout externo.

## Bloqueios

Quando bloqueado, o agente deve:

1. concluir partes independentes;
2. documentar passo exato que falhou;
3. salvar logs sanitizados;
4. propor 1–3 caminhos;
5. marcar `BLOCKED`, não `DONE`;
6. evitar refatoração não relacionada.
