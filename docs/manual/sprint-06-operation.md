# Manual — operação e recuperação local

## Finalidade e pré-verificações

- Execute os comandos no PowerShell, na raiz do repositório. Python 3.12 ou superior e `uv` devem estar disponíveis; se `uv` não estiver no PATH, use `python -m uv` quando instalado nesse Python.
- Os dados operacionais ficam em `data/db/finance.sqlite3` e `data/raw/`. A pasta `data/` é ignorada pelo Git. Não copie dados financeiros para testes, documentação, logs compartilhados ou serviços externos.
- O banco pode conter suas importações. Nunca use `data/` como destino de testes sintéticos, nem sobrescreva o banco ativo para testar uma restauração.

## Instalar, iniciar e parar

1. Na raiz, instale as versões do lockfile: `python -m uv sync --locked`.
2. Em um terminal, inicie a API: `python -m uv run --locked uvicorn streamline_finance.api:app --host 127.0.0.1 --port 8000`.
3. Em outro, inicie a interface: `python -m uv run --locked streamlit run app.py --server.address 127.0.0.1`.
4. Abra o endereço local informado pelo Streamlit. Comece em **Demo** para praticar com `tests/fixtures/nubank_statement_synthetic.csv`; Demo é temporário. **Meus dados locais** usa o banco persistente e só importa após confirmação.
5. Para parar, use `Ctrl+C` em ambos os terminais. Se os processos foram iniciados em segundo plano, identifique as janelas ou os processos que você iniciou e encerre-os. Antes de copiar, confirme que nenhum processo da aplicação ou outro programa está usando o banco.

Não altere o endereço de escuta para rede pública: a aplicação local não tem autenticação.

## Roteiro de aceite local

1. Em **Demo**, confira a navegação, escolha um intervalo e teste filtros, gráficos e tooltips em BRL.
2. Em **Importar extrato**, envie `tests/fixtures/nubank_statement_synthetic.csv`, gere a prévia e confirme a inclusão no sandbox. Em **Revisar movimentações**, selecione natureza e categoria e confirme a alteração fictícia. Verifique a análise para o mesmo intervalo e pessoa.
3. Alterne para dados locais e de volta para Demo; confirme que o sandbox voltou ao estado inicial. As alterações Demo não devem aparecer nos dados locais.
4. Pratique o backup e a restauração isolada conforme as seções seguintes. Não use uma restauração de ensaio para substituir o banco em uso.
5. Avalie o resultado e informe se aceita a Sprint 6 ou quais problemas devem ser corrigidos. Qualquer conferência com dados pessoais é local, escolhida por você, e não faz parte dos testes automatizados.

## Fazer backup privado

1. Pare a API e a interface e confirme que nenhum outro programa usa `data/db/finance.sqlite3` ou está importando arquivos.
2. Escolha um destino privado com espaço suficiente; prefira disco criptografado. O exemplo cria um conjunto novo dentro de `data/backups/`, ignorada pelo Git. Um backup no mesmo disco **não protege contra perda desse disco**: faça também uma cópia privada em outro dispositivo, se desejar essa proteção.
3. No PowerShell, na raiz, execute:

   ```powershell
   $ErrorActionPreference = 'Stop'
   if (-not (Test-Path -LiteralPath 'data/db/finance.sqlite3' -PathType Leaf)) { throw 'Banco não encontrado; nada foi copiado.' }
   if (-not (Test-Path -LiteralPath 'data/raw' -PathType Container)) { throw 'Pasta raw não encontrada; nada foi copiado.' }
   $backup = Join-Path (Join-Path (Get-Location) 'data/backups') ([guid]::NewGuid().ToString())
   New-Item -ItemType Directory -Path $backup | Out-Null
   Copy-Item -LiteralPath 'data/db' -Destination (Join-Path $backup 'db') -Recurse
   Copy-Item -LiteralPath 'data/raw' -Destination (Join-Path $backup 'raw') -Recurse
   Write-Host "Backup criado em: $backup"
   ```

4. Confirme que o comando terminou sem erro e que o destino contém `db/finance.sqlite3` e `raw/`. Se falhar, considere esse conjunto incompleto: preserve a origem e repita em um novo destino. Guarde o caminho do backup em local privado.

## Ensaio de restauração isolada

