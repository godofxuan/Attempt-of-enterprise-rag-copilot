import { useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  type ConversationSummary,
  type Status,
  type Run,
} from "../api/client";
import { Assistant } from "../features/Assistant";
import { Requests } from "../features/Requests";
import { LibraryPage } from "../features/Library";
import { Desk } from "../features/Desk";
import { SettingsPage } from "../features/Settings";
import { TaskDetail } from "../features/TaskDetail";
export function App() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const cache = useQueryClient();
  const [archived, setArchived] = useState(false);
  const conversations = useInfiniteQuery({
    queryKey: ["conversations", filter, archived],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<{ items: ConversationSummary[]; next_cursor: string | null }>(
        "/api/conversations/page?" +
          new URLSearchParams({
            q: filter,
            archived: String(archived),
            limit: "15",
            ...(pageParam ? { cursor: pageParam } : {}),
          }),
      ),
    getNextPageParam: (page) => page.next_cursor,
  });
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => api<Status>("/api/status"),
    refetchInterval: 30000,
  });
  const cid = params.get("c");
  const taskId = params.get("task");
  const rows = conversations.data?.pages.flatMap((page) => page.items) || [];
  const openTask = (id: string) =>
    setParams((old) => {
      const p = new URLSearchParams(old);
      p.set("task", id);
      return p;
    });
  const closeTask = () =>
    setParams((old) => {
      const p = new URLSearchParams(old);
      p.delete("task");
      return p;
    });
  const onRun = (run: Run, conversationId?: string | null) => {
    cache.invalidateQueries({
      queryKey: ["conversation-runs", run.conversation_id || conversationId],
    });
    if (conversationId)
      navigate(
        "/assistant?c=" + conversationId + (taskId ? "&task=" + taskId : ""),
      );
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/assistant">
          <span className="brand-symbol">E</span>
          <span>
            ESA<small>知识与服务助理</small>
          </span>
        </Link>
        <button className="new-chat" onClick={() => navigate("/assistant")}>
          ＋ 新会话
        </button>
        <nav aria-label="主导航">
          <NavLink to="/assistant">◌ 助理</NavLink>
          <NavLink to="/requests">▤ 我的事项</NavLink>
          <NavLink to="/library">▥ 资料库</NavLink>
        </nav>
        <details className="recent" open>
          <summary>最近会话</summary>
          <input
            type="search"
            aria-label="搜索会话"
            placeholder="搜索历史"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="recent-list">
            {rows.map((c) => (
              <Link
                aria-current={cid === c.id ? "page" : undefined}
                key={c.id}
                title={c.title || "知识会话"}
                to={"/assistant?c=" + c.id}
              >
                {c.title || "知识会话"}
              </Link>
            ))}
          </div>
          {conversations.hasNextPage && (
            <button
              disabled={conversations.isFetchingNextPage}
              onClick={() => conversations.fetchNextPage()}
            >
              更多会话
            </button>
          )}
          {!rows.length && <p className="muted">没有匹配的会话</p>}
          <button onClick={() => setArchived(!archived)}>
            {archived ? "查看当前会话" : "查看归档"}
          </button>
          {cid && (
            <div className="inline">
              <button
                onClick={async () => {
                  const title = window.prompt(
                    "会话名称",
                    rows.find((r) => r.id === cid)?.title || "",
                  );
                  if (title?.trim()) {
                    await api("/api/conversations/" + cid, "PATCH", {
                      title: title.trim(),
                    });
                    cache.invalidateQueries();
                  }
                }}
              >
                重命名
              </button>
              <button
                onClick={async () => {
                  await api("/api/conversations/" + cid, "PATCH", {
                    archived: !archived,
                  });
                  cache.invalidateQueries();
                  navigate("/assistant");
                }}
              >
                {archived ? "恢复会话" : "归档会话"}
              </button>
            </div>
          )}
        </details>
        <nav className="secondary" aria-label="更多工具">
          <NavLink to="/desk">演示服务台</NavLink>
          <NavLink to="/settings">设置</NavLink>
        </nav>
        <div className="connection">
          <i className={status.data?.chat.ready ? "connected" : ""} />
          {status.data?.chat.ready ? "本地模型可用" : "模型未连接"}
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>本地工作空间</span>
          <Link to="/settings">
            {status.data?.mode === "SYNTHETIC_LOCAL"
              ? "合成演示数据"
              : "个人工作区"}
          </Link>
        </header>
        {status.data && !status.data.onboarding_complete && (
          <div className="connection-banner">
            首次使用：① 当前工作区 → ② 连接已有本地模型 → ③ 导入资料或启用 TEST
            演示。
            <Link to="/settings">完成首次配置</Link>
          </div>
        )}
        {status.data?.configuration_error && (
          <div role="alert" className="connection-banner">
            {status.data.configuration_error.message}
            <Link to="/settings">修复配置</Link>
          </div>
        )}
        {status.data && !status.data.chat.ready && (
          <div className="connection-banner">
            模型尚未就绪，历史与设置仍可使用。
            <Link to="/settings">连接模型</Link>
          </div>
        )}
        <div className="page">
          <Routes>
            <Route
              path="/requests"
              element={<Requests openTask={openTask} />}
            />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/desk" element={<Desk />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="*"
              element={
                <Assistant
                  drafts={drafts}
                  setDraft={(id, text) =>
                    setDrafts((v) => ({ ...v, [id]: text }))
                  }
                  openTask={openTask}
                />
              }
            />
          </Routes>
        </div>
      </main>
      <TaskDetail id={taskId} onClose={closeTask} onRun={onRun} />
    </div>
  );
}
