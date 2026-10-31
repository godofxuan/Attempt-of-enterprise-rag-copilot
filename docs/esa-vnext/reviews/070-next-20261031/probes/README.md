# 复现方式

使用项目支持的Python环境，在候选仓库根目录运行：

```bash
python /path/to/handoff/probes/reproduce_default.py
```

或设置ESA_SOURCE为仓库根目录。ESA_PROBE_OUT可指定结果文件。脚本只写临时合成工作区和结果文件，不连接真实模型、不访问活动DATA_DIR。

当前旧缺陷：partial_failure结果turn=DONE且retry_http=409；omitted_knowledge没有知识结果却task=COMPLETED。两个场景都不会写业务申请。修复后应按02_IMPLEMENTATION建立新的正确行为断言，不把复现成功当验收通过。
