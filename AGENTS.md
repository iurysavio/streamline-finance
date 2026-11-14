# Repository instructions

- The Streamlit interface is not implemented yet; FastAPI and finance domain are under `src/streamline_finance/`. Python setup and quality commands are defined in `pyproject.toml` and `docs/manual/`; plans are in `docs/plans/`. Read the current sprint handoff under `docs/handoffs/` before continuing.
- For financial calculations or data, load `.opencode/skills/financial-data/SKILL.md`; preserve exact amounts, explicit rounding and currency, and deliberate date/time-zone behavior.
- Real transaction data lives locally under `data/` and is ignored by the root `.gitignore`. Never copy transaction rows, identifiers, names, or amounts into tracked docs, fixtures, logs, issues, or CI; use synthetic examples only.
- The project is personal and unrelated to NSX or Flutter; do not add organization-specific configuration, services, credentials, or package registries.
- Use `/review-finance` for a read-only review of working-tree changes; it routes to the `finance-reviewer` agent.
- Keep OpenCode agents, commands, and skills in `.opencode/agents/`, `.opencode/commands/`, and `.opencode/skills/<name>/SKILL.md` respectively. Restart OpenCode after changing config-time files.
