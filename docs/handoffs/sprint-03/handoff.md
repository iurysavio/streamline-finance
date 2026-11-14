# Handoff — Sprint 3: SQLite, histórico e duplicatas

## Status

**Concluída e aceita pelo usuário.** A Sprint 4 foi iniciada após aceite explícito. Ver `docs/handoffs/sprint-04/handoff.md`.

## Objetivo

Confirmar prévias válidas de modo atômico, persistir transações e histórico em SQLite local, manter originais localmente, tratar reimportação sem duplicar e criar apenas candidatos revisáveis de possível pagamento de fatura.

## Decisões propostas/implementadas

- SQLite em `data/db/finance.sqlite3`; arquivos brutos em `data/raw/` com nome SHA-256.
- Arquivos na criação recebem modo 0600, diretórios de dados 0700 em POSIX; SQLite usa rollback journal e `secure_delete`. Criptografia do disco/backup é responsabilidade do sistema local.
- Um `source_key` explícito identifica conta/cartão; `SourceKind` identifica `bank_account` ou `credit_card`. Nunca adivinhar origem pela string do nome.
- Batch guarda SHA-256 do original, pessoa, tipo de fonte, horário, contagem e vínculo às transações.
- Valores persistidos em centavos inteiros e BRL.
- Reimportar arquivo igual e mesmas decisões pessoa/tipo retorna `already_imported`; arquivo igual com escolhas diferentes conflita.
- Unicidade de transação é `(source_key, external_id)`. Mesmo ID/conteúdo repetido é ignorado e o batch novo mantém vínculo ao movimento existente. Mesmo ID com conteúdo diferente aborta atomicamente.
- CSV original byte a byte é mantido em `data/raw`; não guardar CSV no banco.
- Natureza inicia `pending`; revisão exige confirmação explícita, só atualiza linha ainda pendente e gera histórico.
- Payment candidates exigem cartão previamente confirmado como expense + saída bancária com texto pagamento/fatura e natureza pending/transfer, mesma pessoa, ambos valores negativos, igualdade absoluta exata em centavos e janela máxima de 5 dias (configurável). Candidato requer revisão e aceitar/rejeitar/reset não altera transações.
- Preview, confirmação persistente e candidatos ainda não estão ligados à UI Streamlit (Sprint 5); a API local foi implementada na Sprint 4.

## Testes TDD

- `tests/test_persistence.py` foi criado primeiro. Primeira execução falhou esperando o módulo `storage` que ainda não existia.
- Casos de teste: valores exatos/import batch, mesmo arquivo idempotente, IDs sobrepostos em arquivos, conflito atômico quando conteúdo muda, mesmo ID entre fontes, pessoa diferente no mesmo arquivo, preview inválido sem write, paths db/raw, mesmo valor com IDs distintos, origem de cartão e conta, valores/data não correspondentes, revisão explícita de natureza, trilha de revisão e reimport preservando decisão.
- Falhas encontradas durante TDD revelaram valor da trilha de batch para linhas duplicadas, natureza editável precisa de confirmação, tipo de origem explícito, pessoa/tipo parte da identidade de importação e conflito em vez de skip quando escolhas divergem.

## Arquivos

- `src/streamline_finance/storage.py`: repositório SQLite, importação atômica, auditoria e candidatos.
- `src/streamline_finance/domain.py`: `SourceKind` e origem na transação.
- `src/streamline_finance/importers/nubank.py`: preview passa `source_key` e `source_kind` explicitamente.
- `tests/test_persistence.py`: testes sintéticos de SQLite/reimport/review/payment-match.
- `.gitignore`: exclui também sidecar SQLite WAL/SHM.
- `docs/manual/sprint-03-storage.md`: instruções, reimportação, match e backup.

## Segurança e privacidade

- Testes somente em diretórios temporários com registros inventados.
- Não abrir CSV/XLSX reais de `data/`.
- Verificar `.gitignore` para DB, sidecars e `data/` antes de finalizar.
- Cópia raw usa nome derivado de hash; o hash não anonimiza o conteúdo, portanto o diretório continua privado.

## Verificações pendentes

Executar e registrar, corrigindo falhas:

- `uv run pytest`: passou; 50 testes no total (17 persistência, 17 importador, 13 domínio, 3 fundação).
- `uv run ruff format --check .`: passou; 29 arquivos verificados.
- `uv run ruff check .`: passou.
- `uv sync --locked --offline`: passou.
- `git check-ignore -v` confirmou que DB/raw exemplo, planilha/extrato reais e `.venv` ficam ignorados.
- `git diff --check`: passou.
- Testes rodam exclusivamente contra diretórios temporários e fixtures sintéticas.

## Próximo passo

O usuário aceitou a Sprint 3 e aprovou iniciar Sprint 4. Ver o handoff da Sprint 4.
