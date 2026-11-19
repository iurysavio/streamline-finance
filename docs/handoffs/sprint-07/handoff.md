# Handoff — Sprint 7: importação de faturas

## Estado

O usuário aceitou explicitamente a Sprint 6 e o v0 e autorizou iniciar o plano. A branch `feat/card-invoices-reconciliation` foi criada antes das mudanças. Sprint 7 implementada para validação; **aguarda aceite explícito do usuário antes da Sprint 8**.

## Escopo e decisões

- Adaptadores isolados para fatura CSV C6 e Nubank; prévias dos arquivos fornecidos foram verificadas localmente apenas por contagens e tipos de erro, sem copiar linhas ou valores. Os arquivos pessoais não foram importados ou modificados durante os testes.
- Os dois formatos observados não possuem identificador único por lançamento. As linhas geradas usam hash do arquivo e número de linha, preservando duplicatas dentro de um arquivo. Mesmo arquivo/cartão/competência é idempotente. Arquivo diferente no mesmo cartão e competência, ou linha idêntica já presente em outra fatura do mesmo cartão, bloqueia a importação inteira. A identificação estável do cartão depende do usuário; não existe liberação/substituição implementada.
- CSVs apresentam compras positivas e créditos negativos conforme confirmação do usuário; valores são invertidos para a convenção interna de saídas negativas em centavos inteiros. Movimentos continuam pendentes: estornos, pagamentos e compras dependem de revisão humana.
- Alguns valores do campo Parcela no CSV C6 fornecido passaram por editor e podem ter sofrido conversão para data. O texto original é preservado sem inferir número/total de parcelas.
- Nova tabela `card_invoices` liga lote, cartão, competência e formato; a criação é aditiva. Migração e reabertura testadas em SQLite sintético. Antes de atualizar o banco operacional, seguir procedimento de backup privado.
- Conciliação com pagamentos, correção de classificações existentes e alternância entre data de compra e competência são escopo da Sprint 8, após aceite da Sprint 7. Enquanto isso, evitar tratar pagamento bancário de fatura como despesa ao revisar lançamentos de cartão; uma despesa já confirmada pode causar contagem dupla.
- Ajustado filtro de datas da tabela para acompanhar mudanças do intervalo principal.

## Verificação e próximo passo

- `.venv/Scripts/python.exe -m pytest`: 133 testes passaram no Windows/Python 3.12, incluindo testes sintéticos dos dois adaptadores, API, migração e UI C6.
- `.venv/Scripts/ruff.exe format --check .`: passou; 57 arquivos verificados.
- `.venv/Scripts/ruff.exe check .`: passou.
- `python -m uv lock --check --offline`: passou.
- `git check-ignore -v` confirmou que os dois arquivos fornecidos e o banco local são ignorados.
- `rtk git diff --check`: passou para arquivos rastreados; novos arquivos devem ser incluídos na revisão antes de eventual commit.
- Antes da inicialização local da branch, `data/db/` e `data/raw/` foram copiados para uma pasta privada em `data/backups/`; hashes de arquivo conferiram e `PRAGMA integrity_check` retornou `ok`. A API foi então iniciada e aplicou a criação aditiva da tabela `card_invoices`. Nenhuma fatura foi importada nessa etapa.

O usuário deve validar os formatos e o processo com segurança, solicitar ajustes ou aceitar explicitamente a Sprint 7 antes da conciliação. A branch ainda pode receber correções; o banco agora tem o esquema aditivo da Sprint 7.
