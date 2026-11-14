# Handoff — Sprint 1: Domínio financeiro e regras

## Status

**Concluída e aceita pelo usuário.** A Sprint 2 começou após o aceite explícito. Ver `docs/handoffs/sprint-02/handoff.md`.

## Objetivo

Definir modelo financeiro mínimo e regras determinísticas explicáveis usando apenas dados sintéticos; rejeitar valores monetários que exigiriam arredondamento implícito; manter movimentos que não são despesas fora da categorização de despesas.

## Decisões de domínio

- `Money` suporta BRL apenas e armazena centavos inteiros.
- `Money.from_decimal` aceita somente `Decimal` finito representável exatamente em centavos. Não converte float, não arredonda frações de centavo.
- `MovementType` separa `expense`, `income`, `transfer` e `pending`; natureza não é inferida somente pelo sinal.
- `Person` contém `self`, `spouse`, `shared`; usuário da aplicação escolhe a pessoa na importação conforme decidido anteriormente.
- `Transaction` mantém `occurred_on` e `posted_on` separados; `posted_on` pode faltar.
- Apenas despesas podem levar categoria de despesa.
- `Category` guarda macro e micro em par explícito. Mapeamento de planilha continua provisório: `Tipo de Fluxo` macro, `Fluxo` micro, `Classificação` natureza. Não foram criadas regras a partir da planilha.
- `CategorizationRule` mapeia descrição para categoria com ID estável.
- Correspondência considera caixa ignorada e espaços repetidos normalizados, mas acentos/pontuação significativos. Sem fuzzy matching, defaults ou ML.
- Regra desconhecida -> `needs_review`; regras iguais conflitantes -> `ambiguous`; nenhum estado produz sugestão de categoria.
- `CategorizationResult.confirm` separa revisão humana da sugestão original e mantém IDs das regras como proveniência.
- Entradas, transferências e pendências retornam `not_applicable` para categorização de despesa; confirmação de categoria nesses movimentos é rejeitada.

## Mudanças

- `src/streamline_finance/domain.py`: Money, MovementType, Person, Category e Transaction.
- `src/streamline_finance/categorization.py`: regras exatas e resultado explicável/revisável.
- `src/streamline_finance/__init__.py`: pacote de domínio.
- `tests/test_finance_domain.py`: 13 testes de comportamento com dados sintéticos.
- `pyproject.toml`: pytest agora importa o código em `src/`.
- `docs/manual/sprint-01-domain.md`: manual didático do domínio, exemplos sintéticos e limites.

## TDD e verificações

- Primeiro foi criado `tests/test_finance_domain.py`; teste inicial falhou na coleta porque pacote ainda não existia.
- Depois da estrutura mínima do pacote, os testes executaram contra a implementação e passaram.
- Testes cobrem BRL exato, positivos/negativos, rejeição de valores subcentavo e não finitos, rejeição de float, datas e pessoa, regra exata, não correspondência, conflito, exclusão de tipos não-despesa e confirmação/correção mantendo sugestão/proveniência.
- `uv run pytest`: passou; 15 testes no total (13 da Sprint 1 e 2 da Sprint 0).
- `uv run ruff format --check .`: passou; 20 arquivos verificados.
- `uv run ruff check .`: passou.
- `uv sync --locked --offline`: passou com lockfile local, sem resolver o workspace externo.
- `rtk git check-ignore -v` confirmou que os arquivos locais em `data/` e ambiente `.venv/` continuam ignorados.
- `rtk git diff --check`: passou.
- Uma checagem inicial de formatação e uma de ordenação de imports falharam nos testes novos; aplicados Ruff formatter/import-sort e toda a sequência final passou.

## Fora do escopo nesta sprint

Leitura da planilha, definição do conjunto de categorias, geração automática de regras do histórico, classificação do extrato, CSV import, SQLite, API, Streamlit, processamento de estorno, agregados e deduplicação.

## Próximo passo

O usuário aceitou a Sprint 1 e autorizou a Sprint 2. A prévia do CSV não deriva regras da planilha; confirmar o mapeamento e significados antes de produzir regras na próxima etapa apropriada.
