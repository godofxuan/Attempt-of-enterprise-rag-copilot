# 可选复现工具
本工具只验证被标明的控制流，使用临时SQLite和合成数据，替换模型选择与知识回答，不连接真实企业系统。它不是全量或真实模型测试，也不是完成判定器。生成的输出可能包含旧缺陷的实际行为，修复后应转成正确预期回归。

```powershell
# 当前项目环境内执行；不要把旧Windows依赖复制到Linux使用
$env:ESA_SOURCE = "当前真实源码目录"
$env:ESA_PROBE_OUT = "rc2_probe_results.json"
python .\reproduce_rc2.py
```

Linux等价：
```bash
ESA_SOURCE=/path/to/project ESA_PROBE_OUT=rc2_probe_results.json python reproduce_rc2.py
```

依赖当前项目的FastAPI/TestClient等正常环境。不能把脚本输出中复现问题的记录当成新版通过。旧7项pytest日志只作为本次复核证据，不建议为了运行这些旧路径重新导入整个旧项目。
