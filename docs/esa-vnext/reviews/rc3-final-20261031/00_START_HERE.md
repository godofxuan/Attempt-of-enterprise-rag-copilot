# ESA rc3：本轮收尾与教学接入

审核对象：`ESA-0.7.0rc3-windows-x64-13fbe071.zip`，应用 `13fbe0714a59f6b52a75796156f560faa0af9123`。
日期：2026-10-31。**本包是审核结果、有限实施任务和可直接使用的教学资源，不是已修复发行包。**

## 只交接这一个包

- 开发工作区中的 Codex：读 `03_CODEX_ENGINEERING.md`，按6项工作修完并交付。
- 学习实验室中的 Codex：读 `teaching/01_CODEX_TEACHING.md`，先接续真实断点，再使用本版资源；不要替用户完成教学作答。
- 两种角色不互相越权：开发回归通过不代表学生掌握；教学练习不改正式业务数据和产品源码。

本轮不新增框架、第三业务、AgentOps系统或新的解释研究。完成既定修复、相关UI整理、发行验证与教学资料映射，就结束工程任务。学习是使用这版资源，不是启动下一轮产品开发。

## 建议阅读顺序

1. `01_AUDIT.md`：哪些真正改善、哪些复现、哪些未验证。
2. `02_FINAL_PLAN.md`：3组问题与有限的页面/代码修正。
3. `04_ACCEPTANCE.md`：10类用户行为，不是无限测试清单。
4. `teaching/COURSE_MAP.md` 与 `teaching/NEXT_LESSON.md`：8个桥接单元、48个题答、6个标准库实验；实际开课前读取当前学习断点。

所有题目和答案分别放在 `teaching/questions.jsonl` 与 `teaching/answers.jsonl`。
新资源使用 `ESA3-*` 命名空间，不覆盖已有题号或学习状态。资源登记不代表净新增知识点，也不代表已掌握。

## 可运行内容

```bash
# 只检查本包资源结构、ID和引用，不修改教学状态
python tools/validate_pack.py
# 六个独立教学实验，不访问真实产品或模型
python teaching/labs/run_all.py
# 查看一道题，默认不显示答案
python teaching/tools/study.py get ESA3-L05-Q03
python teaching/tools/study.py get ESA3-L05-Q03 --answer
# 在当前源码定位真实函数，不导入/启动应用
python teaching/tools/locate_source.py --source /actual/repo --lesson L05
```

缺陷复现另在 `tools/reproduce_rc3.py`，必须使用实际项目受支持环境、显式设置 `ESA_SOURCE`。它只对临时合成工作区操作；`DEFECT_REPRODUCED`是发现缺陷，不是验收通过。无需为了上课运行整个审核脚本。

## 版本和未完成范围

发行包含后端Python与构建后JS/CSS，不含当前TS源码、当前完整测试、Git历史和用户本机教学状态。
本次没有修改产品、推送远端、导入本机实验室或更新学生进度。
本机后续修复优先于本快照，Codex须定位当前源码后只做仍缺少的部分。
