# Handoff — Sprint 0: Descoberta e fundação segura

## Status

**Concluída e aceita pelo usuário.** A Sprint 1 foi iniciada após esse aceite. Nenhum app/API foi implementado durante a Sprint 0.

## Objetivo desta sprint

Descobrir os formatos de entrada com metadados seguros, proteger dados reais no Git, preparar ambiente e fixtures sintéticas, testar que a fundação é reproduzível e documentar como iniciar o sistema.

## Dados locais inventariados

Há um extrato bancário Nubank em `data/input/` e uma planilha histórica em `data/historical/`. Ambos contêm dados financeiros reais e são ignorados pelo `.gitignore`. Não copiar nomes de arquivos originais, linhas, identificadores, observações, nomes de terceiros ou valores para este handoff, fixtures, logs, issues ou CI.

## Metadados seguros descobertos

### CSV exemplo: extrato Nubank

- Cabeçalhos: `JasData`, `Valor`, `Identificador`, `Descrição`.
- Separador: vírgula.
- Codificação: leitura UTF-8 com BOM tolerado.
- Data observada: `DD/MM/YYYY`.
- Valor observado: sinal positivo/negativo, ponto decimal, sem símbolo monetário.
- O formato contém movimentos de natureza diversa; não tratar todo débito como despesa nem todo crédito como receita. O extrato inclui transferências, boletos e pagamento de fatura; tipo precisa ser preservado/classificado.
- `Identificador` parece ser chave de origem da transação; guardar no domínio apenas se a validação confirmar unicidade/estabilidade. Nunca registrar valores reais de identificador neste documento.
- Escopo confirmado para esta fase: somente o extrato Nubank. O formato da fatura de cartão fica para sprint posterior, quando o usuário fornecer cabeçalhos/formato seguros.

### Planilha histórica

- Abas: `Entrada`, `Mensal`, `Orçamento`, `Patrimônio`, `Descrição das despesas`, `Detalhamento`.
- Cabeçalho observado em `Entrada`: `Data`, `Valor (R$)`, `Fluxo`, `Tipo de Fluxo`, `Classificação`, `Observação`, `Mês/Ano`, `Quem gastou?`.
- Cabeçalho observado em `Descrição das despesas`: `nº`, `Fluxo`, `Descrição`, `Tipo de fluxo`, `Classficação` (ortografia original da coluna).
- Mapeamento de trabalho indicado pelo usuário como provável: `Fluxo` = microcategoria; `Tipo de Fluxo` = macrocategoria; `Classificação` = natureza. Confirmar estrutura e valores sem expor dados pessoais antes de usar para treinamento de regras.
- Pessoa responsável é escolhida na importação; `Quem gastou?` não sobrescreve essa escolha no MVP.
- Planilha inclui áreas/abas também voltadas a receitas, orçamento e patrimônio. O MVP de despesas não deve descartar entradas ou transferências encontradas em extratos; deve distingui-las de despesas.
- A estrutura de cabeçalho não é uniforme: cabeçalhos úteis começam na linha 2, não necessariamente na primeira linha da aba. Revisar possíveis células mescladas/variações antes de escrever o leitor.
- O significado exato de macros/micros e valores possíveis ainda requer confirmação do usuário, sem expor conteúdo pessoal.

## Decisão de escopo derivada

O v0 segue centrado em relatórios de despesas, mas a ingestão deve manter classes `expense`, `income`, `transfer` e `pending` (nomes finais podem ser em português) para evitar falsos gastos. Pagamentos de cartão e compras da fatura exigem detecção conservadora de correspondências e revisão humana; nunca remover automaticamente por valor aproximado.

## Escopo ainda não implementado

1. Antes de usar categorias para regras, confirmar o mapeamento da planilha com o usuário sem compartilhar valores pessoais.
2. O CSV de fatura será mapeado quando entrar na sprint adequada; não é pré-requisito para a fundação limitada ao extrato Nubank.
3. Regras de categorização, modelo financeiro, API, Streamlit, importador de produção, banco operacional e detecção de duplicatas pertencem a sprints seguintes.

## Mudanças feitas nesta sessão

