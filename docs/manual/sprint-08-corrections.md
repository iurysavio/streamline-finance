# Manual — corrigir classificação de movimentações antigas

## Finalidade e pré-verificações

Corrigir natureza ou categoria de uma movimentação já confirmada, sem excluir a importação nem modificar o CSV, valor, pessoa, descrição ou datas originais. A correção é individual e registrada no histórico da transação. API e Streamlit devem estar ativos somente em `127.0.0.1`; mantenha backup privado antes de mudanças nos dados locais conforme `sprint-06-operation.md`.

## Corrigir um pagamento de fatura classificado como despesa

1. Em **Meus dados locais → Revisar movimentações**, escolha **Já revisadas**. Filtre por mês da movimentação no extrato, pessoa, origem, natureza **Despesa** e um trecho da descrição. Os filtros listam apenas registros já classificados; a data exibida é a data original do movimento bancário.
2. Selecione a movimentação correta; confira origem, data, descrição, valor, natureza e categoria atuais. Escolha **Transferência** como nova natureza. A prévia indica a mudança no gasto do período; a categoria de despesa será removida da classificação atual, mas permanece no histórico de revisões.
3. Marque **Confirmo esta correção** e clique em **Salvar correção**. A análise e os relatórios refletem a nova classificação sem reimportar o extrato. Reabra a movimentação e consulte **Histórico de revisões** para conferir a alteração.
4. Se a API responder que a classificação mudou, clique em **Recarregar classificação**, confira novamente e só então confirme. Se não reconhecer o pagamento, não altere a natureza.

## Outras correções e recuperação de falhas

- Para corrigir uma categoria de despesa, mantenha **Despesa** e escolha macro/microcategoria válidas. Ao converter **Entrada** ou **Transferência** em despesa, selecione ambas. Só despesas podem ter categoria. O formulário não permite alterar o valor original nem criar uma associação automática com uma fatura.
- Se a API estiver offline, inicie-a conforme `sprint-06-operation.md`. Uma solicitação sem confirmação, sem categoria obrigatória ou baseada em estado desatualizado é recusada sem gravar parcialmente. Para desfazer uma classificação, selecione de novo o registro e faça uma nova correção confirmada; a decisão anterior continua no histórico.
- Corrigir um pagamento para **Transferência** retira esse movimento dos gastos, mas **não demonstra qual fatura ele liquidou**. Conciliação entre pagamento e fatura, pagamentos parciais e vinculação auditada ainda serão tratados depois nesta sprint.
- Para verificar em desenvolvimento, execute `.venv/Scripts/python.exe -m pytest tests/test_corrections.py` com o banco sintético temporário. Não use dados pessoais em testes ou capturas públicas.
