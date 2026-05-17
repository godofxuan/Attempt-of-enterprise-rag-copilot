from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DOCS_DIR = BASE_DIR / "data" / "raw_docs"


DOCS = {
    "hr_policy.md": """# 人事制度

## 请假规则
员工请假需要至少提前 1 个工作日提交申请。
病假超过 2 天需要提供医院证明。

## 出差报销
出差报销需要在出差结束后 7 天内提交。
报销单据必须包含发票和行程说明。

## 入职资料
新员工需要提交身份证复印件、银行卡信息和学历证明。
""",
    "refund_policy.md": """# 退款政策

## 退款期限
客户可在下单后 14 天内申请退款。

## 不可退款情况
已开封的定制商品不支持退款。
超过 14 天且无质量问题的订单不支持退款。

## 审核流程
客服初审后，财务将在 3 个工作日内处理。
""",
    "it_support.md": """# IT 支持手册

## VPN 连接失败
请先检查账号密码是否正确。
如果报错 691，请联系 IT 管理员重置凭证。

## 邮箱无法登录
请确认是否开启双重认证。
如果忘记密码，请走企业邮箱找回流程。

## 设备申请
新设备申请需要部门经理审批。
""",
    "shipping_faq.md": """# 物流 FAQ

## 发货时间
正常订单会在 48 小时内发货。

## 延迟发货
如遇节假日或库存不足，发货时间可能延长至 5 个工作日。

## 发错货
若客户收到错误商品，客服需要先核对订单并登记异常工单。
""",
}


def main() -> None:
    RAW_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for filename, content in DOCS.items():
        path = RAW_DOCS_DIR / filename
        path.write_text(content, encoding="utf-8")
        print(f"Prepared: {path}")


if __name__ == "__main__":
    main()