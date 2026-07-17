# Demo Assets

最后更新：2026-07-17

本目录保存可公开的真实 UI 截图，不保存原始 prompts、身份详情、私有 artifacts 或浏览器 session 数据。项目首页引用固定文件名：

```text
ask.png
trace.png
evaluation.png
```

## Capture contract

- FastAPI 与 Streamlit 使用无 reload 的前台/记录 PID 进程；
- Ask 运行 canonical single-document case，响应来自真实 `/agent/v2/chat`；
- Trace 与 Ask 使用同一 request ID/session；
- Evaluation 读取 checked-in public snapshot；
- desktop viewport：1440 x 1000；
- mobile verification viewport：390 x 844；
- PNG 不包含本机绝对路径、终端、浏览器账号、secret、非 synthetic email 或 ignored artifact 内容；
- 检查文本溢出、重叠、横向页面滚动、空白 chart、错误 icon/font 和 console error；
- 截图必须与当前 checkout 同一轮浏览器验收生成，不能复用旧 UI 资产。

## Expected content

`ask.png`：Scenario、问题、UserContext 摘要、mode/stop/request/latency、回答、claim verification 与 authorized source。

`trace.png`：evidence coverage、action sequence、budget、HTTP/model/spans；不得显示问题、identity 或 source preview。

`evaluation.png`：frozen 28/28、live 23/24、quality chart/table、source provenance；Security tab 另行验证 indirect injection 显示 `NOT RUN`。

移动端截图用于验收但不作为 README 主资产；除非后续明确需要，不额外提交重复图片。

## Current capture evidence

三张文件来自同一轮 E6 真实联调，均为 1440 x 1000 PNG：

| File | Bytes | SHA-256 |
|---|---:|---|
| `ask.png` | 209,063 | `d6eae8c3425bf0a8a1d227354e612fd9900c89c2f5c0b53d75b9f35330053c81` |
| `trace.png` | 191,791 | `c465ccc3787928c7ce6c95dfa0bbb7695776784ea43543ed7ba0b70b3267efe2` |
| `evaluation.png` | 322,123 | `f01d507ac0e1072aed732d100776f3dc705b59375b0f35b121fa310dd0300048` |

移动端 390 x 844 验收没有提交重复图片，但保留了可复现的 DOM 数值：页面 `clientWidth=390` 且 `scrollWidth=390`；Ask 的 8 个 metric 与 Trace 的 8 个 metric 均按单列堆叠；数据表宽度受容器约束并只在表格内部滚动。

返回 [README](../../README.md) 或查看 [Demo Runbook](../demo_runbook.md)。
