# Handoff — Sprint 4: API FastAPI

## Status

**Concluída, aguardando aceite do usuário.** A Sprint 5 só pode começar após aceite explícito da Sprint 4.

## Objetivo

Oferecer API local para prévia, confirmação explícita de importação, consultas, revisão da natureza/categoria e decisões de candidatos. A API é camada fina: domínio/importador/repositório continuam proprietários das regras.

## Contrato/decisões

- FastAPI + Pydantic; app factory `create_app()` permite injetar repositório para testes. Import do módulo não cria DB; lifecycle de servidor abre DB local.
- Executar em `127.0.0.1:8000`, sem autenticação nesta versão; não expor na rede.
- Upload máximo 10 MiB.
- Prévia não persiste arquivo, import batch nem transações; a resposta inclui linhas/campos do arquivo para inspeção pela pessoa. Não exibir resposta integral de arquivo real em logs.
- Confirmação exige `confirmed=true`, prévia válida e os mesmos dados/contexto; rotas retornam resultado sem repetir linhas CSV.
- Erros de importação não ecoam célula, descrição, valor ou identificador do CSV.
- Listagem de transações retorna modelo normalizado sem `source_fields` brutos; apenas rota de prévia devolve campos originais antes da confirmação.
- Mudança de natureza/categoria e decisão de match exige confirmação explícita.
- Injeção de repositório para testes passa explicitamente por `app.state.repository`; SQLite usa `check_same_thread=False` junto a lock reentrante para serializar uso da conexão única. A API segue um worker local.

## Trabalho TDD

- `tests/test_api.py` criado antes de API. Primeiro teste falhou por FastAPI ausente; dependências foram adicionadas ao manifesto e lock.
- Testes inicialmente falharam por app state não inicializado em testes e por conexão SQLite criada em thread diferente. App factory disponibiliza o repositório injetado; conexão SQLite usa compatibilidade de thread e lock reentrante.
- Outros testes provaram prévia sem write, validação e resposta segura, confirmação/idempotência, listagem sem dados brutos, revisão de natureza/categoria e 404/422/409.
- Testes cobrem limite de upload, lifespan/health e recusa de cliente não-loopback.

## Mudanças

- `src/streamline_finance/api.py`: app factory, schemas, handlers e rotas locais.
- `src/streamline_finance/storage.py`: repositório serializa conexão para servidor e adiciona confirmação de categoria.
- `pyproject.toml`/`uv.lock`: FastAPI, multipart, uvicorn e test client.
- `tests/test_api.py`.
- `.gitignore` ignora `*.egg-info/`, artefatos gerados durante instalação editável.
- `docs/manual/sprint-04-api.md` e link no README.

## Verificações

- `uv run pytest`: passou; 63 testes (13 API, 17 persistência, 17 importador, 13 domínio, 3 fundação).
- Depois da validação inicial, usuário reportou `GET /` e `/json/version` retornando 404. `/` agora exibe uma mensagem com o link de `/docs`; `/json/version` permanece 404 intencional, explicado no manual, pois protocolo de depuração do navegador não faz parte da API. Teste cobre ambos.
- `uv run ruff format --check .`: passou; 33 arquivos verificados.
- `uv run ruff check .`: passou.
- `uv lock --check --offline` e `uv sync --locked --offline`: passaram.
- Smoke test do servidor em `127.0.0.1` com `GET /health`: 200 e serviço encerrado em seguida.
- `git check-ignore -v` confirmou dados reais, banco/raw, `.venv` e `.egg-info/` ignorados.
- `git diff --check`: passou.
- O lote e CSV sintéticos temporários criados na pasta real `data/` durante o exemplo da Sprint 3 foram removidos antes de iniciar esta sprint. Banco confirmou 0 lotes e 0 transações; fontes financeiras reais não foram lidas/alteradas.

## Resíduo de teste Sprint 3

Identificado exclusivamente um lote local `source_key=synthetic-demo`, correspondente ao hash conhecido da fixture sintética e dois movimentos sintéticos. Removidos apenas os vínculos, duas linhas associadas àquele lote e seu CSV raw sintético. Depois da limpeza, importações e transações locais estavam vazias. Arquivos de usuário em `data/input/` e `data/historical/` não foram lidos nem alterados.

## Próximo passo

Apresentar API, comandos locais, limites e testes ao usuário. Aguardar aceite explícito antes da Sprint 5.
