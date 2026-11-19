# Manual — prévia e importação de faturas CSV

## Antes de usar

- A implementação da Sprint 7 exige aceite do usuário antes da Sprint 8. Faça backup privado do banco e arquivos originais conforme `sprint-06-operation.md` antes de atualizar uma instalação com dados. A primeira abertura atualiza o esquema SQLite de forma aditiva; a migração foi testada em banco sintético, não no seu backup real.
- **A conciliação entre pagamento no extrato e total da fatura ainda não está implementada.** Se o pagamento já foi confirmado como despesa, revisar compras da fatura como despesas pode duplicar os gastos. O mecanismo anterior compara pagamento com compra individual e não deve ser tratado como conciliação de fatura.
- Relatórios ainda usam data de ocorrência/compra; a seleção de competência será implementada na Sprint 8. A competência selecionada aqui fica associada à fatura, mas ainda não filtra os relatórios.
- Os formatos são específicos dos CSVs examinados: C6 com cabeçalhos em português, separados por `;`, e Nubank com `date,title,amount`. Outros layouts são recusados. Não editar originais nem compartilhar linhas pessoais em issues, logs ou fixtures.
- A seleção de formato de fatura está no modo **Meus dados locais**; o importador do sandbox Demo continua aceitando somente extrato bancário sintético.

## Importar

1. Em **Meus dados locais → Importar extrato**, escolha **Fatura C6** ou **Fatura Nubank**, selecione a competência correta, titular e uma identificação estável para cada cartão.
2. Marque a confirmação da origem, selecione **Cartão de crédito** e envie o CSV. Selecione o mesmo código de cartão nas importações futuras: as proteções dependem da identificação informada e não identificam a mesma conta nomeada de outra forma.
3. Gere a prévia. Confira a data, sinais, valor em BRL e todas as colunas originais antes de confirmar. Valores positivos dos CSVs são interpretados como saídas; negativos como entradas. **Todos ficam pendentes**: créditos podem ser pagamentos ou estornos e exigem revisão de natureza.
4. O campo C6 `Parcela` é preservado exatamente como veio. Um editor pode converter frações em datas; esses valores não são interpretados nem corrigidos automaticamente. Se o arquivo foi regravado por editor, compare com a fatura original antes de confirmar.
5. Após revisão, marque a confirmação e salve. O CSV original é guardado em `data/raw/` e os movimentos, no SQLite. A prévia, por si só, não grava.

## Reimportação e situações que exigem revisão

- O mesmo arquivo, cartão e competência é idempotente. Compras idênticas dentro do mesmo arquivo são preservadas como linhas distintas.
- Arquivo diferente para o mesmo cartão e competência é bloqueado. Uma linha original idêntica já importada em outra competência do mesmo cartão também bloqueia a importação inteira, inclusive quando poderia ser uma compra legítima. Não há ainda fluxo de substituição, mesclagem ou liberação: preserve os arquivos e peça revisão.
- Alterar a identificação do cartão pode contornar essas proteções; mantenha o mesmo código para o mesmo cartão e não reutilize um código para cartões ou formatos diferentes.
- Data, competência e sinal dependem do CSV e da confirmação do usuário. Parcelas, juros, pagamentos, créditos e estornos não são classificados automaticamente. Entradas em moeda estrangeira mantêm os campos originais e usam o valor em reais informado no CSV, sem conversão calculada pelo app.

## Verificação

Os testes usam somente exemplos sintéticos: `python -m uv run --locked pytest tests/test_c6_invoice.py tests/test_nubank_invoice.py tests/test_invoice_api.py`. Para testes de regressão, rode a suíte completa conforme o manual de operação.
