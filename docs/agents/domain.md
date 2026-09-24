# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- `CONTEXT.md` at the repo root.
- Relevant ADRs in `docs/adr/`.

If these files don't exist, proceed silently. The `/domain-modeling` skill creates them when terms or decisions get resolved.

## File structure

The single-context layout is:

/
/CONTEXT.md
/docs/adr/<NNNN>-<decision>.md

## Use the glossary's vocabulary

When an issue title, proposal, hypothesis, or test names a domain concept, use the term defined in `CONTEXT.md`. If the concept is absent, reconsider the term or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If an output contradicts an existing ADR, identify the ADR and explain why its decision should be reopened.
