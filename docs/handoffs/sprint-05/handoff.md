# Handoff — Sprint 5: Interface Streamlit

## Status

**Concluída e aceita explicitamente pelo usuário.** O usuário aprovou a Sprint 5 e autorizou o início da Sprint 6 em 15/11/2026.

## Escopo desta implementação

Painel local sobre API FastAPI existente, sem acesso direto do Streamlit ao banco. Primeiro objetivo: resumo mensal por pessoa/categoria e fluxo de importação com pessoa/origem, prévia, erros e confirmação explícita. Sem sincronização, login, hospedagem ou upload automático.

Design refinado pelo usuário: navegação nativa multipágina; Demo inicial com sandbox interativo descartável; tendência mês/semana/dia, intervalo livre e uma dimensão por vez; planilha procurada no caminho local histórico conhecido sem copiá-la.

Pedido adicional aprovado: abaixo da tendência, gráfico/lista de top 10 despesas individuais no mesmo intervalo e gráfico de comparação com intervalo anterior de mesmo número de dias; variação percentual. Despesas sem categoria (macro/micro ausente) exibem botão para ir diretamente à revisão; botão oculto quando count=0.

## TDD e implementação

Os itens abaixo registram o estado e as verificações históricas da implementação inicial; ajustes posteriores, incluindo a troca de Altair por Plotly, estão em “Ajuste solicitado durante aceite”. Contagens de testes e estado do banco abaixo são históricos, não uma descrição do banco atual.

- Testes sintéticos para estado vazio, filtro pessoa/mês, estados de API indisponível, upload inválido e confirmação condicionada a prévia válida.
- Preview sintética da planilha exige confirmação do mapeamento, gera regras somente em memória e nunca importa o arquivo direto para a base.
- Relatório mensal calcula em centavos, positiva saída líquida como gasto e só inclui expense confirmado; estornos registrados como expense positiva reduzem gasto.
- Usar `streamlit.testing.v1.AppTest` onde suportado e testar view-model/helpers sem navegador. Não guardar respostas ou fixtures com dados reais.
- Teste end-to-end HTTP/API usa FastAPI TestClient e DB temporário; import jamais aponta para `data/` do usuário.
- `tests/test_streamlit_app.py` valida Demo inicial, navegação de páginas, Altair com seleção temporal e import/revisão sandbox sem persistência.
- Resumo adiciona endpoint `/reports/top-expenses`, `/reports/period-comparison` e `/transactions/uncategorized` com período/pessoa inclusivos.
- Top expenses seleciona as 10 maiores saídas individuais e exclui estornos; comparação atual vs período anterior contíguo de mesma duração; percentual é `None` quando baseline é zero.
- Alerta de despesas sem categoria filtra por intervalo/pessoa e navega para review; a página review recebe contexto para filtrar gastos sem categoria.
- API de top gastos devolve até 10 saídas individuais sem agrupar estabelecimento; API de comparação devolve intervalo inclusivo atual e anterior contíguo de duração igual, totals e percentual (null se baseline zero).
- Solicitação final implementada: top gastos somente em tabela; cards de comparação antes das barras com labels de valores; títulos com emoji e ajuda contextual no hover do header.
- O card de variação usa valor grande no tamanho dos cards adjacentes; seta explícita para baixo verde quando gastos caem e seta para cima vermelha quando aumentam. Baseline zero continua “—”.
- Correção reportada: barras de comparação ficaram invisíveis/imperceptíveis. Gráfico agora ancora o eixo em zero, usa azul de maior contraste e rótulos BRL claros com contorno acima de cada barra; `.interactive()` removido desta visualização. Teste valida cor, escala, rótulo e ausência de zoom redundante.
- Altair é usado para gráficos; já faz parte do conjunto de dependências do Streamlit.
- Modo Demo gera movimentos sintéticos determinísticos; revisão/importo demo alteram apenas Session State, sem chamar rotas de escrita nem banco.
- Modo Real chama API e resumo SQLite; somente after selecting explicitly in sidebar. API permanece loopback.
- O entrypoint usa `st.navigation` com arquivos em `pages/`; labels amigáveis vêm de `st.Page`. AppTest navega pelos caminhos de arquivo.
- A navegação usa páginas `st.Page` definidas pelo entrypoint, enumeradas na sidebar sob título familiar e seletor Demo/Real.
- A planilha histórica é consultada em `data/historical/ControleFinanceiro_VR-2.xlsx` e fallback `data/reference/ControleFinanceiro.xlsx`, somente após confirmação do mapeamento; os arquivos não são movidos.
- `app.py` implementa router nativo e alternância de modo.
- `pages/1_Análise.py`, `pages/2_Importar.py`, `pages/3_Revisar.py` são páginas enumeradas.
- Resumo usa gráfico Altair interativo com granularidade/dimensão únicas escolhidas, intervalo e filtro de pessoa.
- Data sintética demo não é armazenada ou misturada a SQLite real.
- Importação exige origem/pessoa/tipo, checkbox de confirmação da origem, upload, prévia incluindo campos originais, mensagens de erro seguras e checkbox + botão para persistir.
- Revisão lista pendentes; gastos usam sugestão exata quando mapeamento da planilha foi explicitamente confirmado; natureza+categoria confirmadas num único endpoint. Entradas/transferências não entram no gasto agregado.
- FastAPI expõe `POST /categories/historical-rules/preview`: lê workbook só em memória, exige `confirm_column_mapping=true`, não persiste regras automaticamente.
- Sumário positivo de gasto deriva do valor signed em centavos (saída negativa => gasto positivo; estorno positivo => reduz gasto líquido). Sem float.
- Todos os testes Streamlit usam TestClient com DB temporário em `tempfile`; não usam `data/` local.
- API exige host loopback e bloqueia cliente não-loopback e mutations cross-origin.

