# R3 Interview Demo Runbook

## Offline evidence tour

From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.r3_evidence_tour
```

This command reads only checked-in redacted evidence. It does not start Ollama,
load private datasets, expose questions/answers or rerun a consumed split. Use
`--format json` when machine-readable output is useful.

The recommended interview sequence is:

1. Explain the company-disjoint R3 cohort and one-shot validation/test markers.
2. Show why page deduplication was rejected on validation despite a small gain.
3. Show why typed numeric planning was rejected before validation: only 7/192
   cases had a gold-matching value among the first 32 candidates.
4. Show the 48-case external-content security stress result and immediately state
   that it is one probe and not a new blind holdout.
5. State that independent double-human answer review remains `NOT_RUN` because it
   cannot be truthfully automated by the project author.

## Live product demo

For the full authenticated FastAPI + Streamlit workflow, continue to use
[the existing demo runbook](../demo_runbook.md). That demo shows identity, ACL,
Agent trace, citations and the public evaluation snapshot. The R3 offline tour
shows scientific decision-making and negative-result gates; the two demos answer
different interview questions.
