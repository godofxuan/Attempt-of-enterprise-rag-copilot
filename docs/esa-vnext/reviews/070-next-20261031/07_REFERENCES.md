# 本次实际打开的一手参考（2026-10-31）

|参考|链接|采用的内容|不采用的内容|
|---|---|---|---|
|GitHub PR quickstart|https://docs.github.com/en/pull-requests/get-started/pull-request-quickstart|推feature分支、Draft PR共享进行中的工作|把push当正式发布|
|GitHub merging PR|https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request|草稿不能合并、required checks与合并不同于push|虚构仓库已配置的保护规则|
|SQLite WAL|https://www.sqlite.org/wal.html|读写并发改善，但仍只有一个writer，仍可能BUSY|WAL能消除所有锁、以超长timeout代替短事务|
|SQLite transactions|https://sqlite.org/lang_transaction.html|明确事务、读到写升级限制|每层随意打开新写连接|
|Deep Agents architecture|https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md|runtime、loop、capability装配职责分开|迁移全平台或增加子Agent|
|Onyx chat context|https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/chat/README.md|模型看到简洁证据、UI保留丰富引用、上下文预算|照搬所有连接器和检索服务|
|Open WebUI packaging|https://raw.githubusercontent.com/open-webui/open-webui/main/pyproject.toml|前端构建进入发行包，安装与日常运行分开|再扩容其全部依赖或切换桌面平台|
|项目公开主页|https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot|了解公开历史主线|将缓存网页当最新远端HEAD；实际同步以git fetch为准|

未重新统计Star，不将热度当质量证据。只学习与当前问题匹配的机制。
