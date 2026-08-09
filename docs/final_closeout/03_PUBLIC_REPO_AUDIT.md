# Public Repository Final Audit

Date: 2026-08-10

## Automated audit

Command:

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_public_repo --root .
```

Final result: `1536 candidates / 0 findings`.

The audit checks forbidden/private paths, credentials and private keys,
non-example email addresses, author-specific absolute paths, missing local
Markdown links, oversized public files, and required security-corpus contracts.

## Finding and repair

The first closeout audit reported one `absolute_user_path` in the new WixQA
clean-reproduction JSON. The verifier had copied private candidate metadata,
including repository and BLAS install paths, into public evidence. The repair
projects only allowlisted machine/version fields and replaces four concrete
roots with `FRESH_REPOSITORY_LOCAL_IGNORED` classes. Full private metadata stays
in the ignored candidate artifact. The regenerated evidence preserved
`VERIFIED`, zero tolerance, and zero quality differences.

## Secret and identity boundary

No `.env`, JWT, private signing key, credential token, real-company email, or
private raw run directory is public. Local demo identity material stays under
ignored `.private/identity`. The public JWKS/identity documentation contains
only contracts and synthetic/example values.

## Large-file boundary

The largest tracked file observed was 1,914,251 bytes. The 1.37 GiB Enterprise
FTS index, WixQA source/index/cache/detailed runs, Enterprise Parquet corpus,
Ollama models, and resume-private build outputs are not tracked. Public evidence
uses bounded aggregate JSON and redacted rows.

## Local path and link boundary

Public commands are repository-relative. The final audit found no author path
or missing local Markdown link. The actual resume sync is intentionally outside
the repository in the user's existing private resume workspace and is not
referenced by an absolute path from public project files.

## Result

`PASS`. This proves the repository passed the configured static disclosure and
link rules. It is not a legal privacy review, secret-scanner certification, or
production security assessment.
