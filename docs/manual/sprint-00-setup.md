# Manual de operação — ambiente local

## Finalidade

Este procedimento prepara o ambiente de desenvolvimento. Nesta sprint ainda não existe aplicação financeira para iniciar; os testes usam apenas uma fixture inventada.

## Pré-verificações

- Python 3.12 ou superior disponível.
- `uv` instalado e disponível no terminal.
- Terminal aberto na raiz do repositório.
- Arquivos reais permanecem em `data/`; não copie linhas, identificadores, nomes ou valores para testes ou documentação.

## Preparar o ambiente

1. Crie ou atualize o lockfile e instale as dependências do projeto:

   ```bash
   uv lock
   uv sync
   ```

2. Confirme que instalação terminou sem erro. `uv sync` cria `.venv/`, ignorada pelo Git.

   O `pyproject.toml` declara `tool.uv.workspace.members = []` para manter este repositório independente mesmo quando estiver dentro de uma pasta que contenha outro workspace uv. Não remova essa configuração sem verificar o caminho do workspace detectado.

3. Verifique que os arquivos locais sob `data/` estão ignorados:

   ```bash
   git check-ignore -v data/
   git status --short --untracked-files=all
   ```

   Nenhum arquivo financeiro deve aparecer como `A`, `??` ou staged. Se aparecer, pare: não execute `git add`; corrija o `.gitignore` primeiro e peça revisão.

## Executar qualidade local

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
```

Os comandos devem terminar com código de saída zero. A suíte usa somente fixtures sintéticas para validar o domínio e regras básicas de exclusão de dados.

## Resultado esperado

- `pyproject.toml` descreve dependências e configurações de teste/lint.
- O projeto Python está empacotado e instalado em modo editável no `.venv`, para que `uv run python -c 'import streamline_finance'` funcione fora do pytest.
- `uv.lock` registra versões resolvidas para instalação reproduzível. Ele deve existir na raiz deste repositório e não deve incluir membros/dependências de outro repositório.
- A fixture de teste contém apenas categorias e identificadores inventados.
- GitHub Actions executa testes e lint em Python 3.12 e 3.13, sem acessar arquivos locais ignorados.

## Recuperação de falhas

- **`uv` não encontrado:** instale `uv` pelo método oficial para seu sistema e abra um novo terminal; não use scripts de instalação desconhecidos.
- **Resolução ou download falhou:** preserve a mensagem de erro sem incluir tokens/URLs privadas; valide conexão e configuração do índice PyPI público antes de repetir.
- **Teste falhou:** execute `uv run pytest -vv` e corrija primeiro a fixture/configuração indicada. Não use conteúdo real para “consertar” teste.
- **uv cria/usa ambiente fora deste repositório:** confirme que `tool.uv.workspace.members = []` continua no `pyproject.toml` raiz e examine o workspace detectado com `uv lock --verbose`; não execute `uv sync` até confirmar que o `.venv/` será o da raiz do repo.
- **Arquivo em `data/` aparece no Git:** interrompa qualquer `git add`/commit. Adicione a regra apropriada ao `.gitignore`; se já estiver no índice, peça revisão antes de removê-lo do índice.
- **Lint/format falhou:** rode `uv run ruff format .` somente nos arquivos de código/configuração sintéticos e depois repita os checks.

## Limpeza

Para remover somente o ambiente recriável, execute `rm -rf .venv`; depois `uv sync` recria o ambiente. Nunca use comandos de limpeza amplos apontando para `data/`.
