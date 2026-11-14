# Manual de referência — domínio financeiro e categorização

## Finalidade

Este módulo define como representar movimentos financeiros e como sugerir uma categoria sem alterar silenciosamente o histórico. Não importa arquivos, não persiste dados e não chama serviços externos.

## Conceitos básicos

- **Money:** valor BRL armazenado em centavos inteiros. Exemplo fictício: `Decimal("12.34")` vira `1234` centavos. Valores com mais de duas casas não são arredondados: são rejeitados para uma pessoa decidir a regra.
- **Transaction:** um movimento de uma conta/cartão, com identificador, descrição, pessoa, valor, natureza e data em que ocorreu. `posted_on` é opcional e separado, pois data de compra e data de lançamento podem diferir.
- **MovementType:** `expense`, `income`, `transfer` ou `pending`. Tipo econômico não é inferido apenas pelo sinal do valor.
- **Person:** pessoa proprietária selecionada na importação: `self`, `spouse` ou `shared`.
- **Category:** par `macro` e `micro`. Na planilha, o mapeamento provisório informado foi `Tipo de Fluxo` como macro e `Fluxo` como micro; verificar antes de gerar regras.
- **CategorizationRule:** associação explícita entre descrição e categoria. A regra tem ID para que a sugestão explique sua origem.

## Como funciona a sugestão

1. Chame `suggest_category(transaction, rules)` com uma transação e regras explícitas.
2. Só despesas são candidatas. Entradas, transferências e itens pendentes retornam `not_applicable`.
3. Para despesas, a busca exige descrição exata após converter para minúsculas e normalizar espaços repetidos. Acentos e pontuação continuam significativos. Não há aproximação fuzzy, aprendizado ou categoria padrão.
4. Uma categoria única retorna `suggested`, com a categoria, os IDs das regras e uma explicação.
5. Nenhuma regra retorna `needs_review`; regras iguais que discordam retornam `ambiguous`. Ambas retornam sem categoria sugerida.
6. Uma pessoa pode chamar `result.confirm(category)` após revisar. A categoria sugerida e IDs de origem permanecem preservados; a confirmação é registrada separadamente.

## Exemplo sintético

```python
from datetime import date
from decimal import Decimal

from streamline_finance.categorization import CategorizationRule, suggest_category
from streamline_finance.domain import Category, Money, MovementType, Person, Transaction

rule = CategorizationRule(
    rule_id="synthetic-rule-01",
    description="Mercado Exemplo",
    category=Category(macro="Necessidades básicas", micro="Supermercado"),
)
transaction = Transaction(
    transaction_id="synthetic-transaction-01",
    description="MERCADO EXEMPLO",
    amount=Money.from_decimal(Decimal("-12.34")),
    movement_type=MovementType.EXPENSE,
    person=Person.SELF,
    occurred_on=date(2026, 2, 3),
)
result = suggest_category(transaction, [rule])
```

O exemplo usa somente identificadores e informações inventadas.

## Verificação

Na raiz do repositório:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
```

## Limites conhecidos

- Moeda diferente de BRL não é suportada.
- Taxas, conversão monetária e arredondamento de negócio ainda não existem.
- O tipo de movimento precisa ser informado por regra/adaptador futuro; valor positivo ou negativo isolado não o determina.
- Regras são exatas após normalização de caixa e espaços. Correspondência por aproximação, alias ou prioridade precisa de decisão futura e testes próprios.
- A confirmação ainda é um objeto em memória; persistir auditoria será trabalho de sprint futura.
