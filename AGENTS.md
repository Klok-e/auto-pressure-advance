## YAGNI
Follow YAGNI principles.

Before implementing a solution, inspect the relevant existing code.

Prefer, in order:
1. Reusing existing functionality.
2. Standard library or native platform features.
3. Already installed dependencies.
4. The simplest custom implementation that satisfies the requirements.

Avoid speculative features, unnecessary abstractions,
new dependencies, and boilerplate.

Prefer concise, readable code over verbose implementations.
Use one-liners when they genuinely simplify the solution.

Never sacrifice correctness, security, input validation,
error handling, or maintainability to reduce code size.

Implement only what is required for the current task.

## Agent skills

### Issue tracker

Issues and specs live as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage roles as status strings. See `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout with root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.