Este procedimento **não substitui** o banco operacional. Execute após o backup, com a aplicação parada, usando a variável `$backup` da etapa anterior ou atribuindo a ela o caminho do conjunto escolhido.

1. No mesmo PowerShell, copie o conjunto para uma pasta temporária nova:

   ```powershell
   $ErrorActionPreference = 'Stop'
   if (-not (Test-Path -LiteralPath (Join-Path $backup 'db/finance.sqlite3') -PathType Leaf)) { throw 'Banco do backup ausente.' }
   if (-not (Test-Path -LiteralPath (Join-Path $backup 'raw') -PathType Container)) { throw 'Pasta raw do backup ausente.' }
   $ensaio = Join-Path $env:TEMP ("streamline-restore-" + [guid]::NewGuid().ToString())
   New-Item -ItemType Directory -Path $ensaio | Out-Null
   Copy-Item -LiteralPath (Join-Path $backup 'db') -Destination (Join-Path $ensaio 'db') -Recurse
   Copy-Item -LiteralPath (Join-Path $backup 'raw') -Destination (Join-Path $ensaio 'raw') -Recurse
   $bancoEnsaio = Join-Path $ensaio 'db/finance.sqlite3'
   .\.venv\Scripts\python.exe -c "import pathlib,sqlite3,sys; p=pathlib.Path(sys.argv[1]).resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); r=c.execute('PRAGMA integrity_check').fetchone(); f=c.execute('PRAGMA foreign_key_check').fetchone(); c.close(); print('Integridade OK' if r == ('ok',) and f is None else 'Falha de integridade'); sys.exit(0 if r == ('ok',) and f is None else 1)" $bancoEnsaio
   if ($LASTEXITCODE -ne 0) { throw 'Verificação falhou; não use este backup para restaurar.' }
   Write-Host "Ensaio isolado em: $ensaio"
   ```

2. Resultado esperado: `Integridade OK`, sem erros de cópia. Confira também se os CSVs esperados estão presentes em `$ensaio/raw`; a verificação SQLite não confirma a integridade ou completude dos CSVs. Se precisar confrontar hashes, faça isso localmente sem compartilhar nomes ou resultados.
3. Mantenha o ensaio privado. Apague **somente a pasta indicada por `$ensaio`** após terminar, se não precisar dela; ela pode conter dados reais.

## Recuperar a operação após uma falha

1. Pare API e interface. Execute o ensaio acima e valide o backup escolhido. Se a integridade falhar ou faltarem CSVs, não substitua o conjunto atual; tente outro backup.
2. Preserve integralmente os diretórios atuais `data/db/` e `data/raw/` em outro local privado, mesmo que pareçam danificados. Não os exclua nem misture com os arquivos do backup.
3. Com a aplicação ainda parada, renomeie `data/db/` e `data/raw/` atuais para nomes diferentes e inexistentes no mesmo diretório. Copie os diretórios `db/` e `raw/` do backup validado para `data/`, mantendo exatamente esses nomes. Se qualquer etapa falhar, mantenha a aplicação parada; preserve todas as cópias e reverta os nomes originais antes de tentar novamente.
4. Confira a presença de `data/db/finance.sqlite3` e de `data/raw/`, repita o teste de integridade apontando `$bancoEnsaio` para o banco restaurado, e só então reinicie API e interface. Confira seus dados localmente. O backup representa o instante em que foi criado; movimentos posteriores a ele não serão recuperados por essa cópia.

## Erros e verificação

- **`uv` ausente:** instale pelo método oficial ou disponibilize-o no PATH; use `python -m uv` se instalado no Python atual.
- **API indisponível:** verifique se a API está ativa em `127.0.0.1:8000` e se a porta não está ocupada por outro processo. Reiniciar a interface não inicia a API.
- **Prévia inválida:** não confirme; corrija o arquivo na origem e gere nova prévia. Não publique os dados ao pedir ajuda.
- **Backup falhou ou integridade não é `OK`:** não apague a origem nem restaure por cima dela; preserve o conjunto e tente outro backup.
- **Checagens de desenvolvimento:** `python -m uv run --locked pytest`, `python -m uv run --locked ruff format --check .` e `python -m uv run --locked ruff check .`. Testes usam apenas dados sintéticos.
