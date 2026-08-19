# Known Limitations and Interview Boundaries

## MCP deployment boundary

The project uses the official MCP SDK as an in-process adapter. It has no
network-isolated MCP server, OAuth flow, service-to-service identity, or remote
tool deployment. Say “MCP protocol integration/adapter,” not “production MCP.”

## HITL durability

Pending reviews and the `InMemorySaver` checkpoint exist only in the running
process. Same-process retries and concurrency are controlled; process restart
loses pending review state. Persistent or distributed HITL remains production
work.

## Trajectory storage

SQLite plus a SHA-256 event chain is tamper-evident local trajectory storage.
The module does not provide encryption-at-rest, key rotation, tenant retention,
external signatures/timestamps, WORM media, or a production audit ledger.

## Distributed deployment

There is no cluster scheduler, Redis state, distributed checkpoint, multi-
writer ordering, or cross-region execution. The verified container contract is
single-service portfolio evidence.

## External Agent benchmarks

The runtime A/B has five deterministic mechanism cases. It validates adapter
parity and permission behavior but cannot establish general Agent quality,
safety, or external benchmark performance.

## Operational SLO

No production traffic, capacity test, availability history, QPS claim, or SLA
exists. Local/CI latency and one-host index measurements must retain their
machine/protocol boundaries.

## Retrieval/evaluation semantics

WixQA and EnterpriseRAG metrics are retrieval metrics on fixed consumed public
labels, not answer accuracy. The clean replay is local exact regression, not an
independent third-party reproduction. Equal RRF and a multi-document candidate
were rejected; they must not be presented as improvements.

