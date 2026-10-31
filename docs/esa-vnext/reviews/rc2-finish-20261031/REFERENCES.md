# 少量直接相关的实现依据

本轮不重新拉高星排名、不安装新框架。现有React/TanStack/Playwright已经提供需要的成熟机制；参考的是状态、操作和测试组织方式。

1. React — Choosing the State Structure
   https://react.dev/learn/choosing-the-state-structure
   用途：避免重复事实、矛盾布尔状态与页面各自维护同一对象。不是限制if语句数量。
2. TanStack Query — Invalidations from Mutations
   https://tanstack.com/query/latest/docs/framework/react/guides/invalidations-from-mutations
   用途：持久化动作成功后及时更新/失效相关数据。两个独立服务请求不能等第二个成功才承认第一个成功。
3. W3C — Contrast Minimum
   https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
   用途：正文/说明的可读性；普通文字4.5:1目标，不把单项检查称为全面认证。
4. WAI APG — Dialog Modal
   https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/
   用途：保持现有Dialog的焦点、Tab、Escape与返回触发点；不重新写组件库。
5. Playwright — Best Practices
   https://playwright.dev/docs/best-practices
   用途：测试用户可见行为、隔离数据、不依赖内部函数名和CSS实现细节。

本轮没有新功能需要再搬入Open WebUI、Dify或Deep Agents整个系统。此前已采用的单应用发行、三入口、原生工具循环和事件结构继续使用。技术参考不能代替当前产品验证。