- Criado `.gitignore` raiz. Regras cobrem `/data/`, arquivos SQLite, `.env`, segredos Streamlit e caches comuns de Python/testes.
- `git check-ignore -v` confirmou que os arquivos locais nas pastas de dados são ignorados por `/data/`.
- Atualizado `docs/plans/v0.md` para preservar/classificar entradas e transferências e excluí-las dos agregados de despesa.
- Este handoff registra somente metadados de formato e estrutura, sem valores de transação.
- Organizado `pytest` e `ruff` como dependências de desenvolvimento no `pyproject.toml`; definido Python suportado `>=3.12`, configuração do pytest e lint/format do Ruff.
- Isolado explicitamente o workspace uv deste repositório com `tool.uv.workspace.members = []`; a pasta pai possui um workspace distinto e não deve fornecer dependências/ambiente para este projeto.
- Criado `uv.lock` local e ambiente `.venv/` para instalação reproduzível. Lockfile/ambiente deste repo devem permanecer independentes e o ambiente é ignorado pelo Git.
- Criada fixture sintética em `tests/fixtures/nubank_statement_synthetic.csv` com cabeçalhos compatíveis e registros inventados.
- Criados dois testes de fundação: leitura de cabeçalhos/data/valor da fixture e proteção do `.gitignore` contra caminhos de `data/`.
- Criado workflow GitHub Actions para pytest e Ruff em Python 3.12 e 3.13, com permissões somente de leitura do conteúdo.
- Criado `docs/manual/sprint-00-setup.md` com instalação, comandos de qualidade, verificação de privacidade e recuperação de falhas.
- Atualizados README e AGENTS.md para apontar aos comandos reais e documentação atuais.

## Verificações executadas

- `rtk git ls-files`: apenas `README.md` está atualmente rastreado; ainda não há dado financeiro adicionado ao índice.
- `rtk git check-ignore -v` nos dois caminhos locais: ambos ignorados por `.gitignore` raiz. Os nomes originais foram omitidos deste handoff por privacidade.
- Leitura do CSV restrita ao cabeçalho/formatos nesta etapa; nenhum identificador ou linha copiado para docs.
- Inspeção da planilha usando metadados OOXML: nomes de abas e cabeçalhos, sem colocar células de transação no handoff.
- Primeira tentativa de `uv lock`/`uv sync` antes de declarar workspace vazio foi detectada como executada no workspace da pasta pai (`/Users/nsx/Documents/Pessoal`), usando `/Users/nsx/Documents/Pessoal/.venv` e lockfile externo. O sync removeu 68 pacotes desse ambiente compartilhado; depois foi identificado no comando que o manifesto externo inclui este repo como membro.
- Não editei arquivos fora do repositório. A configuração foi corrigida localmente com workspace vazio e os comandos subsequentes confirmaram lock e `.venv` próprios. O ambiente da pasta pai foi deixado intocado após a detecção.
- `uv lock --offline`: passou no projeto isolado, resolvendo 10 pacotes.
- `uv sync --offline`: passou e instalou dependências no `.venv/` local.
- `uv run pytest`: passou; 2 testes.
- `uv run ruff format --check .`: passou; arquivos formatados.
- `uv run ruff check .`: passou.
- `uv lock --check --offline`: passou após isolar o workspace; 10 pacotes resolvidos para este projeto.
- `uv sync --locked --offline`: passou usando somente `.venv/` da raiz do repo e lockfile local.
- `rtk git check-ignore -v` nos dois caminhos de dados locais e `.venv/bin/python`: todos ignorados pela raiz.
- `rtk git diff --check`: passou.
- Versões locais verificadas: Python 3.13.5, uv 0.9.21. A matriz CI para Python 3.12/3.13 foi configurada, mas não foi executada pelo GitHub nesta etapa.
- `openpyxl` está declarado e instalado pelo ambiente; nenhuma transação real foi lida ou colocada em fixtures/docs.
- API e app não existem ainda por escopo; início de API/Streamlit não faz parte do aceite da fundação.

## Próximo passo

O usuário aceitou a Sprint 0 e autorizou o início da Sprint 1. Ver `docs/handoffs/sprint-01/handoff.md`; os metadados da planilha continuam sendo hipótese até confirmação antes de gerar regras.
