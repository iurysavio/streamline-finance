# Planos de evolução

Este diretório descreve a evolução do projeto antes de qualquer sprint de implementação. Os planos são propostas operacionais: decisões que dependem dos arquivos reais só serão fechadas depois de examinar nomes de abas, cabeçalhos e formatos — sem colocar transações reais no Git ou nesta documentação.

## Planos

- [v0 — Aplicação local para despesas](v0.md)
- [v1 — Fluxo financeiro familiar](v1.md)
- [v2 — Engenharia analítica](v2.md)
- [v3 — Acesso compartilhado e hospedagem](v3.md)

## Portões de aceite

1. **Antes da Sprint 0:** o usuário revisa e aceita explicitamente os quatro planos. Até lá, nenhuma sprint de implementação começa.
2. **Entre sprints:** a sprint seguinte só começa depois que o usuário aceita explicitamente a sprint anterior concluída. Silêncio ou aprovação do plano geral não conta como aceite de uma sprint concluída.
3. Se critérios de aceite falharem, registrar o que falta no handoff e parar para correção; não avançar por conveniência.
4. Mudanças de escopo, privacidade ou custo devem ser apresentadas para decisão antes de serem aplicadas.

## Método comum das sprints

- Trabalhar em ciclos **vermelho → verde → refatorar**: escrever primeiro um teste de comportamento que falha, implementar o mínimo para fazê-lo passar e então melhorar o desenho preservando os testes.
- Usar fixtures inventadas. CSV, planilhas, banco local, backups, exports e segredos com dados reais nunca entram no Git nem em logs de CI.
- Cada sprint tem seu próprio handoff em `docs/handoffs/sprint-NN/handoff.md`. O handoff explica objetivo, decisões, arquivos, comandos exatos executados, testes e resultados, pendências e próximo passo.
- Documentar procedimentos como checklist operacional: finalidade, pré-verificações, passos, resultado esperado e recuperação de falhas. Escrever para alguém que ainda não conhece o sistema.
- Fluxo GitHub leve: issue para a sprint, branch curta, PR para revisar diff e checks automáticos gratuitos/básicos. Não executar deploy ou publicar releases sem solicitação.

## Convenções financeiras e de privacidade

- Na entrada, interpretar valores com precisão decimal; não usar `float` para cálculos de dinheiro. No armazenamento, preferir inteiros em centavos e moeda BRL explícita.
- Não arredondar valores sem regra definida. Não alterar nem apagar automaticamente movimentos com base em aproximações.
- Preservar a distinção entre data da compra, data do lançamento e data da fatura quando os formatos de origem fornecerem essas datas.
- Importações e banco começam locais. Nenhum dado financeiro é enviado a APIs externas, Databricks, serviços de IA, CI ou ao Git.
- O repositório é pessoal e não tem relação com NSX ou Flutter. Não incorporar configurações, serviços, credenciais ou registries da organização do usuário.
