# Handoff — Sprint 8: conciliação de faturas

## Status

Sprint 7 aceita explicitamente e Sprint 8 autorizada pelo usuário. **Primeira etapa implementada: correção individual de natureza e categoria já confirmadas. Sprint 8 não concluída**; a associação pagamento ↔ fatura e a escolha da visão por data da compra/competência continuam pendentes.

## Etapa de correção

- API e repositório têm fluxo separado do registro inicial para alterar uma classificação já confirmada. O pedido compara natureza e categoria anteriores; se houver mudança concorrente ou nenhum ajuste, retorna conflito sem sobrescrever. A atualização e os eventos de auditoria ocorrem na mesma transação SQLite. Os valores, datas, arquivos brutos e identificadores continuam intactos.
- Streamlit oferece **Já revisadas** na página de revisão: filtros por mês original, pessoa, origem, natureza e descrição, seleção de um movimento e prévia do impacto em centavos formatados em BRL. Após confirmar, permite consultar o histórico. Há opção de recarregar quando a classificação mudou durante o preenchimento.
- Testes de integração usam somente CSV inventado, FastAPI TestClient, AppTest e banco temporário. Cobrem correção de pagamento bancário de despesa para transferência, recalcular gasto sem mexer nas outras compras, bloqueios de confirmação ausente/estado desatualizado, mudança de categoria, reabertura e reimportação idempotente.
- Operação documentada em `docs/manual/sprint-08-corrections.md`. O banco local do usuário não é usado nos testes nem tem transações modificadas automaticamente.

## Verificações desta etapa

- `.venv/Scripts/python.exe -m pytest`: **140 testes passaram** em Windows/Python 3.12, incluindo API, AppTest e reabertura do banco sintético.
- `.venv/Scripts/ruff.exe format --check .`: **60 arquivos formatados**.
- `.venv/Scripts/ruff.exe check .` e `rtk git diff --check`: passaram.
- Este checkpoint inclui as correções da Sprint 7 e a primeira etapa da Sprint 8 na branch `feat/card-invoices-reconciliation`; nenhuma transação real foi aberta para teste.

## Próximo passo

Validar a correção localmente e continuar o projeto de conciliação da fatura com pagamento e da seleção de critério de data, ainda sujeito aos demais critérios da Sprint 8. Não marcar a Sprint 8 como concluída até esses passos e aceite do usuário.
