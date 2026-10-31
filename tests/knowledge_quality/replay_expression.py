"""Offline consistency diagnosis of actual saved wires, not live acceptance.

The source quotations are reconstructed from the exact sent packet. This probes
expression validation only; it does not replace full parser/ACL/citation tests.
"""

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.agent.generation_v2 import _parse_generated_answer
from app.agent.answer_blocks import retained_blocks
from app.domain.evidence import Claim


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    assert not args.out.exists()
    report = json.loads(args.report.read_text("utf8"))
    result = {
        "kind": "OFFLINE_ORIGINAL_WIRE_CONSISTENCY_NOT_MODEL_OR_FINAL_PUBLISH_ACCEPTANCE",
        "calls": [],
    }
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for case in report["results"]:
            rid = (case.get("run") or {}).get("id")
            for call_id, raw_input, raw_output in db.execute(
                "SELECT id,input_json,output_json FROM model_calls WHERE run_id=? AND kind='chat' AND output_json IS NOT NULL",
                (rid,),
            ):
                sent = json.loads(raw_input)
                if "answer_blocks" not in sent.get("format", {}).get("properties", {}):
                    continue
                row = {"case": case["case"]["id"], "call_id": call_id}
                result["calls"].append(row)
                try:
                    user = sent["messages"][1]["content"]
                    envelope = re.search(
                        r"\[BEGIN_UNTRUSTED_EVIDENCE nonce=[^\]]+\]\n(.*?)\n\[END_UNTRUSTED_EVIDENCE",
                        user,
                        re.S,
                    )
                    records = json.loads(envelope[1])
                    units = {}
                    contexts = {}
                    for record in records:
                        text = "\n".join(
                            record.get(field, "")
                            for field in ("matched_text", "context_text", "open_content")
                        )
                        for match in re.finditer(
                            r"\[(S[1-9]\d*U[1-9]\d*)\](.*?)\[/\1\]", text, re.S
                        ):
                            units[match[1]] = match[2].strip()
                            contexts[match[1]] = text
                    generated = _parse_generated_answer(
                        json.loads(raw_output)["message"]["content"]
                    )
                    claims = [
                        Claim(
                            claim_id=c.claim_id,
                            text=units[c.source_unit_id],
                            critical=True,
                            cited_chunk_ids=[c.source_unit_id.split("U")[0]],
                            need_refs=c.need_refs,
                        )
                        for c in generated.claims
                    ]
                    provenance = {c.claim_id: contexts[c.source_unit_id] for c in generated.claims}
                    kept, errors = retained_blocks(
                        generated._answer_blocks, claims, case["actual_user_question"], provenance
                    )
                    row.update(retained=[b.model_dump() for b in kept], rejected=errors)
                except Exception as error:
                    row["error"] = type(error).__name__ + ": " + str(error)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(
        json.dumps(
            [
                {
                    "case": r["case"],
                    "kept": len(r.get("retained", [])),
                    "errors": r.get("error"),
                    "reasons": [x["reason"] for x in r.get("rejected", [])],
                }
                for r in result["calls"]
            ],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