## Decisões de interface

- Estado inicial mostra mês corrente e sem dados; vazio é estado válido.
- Erros mostram mensagem segura, status/campo e ação de correção; não imprimir body bruto, conteúdo de upload ou identificador real.
- Somente despesas com natureza confirmada contam no relatório; entradas, transferências e pendências não contam.
- Valor aparece em BRL vindo da API como centavos inteiros; nenhum cálculo de dinheiro com float no Streamlit.
- Sugestões de categoria são só sugestões; confirmação/correção exige ação humana.
- App vinculado a loopback; não expor rede porque não há autenticação.

## Arquivos previstos

- `app.py`: entrada do Streamlit.
- `pages/1_Análise.py`, `pages/2_Importar.py`, `pages/3_Revisar.py`: páginas multipage.
- `src/streamline_finance/ui_summary.py`: cálculo do resumo mensal e formatação de BRL.
- `src/streamline_finance/rules.py`: leitura explícita e segura de regras de gasto do histórico.
- `src/streamline_finance/demo_data.py`: dados fictícios determinísticos e edição in-memory.
- `tests/test_streamlit_app.py`, `tests/test_historical_rules.py`, `tests/test_spending_summary.py`.
- `tests/test_demo_data.py`.
- `tests/test_api.py`: contrato de tendência, filtro, dimensão e validação.
- `tests/test_api.py`/`tests/test_spending_summary.py`: top-N, comparação, baseline zero e contagem da revisão.
- `docs/manual/sprint-05-streamlit.md`.

Helpers de resumo ficam em `ui_summary.py`; `demo_data.py` produz dados artificiais. Cliente HTTP fica em `ui_pages.py`. A planilha real em `data/historical/` só será lida localmente após o usuário confirmar o mapeamento; não foi aberta ou alterada durante implementação.

## Segurança

Não abrir arquivos reais para desenvolver/testar UI. Verificar que banco local continua sem lote sintético/de demonstração, e `git status` ignora `data/`. Nunca gravar valores financeiros em session dump, stdout ou screenshot a ser versionada.

## Critérios de aceite e verificações

- Resumo filtra por intervalo/pessoa e granularidade mês/semana/dia; dimensão única é total/pessoa/macro/micro.
- Gasto líquido em BRL considera somente despesas confirmadas e reduz estornos; transferências, receitas e pendências ficam fora.
- App abre Demo, apresenta banner, gera tendência Altair e oferece sandbox import/revisão; sair do Demo remove estado temporário sem gravar no SQLite.
- Modo local permite prévia e confirmação explícita, e revisão de natureza/categoria.
- Workbook esperado é pesquisado apenas nos dois caminhos conhecidos e somente depois de confirmação do mapeamento.
- `uv run pytest`: passou; 103 testes totais.
- `uv run ruff format --check .`: passou; 47 arquivos verificados.
- `uv run ruff check .`: passou.
- `uv lock --check --offline` e `uv sync --locked --offline`: passaram.
- `git diff --check`: passou.
- `git check-ignore -v` confirmou DB/raw/reference, histórico, extrato, `.venv/` e `.egg-info/` ignorados.
- Banco local ao fim: 0 batches e 0 transações; nenhuma linha pessoal foi lida nos testes.
- AppTest valida Demo inicial, navegação, gráficos Altair interativos, sandbox e mudanças in-memory. A UI manual visual segue como verificação de aceitação do usuário.
- Smoke test iniciou API e Streamlit simultaneamente em portas loopback; ambos permaneceram ativos e foram encerrados pelo teste. Tela visual interativa ainda deve ser conferida pelo usuário em Demo.

## Próximo passo

Prosseguir com a Sprint 6 autorizada; consultar `docs/handoffs/sprint-06/handoff.md` para o estado atual.

## Ajuste solicitado durante aceite

- Painel usa Plotly, tooltip BRL, cards de microcategoria/economia/maior saída e tabela de despesas do período com filtros. Pivot foi adiada pelo usuário.
- Revisão usa seletores de categorias dependentes e cadastro separado. Catálogo SQLite é aditivo e Demo mantém catálogo somente em memória; pares da planilha autorizada e revisões prévias aparecem nas opções.
- Diagnóstico local mostra aba, linha e motivo de categorias incompletas ou conflitantes na planilha, sem editar a planilha.
- Busca da planilha inclui `data/historical/ControleFinanceiro_VR.xlsx` antes dos caminhos anteriores, sem mover arquivos.
- Categorias incompletas e conflitos na planilha não impedem o carregamento das demais regras. As descrições afetadas não geram sugestões, inclusive a partir do histórico do app, enquanto o mapeamento da planilha estiver ativo.
- Prévia e revisão sugerem categorias por descrição exata normalizada a partir das despesas confirmadas no banco e, após confirmação do mapeamento, das regras da planilha. Origens são exibidas; conflitos exigem revisão manual. Sugestões não classificam nem gravam automaticamente.
- A revisão aceita usar uma sugestão em movimento pendente antes de confirmar sua natureza. Importações continuam pendentes até revisão humana.
