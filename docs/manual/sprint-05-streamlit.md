# Manual de operação — painel Streamlit

## Finalidade

O painel é a interface visual do projeto. FastAPI continua responsável por validar pedidos, enquanto o domínio define regras e o SQLite mantém os registros locais. O painel não importa arquivos nem mostra transações reais automaticamente ao iniciar.

## Iniciar e parar

1. No terminal, vá à raiz do repositório e execute `uv sync` depois de atualizar o projeto.
2. A navegação usa páginas nativas do Streamlit; títulos aparecem enumerados na sidebar sob “Finanças da Família Sávio”.
3. Inicie a API em um terminal:

   ```bash
   uv run uvicorn streamline_finance.api:app --host 127.0.0.1 --port 8000
   ```

4. Em outro terminal, inicie a interface:

   ```bash
   uv run streamlit run app.py --server.address 127.0.0.1
   ```

5. Abra o endereço local mostrado pelo Streamlit. A interface começa em Demo, com dados sintéticos; não mude o bind para `0.0.0.0`, pois API não tem login nesta sprint.
6. Para parar cada processo, use `Ctrl+C` no terminal correspondente.

## Primeira tela

O app usa navegação nativa do Streamlit e lista “Análise de gastos”, “Importar extrato” e “Revisar movimentações” na sidebar sob o título familiar.

O modo inicial é Demo. Gera histórico sintético, determinístico, com várias pessoas e meses. Pode testar revisões e importar um CSV fictício para sandbox em memória. Alterações demo não chamam persistência; alternar para dados locais descarta a cópia demo.

Na página de análise, escolha intervalo de datas, granularidade (mês/semana/dia), pessoa e uma dimensão por vez (total, pessoa, macro ou microcategoria). O gráfico Altair é interativo: tooltip, zoom e seleção temporal. Selecionar uma única dimensão evita excesso de séries. O total é gasto líquido positivo (despesas menos estornos), exclui entradas e transferências; pendências também não contam.

Abaixo da tendência aparece uma tabela com os 10 gastos individuais de maior valor, usando os mesmos filtros de período e pessoa.

O top gastos é por transação individual, não soma estabelecimentos. Estornos, entradas, transferências e movimentos pendentes não aparecem. Se houver despesa confirmada sem macro ou microcategoria dentro do período/pessoa, aparece “Revisar transações sem categoria”; o botão abre a revisão já filtrada e fica oculto quando nenhuma estiver pendente. Títulos usam ícones; passe o mouse sobre o ícone de ajuda junto ao título para ver a explicação contextual.

Na comparação, os cards de valores aparecem antes do gráfico. O gráfico mostra o intervalo selecionado e os dias imediatamente anteriores com a mesma duração. A variação é `(atual - anterior) / anterior × 100`; se o período anterior for zero, o painel mostra “—”, pois o percentual não é calculável. As barras exibem valores diretamente. A variação usa fonte grande, igual aos outros cards: queda de gastos aparece com seta para baixo e verde; aumento aparece com seta para cima e vermelho.

A página de revisão só carrega regras históricas quando você marca confirmação do mapeamento provisório. Procura, nesta ordem, `data/historical/ControleFinanceiro_VR-2.xlsx` e `data/reference/ControleFinanceiro.xlsx`; lê o workbook escolhido em memória e não o copia ou renomeia. Se nenhum arquivo existir, classificação manual continua disponível. Arquivos reais nunca são carregados em Demo.

Relatório inclui somente movimentos:

- com tipo confirmado como `expense`;
- cuja data de ocorrência cai no mês escolhido;
- da pessoa selecionada, se houver filtro.

Movimentos pendentes, entradas e transferências não entram em gastos. Valor positivo marcado explicitamente como despesa — por exemplo, estorno — reduz o total líquido. Valores são centavos inteiros e formatados em BRL sem float.

## Importação

1. Em Demo, teste apenas com CSV sintético; a prévia e confirmação adicionam linhas à sandbox em memória, nunca ao banco.
2. Para dados locais, selecione “Meus dados locais” na sidebar e abra “Importar extrato”.
3. Escolha pessoa, identificação da conta/origem e tipo (conta bancária/cartão); confirme que a identificação corresponde à origem.
4. Envie somente CSV do formato suportado e gere prévia.
5. Confira contagem, datas, sinais, pessoa e campos originais.
6. Confirme apenas depois de revisar. A confirmação persiste o original em `data/raw/` e movimentos no SQLite.

Se a prévia falhar, nenhuma transação é gravada; corrija o arquivo de origem e tente novamente. Não edite/reescreva o arquivo original automaticamente.

## Categorias

- Categorias do histórico só são carregadas em dados locais após confirmar o mapeamento provisório da planilha.
- Regras são exatas (ignorando caixa e espaços repetidos); sem regra ou com conflito, painel pede revisão.
- Sugestão mostra regra de origem. Ela não é aplicada automaticamente. A pessoa escolhe ou corrige categoria e confirma.

## Pagamento da fatura

Candidatos exatos aparecem na revisão, não como exclusão automática. Confira a transação da fatura e a saída bancária; aceitar associação não apaga as duas linhas. Se não reconhecer, rejeite o candidato. Não considere valor aproximado prova de que é a mesma operação.

## Privacidade e recuperação

- API e UI locais não têm autenticação nesta sprint; não exponha servidor para rede.
- Não copie descrições, valores, nomes nem arquivos financeiros em bugs, capturas de tela públicas, logs ou CI.
- Faça backup privado do SQLite e CSVs brutos; procedimento e recuperação seguem o manual da Sprint 3. Nunca use dataset real em testes.

## Verificação de desenvolvimento

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
```

## Checklist visual antes de aceitar esta sprint

Faça essa validação somente em modo Demo:

- Sidebar mostra as três páginas e o título da família.
- Gráfico mostra meses suficientes, e filtros de intervalo/granularidade/detalhamento atualizam os pontos.
- Tooltip, zoom e seleção temporal funcionam sem perder contexto.
- Alternar pessoa/recorte muda gráfico e totais de forma consistente.
- CSV sintético aparece em prévia, e import sandbox deixa os totais Demo mudarem sem tocar SQLite.
- Revisar uma movimentação Demo altera a sessão; sair de Demo e voltar reseta os dados sintéticos.
- Nenhum arquivo real ou captura de tela com transações pessoais entra no Git.
