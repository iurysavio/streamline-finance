# streamline-finance

## Planos do projeto

Leia os planos incrementais em [`docs/plans/`](docs/plans/README.md). Nenhuma sprint começa sem o aceite explícito do usuário: primeiro os planos v0–v3, depois cada sprint concluída antes da próxima.

O roteiro e o estado de continuidade da Sprint 0 ficam em [`docs/handoffs/sprint-00/handoff.md`](docs/handoffs/sprint-00/handoff.md).

Para preparar o ambiente local, siga o [manual de setup](docs/manual/sprint-00-setup.md) e execute `uv sync` na raiz. Isso instala o pacote `src/` no ambiente virtual para que imports do projeto funcionem em comandos `uv run`. A aplicação Streamlit ainda não foi iniciada; os comandos atuais validam a fundação, domínio, prévia sintética, formatação e lint.

O domínio financeiro e as regras de categoria em andamento estão descritos no [manual da Sprint 1](docs/manual/sprint-01-domain.md), com continuidade em [`docs/handoffs/sprint-01/handoff.md`](docs/handoffs/sprint-01/handoff.md).

A prévia em memória do extrato Nubank está explicada no [manual da Sprint 2](docs/manual/sprint-02-import-preview.md), com continuidade em [`docs/handoffs/sprint-02/handoff.md`](docs/handoffs/sprint-02/handoff.md).

Para persistência local, importações idempotentes e revisão de possíveis pagamentos de fatura, consulte o [manual da Sprint 3](docs/manual/sprint-03-storage.md) e [`docs/handoffs/sprint-03/handoff.md`](docs/handoffs/sprint-03/handoff.md).

A API local está descrita no [manual da Sprint 4](docs/manual/sprint-04-api.md), com continuidade em [`docs/handoffs/sprint-04/handoff.md`](docs/handoffs/sprint-04/handoff.md).

A interface Streamlit e o painel de despesas são documentados no [manual da Sprint 5](docs/manual/sprint-05-streamlit.md), com continuidade em [`docs/handoffs/sprint-05/handoff.md`](docs/handoffs/sprint-05/handoff.md).

## Configuração do OpenCode

Este repositório inclui configuração e exemplos do OpenCode em `.opencode/`:

```text
.opencode/
├── opencode.json
├── agents/
│   └── finance-reviewer.md
├── commands/
│   └── review-finance.md
└── skills/
    └── financial-data/
        └── SKILL.md
```

- **Agente:** `finance-reviewer` revisa mudanças financeiras sem editar arquivos.
- **Skill:** `financial-data` orienta cuidados com valores, arredondamento, moeda e datas.
- **Comando:** execute `/review-finance` para revisar mudanças; você pode acrescentar um foco específico ao comando.

O OpenCode encontra agentes, comandos e skills nessas pastas automaticamente. Mantenha segredos fora dos arquivos versionados. Depois de alterar arquivos de configuração, reinicie o OpenCode para carregar as mudanças.
