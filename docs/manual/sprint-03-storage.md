# Manual de operação — SQLite local e importações

## Finalidade

Este manual explica como confirmar uma prévia válida do adaptador Nubank, guardar transações em SQLite local e revisar possíveis pagamentos de fatura. Confirmar importa os dados; não executar contra arquivos reais sem entender as verificações abaixo.

## Pastas e conteúdo

- `data/db/finance.sqlite3`: banco operacional.
- `data/raw/<sha256-do-arquivo>.csv`: CSV original, mantido byte a byte para auditoria e reprocessamento.
- SQLite guarda valor como centavos inteiros, BRL, datas ISO, IDs de origem, descrição, pessoa, natureza, cabeçalhos/valores de campos de origem, hash do arquivo e histórico de revisão.
- Banco e CSV bruto recebem permissões locais restritas na criação (diretórios 0700; arquivos 0600 em sistemas POSIX). A proteção depende também de login, criptografia do disco e backups do sistema operacional.
- Todos os caminhos `data/` são ignorados pelo Git; nunca force adição desses arquivos.

## Confirmar uma importação

A interface Streamlit e a API já oferecem prévia e confirmação. O exemplo abaixo é apenas para experimentar o repositório isoladamente e não usa o banco operacional.

Exemplo abaixo usa **somente fixture sintética**:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from streamline_finance.domain import Person, SourceKind
from streamline_finance.importers.nubank import preview_nubank_csv
from streamline_finance.storage import FinanceRepository

content = Path("tests/fixtures/nubank_statement_synthetic.csv").read_bytes()
preview = preview_nubank_csv(
    content,
    person=Person.SELF,
    source_key="nubank-main",
    source_kind=SourceKind.BANK_ACCOUNT,
)
if not preview.can_confirm:
    raise ValueError("Revise os erros da prévia")

# Em uma interface, só executar este bloco após ação explícita de confirmação.
with TemporaryDirectory() as temporary:
    with FinanceRepository(Path(temporary) / "db" / "finance.sqlite3") as repository:
        result = repository.confirm_import(
            preview,
            source_key="nubank-main",
            content=content,
        )
        print(result)
```

Não imprima `preview.transactions`, `source_fields`, linhas CSV, IDs, nomes, descrições ou valores de arquivos reais em terminal/logs compartilhados.

## Reimportação e conflitos

- Hash SHA-256 do arquivo + origem identifica reimportação idêntica. Uma repetição retorna `already_imported` e não replica transações.
- ID de transação + origem identifica repetição de uma linha em arquivo diferente. Transação repetida e igual não é inserida de novo.
- Mesmo ID com conteúdo diferente aborta a transação inteira com conflito; não sobrescreve nem escolhe automaticamente qual linha é correta.
- Mudança de pessoa/tipo de origem ao tentar reimportar o mesmo arquivo também gera conflito.
- Compras legítimas com mesmo valor não são deduplicadas pelo valor; IDs de origem distintos permanecem separados.
- Import batch associa todas as transações do arquivo, inclusive linhas que já existiam, para permitir auditoria da origem dos dados.

## Revisar natureza do movimento

Transações importadas entram como `pending`. A natureza não é derivada só de sinal ou descrição. Depois de revisar manualmente, a API chama `review_movement_type(..., confirm=True)`. Mudanças só são aceitas enquanto o movimento ainda estiver pendente; cada decisão é registrada e exige confirmação explícita.

## Candidatos de pagamento de cartão

`refresh_payment_candidates(window_days=5)` sugere pares somente quando:

- uma transação já foi manualmente confirmada como despesa e sua origem está marcada `credit_card`;
- outra transação de origem `bank_account` tem descrição contendo “pagamento” e “fatura” e natureza pendente/transferência;
- a pessoa selecionada é a mesma;
- ambos os lançamentos têm sinal de saída negativo;
- os valores absolutos são iguais até o centavo;
- datas estão dentro da janela configurada.

O candidato fica pendente para decisão humana. Aceitar/rejeitar/resetar candidato **não apaga, mescla nem reclassifica** nenhum movimento. Igualdade exata mais janela de data ainda pode gerar falso positivo; confirmar a associação requer revisão.

Para usar corretamente, o criador da prévia deve passar explicitamente `SourceKind.CREDIT_CARD` quando a origem for cartão. Não infira isso do nome da conta.

## Backup e restauração

Feche os processos que usam o banco e copie conjuntamente `data/db/` e `data/raw/`. O roteiro detalhado, inclusive restauração isolada e verificação de integridade, está no [manual de operação e recuperação](sprint-06-operation.md). Não sobrescreva o banco ativo durante um ensaio.

## Testes

```bash
uv run pytest tests/test_persistence.py
uv run pytest
uv run ruff format --check .
uv run ruff check .
```
