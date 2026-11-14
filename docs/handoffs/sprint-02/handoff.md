# Handoff — Sprint 2: Importador CSV e prévia

## Status

**Concluída e aceita pelo usuário.** A Sprint 3 foi iniciada por solicitação explícita do usuário. Ver `docs/handoffs/sprint-03/handoff.md`.

## Objetivo e escopo

Implementar somente um adaptador para o formato de extrato Nubank já conhecido. Fatura de cartão não tem formato fornecido e segue fora deste adaptador. A prévia valida e normaliza em memória, mas não persiste nem altera arquivos.

## Contrato do adaptador

- Entrada aceita `str` ou bytes UTF-8 (BOM permitido) e requer escolha explícita de `Person`.
- Cabeçalho de origem aceito: `JasData`, `Valor`, `Identificador`, `Descrição`; `JasData` é normalizado para `Data` na prévia.
- Colunas extras são aceitas e preservadas integralmente em `source_fields`; cabeçalhos duplicados são recusados.
- CSV é separado por vírgulas; `csv` padrão respeita quoting. Linhas com menos/mais células que o cabeçalho bloqueiam a prévia.
- Data estrita `DD/MM/YYYY`, com validação de calendário.
- Valor estrito: sinal opcional negativo, inteiro decimal com ponto e até duas casas; não usa float, não arredonda, não aceita notação científica nem vírgula decimal.
- IDs e descrições ausentes são erro. Mensagens nunca incluem valores de célula/identificadores/descrições.
- Linhas integralmente vazias são ignoradas e sua posição é devolvida para transparência.
- Cada transação recebe `MovementType.PENDING`, sem categoria. O sinal não determina natureza econômica.
- `can_confirm` é true somente sem erros e com pelo menos uma linha válida. Esta sprint ainda não grava mesmo quando a prévia está válida.

## TDD e implementação

- Arquivo de testes foi criado antes do adaptador; primeira coleta falhou porque `streamline_finance.importers` ainda não existia.
- Implementação em `src/streamline_finance/importers/nubank.py`.
- `ImportPreview`, `PreviewTransaction` e `PreviewError` mantêm campos originais, resultado normalizado e problemas por linha/campo.
- 17 testes sintéticos cobrem parse válido, BOM, seleção de pessoa, preservação de coluna extra, arquivo vazio, delimitador/header incorreto, datas inválidas, valores subcentavo/vírgula/expoente, obrigatórios vazios, linha truncada/extra, cabeçalho duplicado, linha em branco, erros sem dados sensíveis e ausência de persistência.
- Falhas intermediárias levaram a clarificações no contrato: aceitar colunas adicionais sem descartá-las; rejeitar estrutura de linha truncada/extra; validar string estrita para data/valor. Todos os casos foram convertidos em testes.
- Ruff inicialmente apontou formatação/imports e duas linhas longas nos arquivos novos; os ajustes foram aplicados e a sequência final completa passou.

## Arquivos

- `src/streamline_finance/importers/__init__.py`
- `src/streamline_finance/importers/nubank.py`
- `tests/test_nubank_import.py`
- `docs/manual/sprint-02-import-preview.md`
- `README.md` aponta ao manual/handoff da sprint corrente.

## Correção posterior à sprint: importabilidade do pacote

Ao executar o exemplo documentado, o usuário encontrou `ModuleNotFoundError: No module named 'streamline_finance'`. Causa: projeto usa layout `src/`, mas `pyproject.toml` não definia build-system; uv instalava dependências, mas não instalava o projeto. Corrigido ao declarar `setuptools.build_meta` e descoberta de pacotes sob `src/`. Após `uv lock --offline` e `uv sync --locked --offline`, o projeto foi instalado editável no `.venv`, e o comando do manual passou. A correção não lê nem altera arquivos em `data/`.

## Verificações

- Incidente da interface do usuário reproduzido via CSV local: cabeçalho da fonte está correto e o parser/FastAPI confirmam prévia válida com 38 linhas e zero erros; nenhuma gravação ocorre na prévia.
- Campo de origem `JasData` agora aparece como `Data`; a tabela exibe os quatro campos reconhecidos e ordenados em campos amigáveis.
- Teste sintético dedicado cobre a normalização `JasData` → `Data`.
- Segunda ocorrência da mesma mensagem após reinício: cabeçalhos observados são ASCII/UTF-8 esperados; chamadas in-process ao parser e à rota FastAPI retornam 200, prévia válida (38 linhas), zero erros e sem persistir. Causa visual da mensagem não foi reproduzida pela API/parser.
- Parser normaliza Unicode NFC, espaços periféricos e caracteres invisíveis da categoria Unicode Cf nos cabeçalhos; mantém validação das colunas conhecidas após normalização. Fixture sintética cobre esses caracteres.

- `uv run pytest`
- `uv run pytest`: passou; 33 testes no total na validação pós-correção do pacote (17 da Sprint 2, 13 da Sprint 1 e 3 da Sprint 0); Sprint 3 adiciona seus testes no handoff próprio.
- Após a robustez de normalização do cabeçalho: `uv run pytest`: passou; 109 testes no total.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv lock --check --offline`, `uv sync --locked --offline` e `git diff --check`: passaram.
- `git check-ignore -v` confirmou banco/raw e os arquivos reais de entrada/histórico ignorados; SQLite ficou com 0 batches e 0 transações depois de todos os testes.
- `uv run ruff format --check .`
- `uv run ruff format --check .`: passou; 25 arquivos verificados.
- `uv run ruff check .`
- `uv run ruff check .`: passou.
- `uv sync --locked --offline`
- `uv sync --locked --offline`: passou usando lockfile local e ambiente do repositório.
- `rtk git check-ignore -v data/ .venv/bin/python`
- `rtk git check-ignore -v` confirmou exclusão dos dados reais locais e do ambiente `.venv/`.
- `rtk git diff --check`
- `rtk git diff --check`: passou.
- Após corrigir o empacotamento: `uv lock --offline` e `uv sync --locked --offline` passaram; `uv run --locked --offline python -c ...` no exemplo sintético exibiu `Pode confirmar: True`, `Linhas válidas: 2`, `Erros: 0`.

Não foram abertos nem processados arquivos reais de `data/`; somente metadados do handoff da Sprint 0 e fixtures inventadas foram usados.

## Limitações e próximo passo

- Sem CSV da fatura; mapear quando usuário fornecer seus cabeçalhos/formato seguros.
- Sem inferência de tipo, regras da planilha, revisão visual, gravação, hash, idempotência ou deduplicação; pertencem às próximas sprints.
- Confirmar com o usuário os campos e a prévia antes de ligar qualquer interface/API; revisar fatura numa sprint posterior.
- O usuário pediu explicitamente para iniciar a sprint seguinte; Sprint 3 está em `docs/handoffs/sprint-03/handoff.md`.
