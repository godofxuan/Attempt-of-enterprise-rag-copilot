# 复现工具范围

这些脚本用于本轮读取0.4原源码，全部业务写入临时合成工作区；不修改项目、不连接用户数据库。其结果是缺陷复现，不是修复通过。

```text
python tools/core_probes.py --source /absolute/path/to/source --out /tmp/core_probes.json
python tools/ui_replay_probe.py --source /absolute/path/to/source --out /tmp/ui-replay
```

运行需要相应Python依赖。UI回放额外需要Playwright Python与`/usr/bin/chromium`，浏览器路径是本次环境的具体值，在其他平台需调整。它用合成fetch/localStorage适配执行原DOM和JS，是前端回放，不是HTTP后端+模型端到端。

正式实现时，将复现缺陷的期待改成正确行为断言。不要把脚本执行成功、保存了DEFECT_REPRODUCED当产品通过。
