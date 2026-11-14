# Manual de operação — API local

## Finalidade

FastAPI expõe operações locais para revisar importações, persistir uma prévia confirmada, consultar transações e registrar decisões humanas. A API usa SQLite já existente do domínio e não faz categorização automática de movimentos desconhecidos.

## Pré-verificações

- Execute `uv sync` na raiz após alterações de dependências.
- Use somente na máquina local. O servidor deve escutar em `127.0.0.1`, nunca em `0.0.0.0` ou interface pública.
- A API não tem autenticação de usuário ainda. Portanto, não a exponha a outros dispositivos/rede, não configure proxy/túnel e pare o servidor quando não estiver testando.
- Arquivos reais em `data/` não devem ser usados durante os testes. A API não copia conteúdo de arquivo para mensagens de erro ou respostas de listagem.
- A prévia lê o upload em memória; tamanho máximo nesta sprint é 10 MiB.

## Iniciar e parar

Na raiz do projeto:

```bash
uv run uvicorn streamline_finance.api:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000/` para a mensagem de boas-vindas ou `http://127.0.0.1:8000/docs` para a documentação interativa da API. Pressione `Ctrl+C` no terminal para parar.

Se o log mostrar `404` em `GET /json/version`, isso é esperado: navegadores e extensões às vezes consultam esse endereço para descobrir se há um serviço de depuração compatível. Esta API não oferece esse protocolo. A sondagem não interfere com `/health`, `/docs` ou as rotas financeiras.

## Fluxo seguro de importação

1. `POST /imports/preview` com arquivo, `source_key`, `person` e `source_kind`. Essa rota não grava transações nem mantém o arquivo depois da resposta.
2. Revise `can_confirm`, quantidade, linhas apresentadas (incluindo campos originais para revisão) e erros. Erros nunca repetem valores de linhas.
3. Somente depois de revisão, `POST /imports/confirm` com os mesmos dados e `confirmed=true`.
4. A resposta retorna batch e contagens, sem devolver linhas ou conteúdo CSV.
5. Se uma linha for inválida, a confirmação retorna 422 e não grava o lote.
6. Repetir o mesmo arquivo/origem retorna resultado idempotente. Se escolhas de pessoa/origem divergirem, servidor retorna conflito 409.

`source_kind` deve ser escolhido explicitamente entre `bank_account` e `credit_card`. Não inferir natureza da transação só pelo sinal do valor. Cada movimento permanece `pending` até revisão.

## Rotas principais

- `GET /health`: estado simples de disponibilidade local.
- `POST /imports/preview`: prévia sem persistência; retorna transações e campos originais para a pessoa conferir.
- `POST /imports/confirm`: confirmação persistente explícita.
- `GET /imports`: metadados de importação, sem conteúdo original.
- `GET /transactions`: lista normalizada; aceita filtros de pessoa, origem e natureza.
- `GET /transactions/{source_key}/{transaction_id}`: consulta pontual.
- `POST /transactions/{source_key}/{transaction_id}/movement-type`: altera movimento pendente apenas com `confirmed=true`; cria histórico.
- `POST /transactions/{source_key}/{transaction_id}/category-suggestion`: avalia regras explícitas enviadas pelo cliente, sem salvar regras.
- `POST /transactions/{source_key}/{transaction_id}/category`: registra categoria humana confirmada numa despesa.
- `POST /payment-candidates/refresh`, `GET /payment-candidates`, `POST /payment-candidates/{id}/decision`: gerar e revisar candidatos sem mesclar ou apagar movimentos.

## Regras importantes

- Natureza possível: `expense`, `income`, `transfer`, `pending`.
- Pessoa possível: `self`, `spouse`, `shared`.
- Valores monetários na API persistidos são centavos inteiros (`amount_minor_units`) e moeda `BRL`.
- Erros não incluem valores de células, descrições ou identificadores CSV.
- Classificação não-despesa é ignorada pelo serviço de regras. Só despesas aceitam categoria.
- Endpoints de alteração exigem confirmação booleana explícita.
- Candidate de pagamento exige igualdade exata do valor, pessoa igual, data dentro da janela e fonte marcada com tipo correto. Mesmo assim é apenas sugestão para conferência.

## Erros comuns

- **422:** campo requerido ausente, tipo inválido, cabeçalho/linha CSV inválidos. Corrija o formato sem enviar dados à documentação ou logs.
- **409:** confirmação não marcada ou conflito de reimportação. Reabra a prévia; não tente contornar o conflito apagando banco.
- **404:** ID/origem não encontrada. Consulte `GET /transactions` e confira a source key.
- **413:** arquivo acima de 10 MiB. Não aumente o limite sem compreender impacto de memória e testar.
- **Connection refused:** servidor não está ativo, URL/porta não conferem, ou terminou após Ctrl+C.
- **Banco bloqueado:** aguarde outra operação local terminar; não copie/apague sidecars durante escrita.

## Testar sem dados reais

```bash
uv run pytest tests/test_api.py
uv run pytest
uv run ruff format --check .
uv run ruff check .
```

Use o cliente de testes e fixtures inventadas. Não passe arquivos existentes em `data/` para comandos de teste/CI.

## Estado do desenho

As rotas chamam adaptador, domínio e repositório; não mantêm regras financeiras dentro dos handlers. API é uma aplicação local de desenvolvimento, sem autenticação, sem deploy e sem acesso externo nesta sprint.
