# 复现工具用法

这两份工具仅对本次0.6源码复现旧问题，使用临时合成数据库，不读取你的活动工作区。外部模型回答/工具选择为明确测试适配，不是live模型。

在项目受支持的Python3.11/3.12环境安装项目及测试依赖，指定真正项目根目录：

```bash
python tools/reproduce_api_findings.py --source /path/to/esa/source --out review-output
python tools/reproduce_mixed_turn.py --source /path/to/esa/source --out review-output
```

第一份会暂时启动本工具创建的本地测试实例，读取后通过自身API关闭；不是用户活动服务。工具不会修改应用源码，但Python可能生成正常导入缓存。

输出中的defect_reproduced=true表示旧缺陷出现，绝不表示新版修复通过。修复后应把场景移入产品正式测试并断言正确行为；函数/fixture调整后允许适配工具，不允许改弱业务目标。

本审核在Python3.13环境检查了相应行为，不能用它代替支持平台与最终Windows产物验收。
