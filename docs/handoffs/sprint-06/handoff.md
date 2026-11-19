# Handoff — Sprint 6: aceite v0 e operação local

## Estado

Sprint 5 aceita e Sprint 6 autorizada pelo usuário em 15/11/2026. **Sprint 6 e v0 aceitos explicitamente pelo usuário** antes da implementação da Sprint 7.

## Escopo e decisões

- Fluxo sintético integrado: prévia sem escrita, confirmação, revisão de despesa/estorno/transferência, relatório em centavos, persistência, backup, restauração isolada e reimportação idempotente.
- Exercício de cópia `db/` e `raw/` em diretórios temporários, inclusive PowerShell no Windows, com verificação SQLite e reabertura do banco restaurado.
- Operação, tratamento de falhas, backup e recuperação em `docs/manual/sprint-06-operation.md`; dados reais não são usados nos testes nem impressos na documentação ou nos logs.
- O banco operacional do usuário não é sobrescrito nem utilizado como fixture. Os backups reais são uma ação local do usuário; o ensaio automático não demonstra que um backup real específico esteja íntegro.
- Pivot interativa continua adiada por decisão do usuário. A aplicação continua local e sem autenticação.

## Verificações e próximo passo

- `python -m uv run --locked pytest`: **122 testes passaram** no Windows/Python 3.12, inclusive os dois cenários de aceite e recuperação sintética.
- `python -m uv run --locked ruff format --check .`: passou; 50 arquivos verificados.
- `python -m uv run --locked ruff check .`: passou.
- `python -m uv lock --check --offline`: passou.
- `git check-ignore -v data/db/finance.sqlite3 data/raw/example.csv data/backups/example/db/finance.sqlite3 data/historical/example.xlsx .venv/example`: todos ignorados.
- `rtk git diff --check`: passou para arquivos rastreados; novos arquivos devem ser incluídos na próxima revisão do diff antes de eventual commit.

Próximo passo: consultar `docs/handoffs/sprint-07/handoff.md` para a evolução de importação de faturas.
