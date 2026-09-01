# Branch Compatibility Policy

Updated: 2026-09-01

## Public entry

- Canonical repository URL:
  <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot>
- Canonical development and display branch: `main`
- Stable portfolio snapshot: `portfolio-v1.0.0`
- Historical implementation evidence remains addressable by immutable commit
  SHA and its original CI run.

GitHub opens the repository on `main`. New resumes, application attachments,
and review prompts must not link to a moving `codex/*` development branch.

## Why legacy refs remain

Every remote `codex/*` branch listed below is fully contained in `main` and has
zero commits ahead of `main`. The refs are retained as URL-compatibility aliases,
not as active development lines.

| Ref | Compatibility reason |
|---|---|
| `codex/agent-runtime-vnext` | Referenced by earlier resume packages and teaching records |
| `codex/durable-agent-runtime-and-policy-v1` | Referenced by the public durable-runtime review packet and GPT review prompt |
| `codex/durable-runtime-integrity-fix-v1` | Referenced by frozen integrity-review evidence |
| `codex/final-resume-readiness-closeout-v1` | Embedded in submitted and current frozen resume PDFs; must not be deleted or renamed |
| `codex/rag-quality-hierarchical-retrieval-v1` | Preserves the original R4 review coordinate while `main` carries the same commit |

Deleting or renaming one of these refs can turn an already distributed
`/tree/codex/...` or `/blob/codex/...` URL into a 404 even though its commits are
still reachable from `main`. Keeping the lightweight refs costs no duplicate
repository storage and protects those external links.

## Link rules

Use one of these forms for all new material:

1. Repository overview:
   <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot>
2. Stable portfolio snapshot:
   <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/portfolio-v1.0.0>
3. Reproducible evidence: an exact `/commit/<sha>` URL plus the matching Actions
   run and artifact hash.

Do not delete a legacy ref until the application ledger proves that no submitted
resume, application attachment, teaching record, or shared review prompt depends
on it. Existing submitted files are never rewritten retroactively.

## Historical documents

Some evidence files deliberately say `NOT_MERGED`, `NOT_RELEASED`, or name their
original feature branch. Those statements describe the state at the time the
evidence was frozen. They remain unchanged for auditability; the current public
state is recorded at the top of `PROJECT_STATUS.md` and on the repository
homepage.
