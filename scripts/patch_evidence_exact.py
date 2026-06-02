"""Optional helper: replace known shortened evidence strings with exact source-document sentences.
Run from the project root after copying the dataset into data/raw_docs and data/eval.
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"

REPLACEMENTS = {
    "如商品存在质量问题，客户可在签收后 30 个自然日内提交质量问题退款申请。": "如商品存在质量问题，客户可在签收后 30 个自然日内提交质量问题退款申请，并提供照片、视频或检测说明。",
    "员工发现数据误发、账号异常、设备丢失或疑似泄露时，应在 2 小时内报告信息安全团队。": "员工发现数据误发、账号异常、设备丢失或疑似泄露时，应在 2 小时内报告信息安全团队，并配合进行风险评估和补救。",
    "各系统负责人须每季度进行一次权限复核。": "各系统负责人须每季度进行一次权限复核，确认离职、转岗或不再需要权限的账号已及时关闭。",
    "外部访客须至少提前 1 个工作日提交访客预约。": "外部访客须至少提前 1 个工作日提交访客预约，填写来访人姓名、公司、手机号、来访时间和接待人。",
    "员工发现公司设备丢失，应在 2 小时内通知直属主管、IT 和信息安全团队。": "员工发现公司设备丢失，应在 2 小时内通知直属主管、IT 和信息安全团队，并说明丢失时间、地点和设备编号。",
    "员工离职时，IT 应在离职日 18:00 前关闭个人账号。": "员工离职时，IT 应在离职日 18:00 前关闭个人账号，特殊保留需求须由部门负责人审批。",
}


def patch_file(path: Path) -> int:
    rows = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for row in rows:
        for source in row.get("gold_sources", []):
            ev = source.get("evidence")
            if ev in REPLACEMENTS:
                source["evidence"] = REPLACEMENTS[ev]
                count += 1
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return count


def main() -> None:
    total = 0
    for path in EVAL_DIR.glob("*.json"):
        if path.name == "metadata.json":
            continue
        total += patch_file(path)
    print(f"Patched evidence fields: {total}")


if __name__ == "__main__":
    main()
