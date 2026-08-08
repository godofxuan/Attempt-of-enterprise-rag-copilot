# R3 Final Report

## Scope and outcome

R3 pursued external credibility rather than feature count. It froze an unused
company-disjoint UDA cohort, evaluated one bounded page-retrieval intervention,
evaluated a typed numeric answer intervention, expanded current-Guard external
security stress coverage and added a one-command offline evidence tour.

No framework, vector database, message queue, extra Agent or extra model was
added. The production Dense retrieval and direct answer paths were not replaced
because neither candidate passed its frozen quality gate.

## What genuinely improved

The strongest implementation improvements are experimental and operational:

- 48 new reports and 17,891 chunks are indexed under an unused-company R3
  protocol with 28 companies still reserved.
- Validation/test access is one-shot and fail-closed; rejected candidates do not
  consume the fixed test.
- Answer campaigns now bind model digest, output-token budget, prompt-cache
  reset policy, generation/calculator calls, citations and immutable details.
- A reproducible candidate-oracle analysis explains typed quality ceilings
  without an LLM judge.
- Current-Guard stress coverage expanded to 48 external garak-derived attacks.
  In the paired run, ASR was 12/48 Guard OFF and 0/48 Guard ON; attack context
  reached the model in 48/48 OFF and 0/48 ON cases. Four benign controls retained
  4/4 utility with 0/4 quarantines.
- Long Ollama campaigns now cap output and periodically reset prompt cache after
  an observed 8.1/8.2 GiB prompt-cache saturation incident.

The 48-attack result proves current implementation behavior on a larger stress
population. It does not supersede the smaller but more independent 12-attack
holdout result.

## What did not improve

Page-level deduplication improved UDA validation Hit@5 only from 81.25% to
82.29% and nDCG@5 from 67.58% to 68.46%. These `+1.04` and `+0.88` point gains
failed the frozen `+5` and `+3` point gates. The fixed test was untouched.

The typed numeric candidate route reduced development numeric accuracy from
7.81% to 1.56%, grounded accuracy from 7.29% to 1.04% and increased unsupported
answers from 31.25% to 58.85%. It was faster and schema-compliant, but quality
was materially worse. It never reached validation or test.

## Current bottleneck

Known-report Dense retrieval found the gold page in 152/192 development cases,
yet the direct arm answered only 15/192 correctly. The typed candidate oracle
found a gold-matching value in only 7/192 cases and hit its 32-value limit in
190/192 cases. The dominant bottleneck is financial table semantics: row/column
association, units, temporal labels, multi-page evidence and operation/operand
selection. More planner prompts cannot recover values that the candidate
contract does not represent.

## Resume numbers

The three safest existing numbers remain:

1. Frozen 12-attack combination-disjoint garak subset: ASR `4/12 -> 0/12`,
   model exposure `12/12 -> 0/12`, mean Guard scan `1.42 ms`.
2. Fixed 100-case public FinQA sample: `44%` strict execution accuracy, `93.5%`
   evidence recall, `79.4%` citation precision and `78.3%` citation recall.
3. Company-disjoint 96-question UDA fixed set within the known report: `74.0%`
   Page Hit@5, `61.3%` nDCG@5 and `222.9 ms` p95.

The R3 48-attack stress result may be discussed as additional current-Guard
coverage only when labeled `one probe`, `recombined stress fixture` and `not a
new blind holdout`.

## Forbidden claims

Do not claim that page max improved the system, typed planning improved answer
quality, the 48-attack set is independent, benign FPR is generally 0%, full
garak is solved, UDA answer accuracy is high, the known-report result is open
document discovery, or the project is production-certified/SOTA.

## Stop decision

Stop adding features. The next legitimate quality experiment requires either:

- the outstanding two-independent-reviewer human campaign; or
- a table/layout-aware evidence representation designed on development and
  evaluated once on currently reserved companies.

Do not spend the 28 reserve companies on another prompt-only planner. Do not
touch the R3 fixed test unless a candidate first passes development and
validation gates. Independent human review is the only planned R3 activity left
`NOT_RUN`; it cannot be completed honestly by this agent.
