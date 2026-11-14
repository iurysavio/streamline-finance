# Manual de operação — prévia de extrato Nubank

## Finalidade

Este passo lê um CSV do formato de extrato Nubank suportado e prepara uma prévia em memória para conferência. Ele **não salva** transações, não altera o arquivo, não grava cópia bruta e não determina sozinho se uma movimentação é despesa, entrada ou transferência.

## Antes de começar

- Após clonar ou atualizar o projeto, execute `uv sync` na raiz. Isso instala o pacote em modo editável no `.venv`; `uv run` sozinho não torna automaticamente um projeto `src/` importável se o projeto não estiver empacotado/instalado.
- Os dados reais permanecem em pastas locais ignoradas pelo Git.
- O adaptador aceita os cabeçalhos exportados `JasData`, `Valor`, `Identificador` e `Descrição`. Normaliza espaços periféricos e marcas invisíveis; na prévia, o nome com erro `JasData` aparece como `Data` e somente os quatro campos reconhecidos são mostrados em ordem padrão.
- Data precisa ser `DD/MM/YYYY`, em data válida do calendário.
- Valor precisa usar sinal opcional `-`, ponto decimal e zero, uma ou duas casas. Exemplos sintéticos aceitos: `10`, `10.5`, `10.50`, `-10.50`. Vírgula decimal, notação exponencial, valores infinitos e mais de duas casas são recusados — nunca convertidos silenciosamente.
- Codificação de bytes suportada: UTF-8, com ou sem BOM.
- A pessoa da importação deve ser escolhida explicitamente como `Person.SELF`, `Person.SPOUSE` ou `Person.SHARED`.

## Executar uma prévia em memória

Com a aplicação ainda não conectada a uma interface, o adaptador pode ser exercitado pelo Python local usando somente dados sintéticos:

```bash
uv run python -c '
from pathlib import Path
from streamline_finance.domain import Person
from streamline_finance.importers.nubank import preview_nubank_csv

content = Path("tests/fixtures/nubank_statement_synthetic.csv").read_bytes()
preview = preview_nubank_csv(content, person=Person.SELF)
print("Pode confirmar:", preview.can_confirm)
print("Linhas válidas:", len(preview.transactions))
print("Erros:", len(preview.errors))
'
```

Use `uv run --locked` se quiser que o comando falhe quando o lockfile não corresponder ao manifesto. Não rode o Python global do sistema para esse teste.

Não imprima nem registre descrições, identificadores, valores, campos de origem ou linhas de CSV real.

## Fluxo previsto para uma pessoa

1. Escolha o arquivo e a pessoa dona da conta/extrato.
2. Gere a prévia em memória.
3. Confira a tabela de data, descrição e valor; a seção expansível apresenta as quatro colunas em ordem padronizada, pessoa escolhida e identificador de origem.
4. Resolva as mensagens de validação na origem. Erros indicam número da linha e campo, nunca copiam o conteúdo da linha.
5. Só apresente ação “confirmar” quando `preview.can_confirm` for verdadeiro e a pessoa tiver revisado a prévia.
6. Nesta sprint não há operação de confirmação persistente: fechar o processo descarta a prévia. A gravação e idempotência serão implementadas em sprints posteriores.

## Significado dos resultados

- `transactions`: linhas válidas normalizadas; cada movimento ainda tem tipo `pending` e categoria vazia.
- `source_fields`: quatro campos normalizados (`Data`, `Valor`, `Identificador`, `Descrição`); o cabeçalho exportado `JasData` aparece como `Data`.
- `errors`: bloqueiam confirmação até que o arquivo seja corrigido.
- `skipped_blank_lines`: posições de linhas inteiramente vazias que não representam movimentos.
- `can_confirm`: verdadeiro somente se há pelo menos uma transação, nenhuma linha inválida e nenhum erro de leitura. Não significa que houve gravação.

## Falhas e recuperação

- **Cabeçalho diferente:** confira acentos, grafia e colunas obrigatórias; não renomeie uma coluna real sem entender sua semântica.
- **`ModuleNotFoundError: streamline_finance`:** confirme que está na raiz correta do repositório e execute `uv sync`; depois repita o comando via `uv run`. Se persistir, confira `build-system` e a configuração de descoberta `src` em `pyproject.toml`.
- **Data inválida:** confirme dia/mês/ano na origem; não tente adivinhar se a data era mês/dia/ano.
- **Valor inválido:** mantenha a grafia original e corrija a regra de parse só com aprovação e teste sintético. Não arredonde nem remova separadores automaticamente.
- **Linha irregular/CSV inválido:** reexporte ou corrija uma cópia de trabalho; mantenha o original intocado.
- **Movimento parece transferência ou pagamento de fatura:** deixe pendente. O valor e o sinal não bastam para classificá-lo.
- **Aparecer informação financeira em log ou erro:** interrompa a execução, não compartilhe a mensagem bruta e trate somente um resumo sem valores/identificadores.

## Testes

```bash
uv run pytest tests/test_nubank_import.py
uv run pytest
uv run ruff format --check .
uv run ruff check .
```
