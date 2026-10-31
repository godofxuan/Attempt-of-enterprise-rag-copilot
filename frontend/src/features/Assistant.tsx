import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  api,
  type Conversation,
  type Answer,
  type Library,
  type Run,
  type Task,
  type JSONRecord,
} from "../api/client";
import { AnswerView } from "../components/AnswerView";
import { Drawer, ErrorNotice, Parameters } from "../components/common";
import { useRun } from "../api/useRun";
import { RunTrace } from "../components/RunTrace";
export function Assistant({
  drafts,
  setDraft,
  openTask,
}: {
  drafts: Record<string, string>;
  setDraft: (id: string, value: string) => void;
  openTask: (id: string) => void;
}) {
  const [params, setParams] = useSearchParams();
  const cid = params.get("c");
  const cache = useQueryClient();
  const [base, setBase] = useState("");
  const [deep, setDeep] = useState(false);
  const [kind, setKind] = useState<string | null>(null);
  const [scope, setScope] = useState("SUBMIT_AFTER_CONFIRMATION");
  const composing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const library = useQuery({
    queryKey: ["library"],
    queryFn: () => api<Library>("/api/library"),
  });
  const conversation = useQuery({
    queryKey: ["conversation", cid],
    enabled: !!cid,
    queryFn: () => api<Conversation>("/api/conversations/" + cid),
  });
  const runs = useQuery({
    queryKey: ["conversation-runs", cid],
    enabled: !!cid,
    queryFn: () => api<Run[]>("/api/product/conversations/" + cid + "/runs"),
    refetchInterval: 2000,
  });
  const runId =
    runs.data?.find(
      (r) =>
        r.conversation_id === cid && ["queued", "running"].includes(r.status),
    )?.id || null;
  const active = conversation.data?.active_task_id;
  const shownTask = active || conversation.data?.task_id;
  const task = useQuery({
    queryKey: ["task", shownTask],
    enabled: !!shownTask,
    queryFn: () => api<Task>("/api/product/tasks/" + shownTask),
  });
  const finish = useCallback(() => {
    cache.invalidateQueries();
  }, [cache]);
  const progress = useRun(runId, finish);
  const track = (r: Run) => {
    if (r.conversation_id)
      cache.setQueryData<Run[]>(
        ["conversation-runs", r.conversation_id],
        (old = []) => [r, ...old.filter((x) => x.id !== r.id)],
      );
    cache.invalidateQueries();
  };
  const binding = useMutation({
    mutationFn: (kb_id: string) =>
      api<Conversation>("/api/conversations/" + cid, "PATCH", {
        kb_id: kb_id || null,
      }),
    onSuccess: () => cache.invalidateQueries(),
  });
  const ensure = async () => {
    if (cid) return cid;
    const c = await api<Conversation>("/api/conversations", "POST", {
      title: (drafts.new || "新会话").slice(0, 60),
      kb_id: base || library.data?.bases[0]?.id || null,
    });
    return c.id;
  };
  const send = useMutation({
    mutationFn: async () => {
      const text = drafts[cid || "new"] || "";
      if (!text.trim()) return;
      const target = await ensure();
      const r = await api<Run>(
        "/api/conversations/" + target + "/turns",
        "POST",
        { text, message_id: crypto.randomUUID(), detailed: deep },
      );
      setDraft(cid || "new", "");
      setParams({ c: target });
      track(r);
    },
  });
  const start = useMutation({
    mutationFn: async () => {
      const target = await ensure();
      const task = await api<JSONRecord>("/api/tasks", "POST", {
        request: { kind, execution_ceiling: scope, confirmed: true },
        conversation_id: target,
        kb_id:
          conversation.data?.kb_id ||
          base ||
          library.data?.bases[0]?.id ||
          null,
      });
      setKind(null);
      await cache.invalidateQueries();
      // One navigation after the async creation. React Router's search-param
      // callbacks are not queued React state and can retain a pre-create URL.
      setParams({ c: target, task: task.task_id });
    },
  });
  const retry = useMutation({
    mutationFn: async (id: string) => {
      track(
        await api<Run>(
          "/api/product/conversations/" + cid + "/turns/" + id + "/retry",
          "POST",
          {},
        ),
      );
    },
  });
  const text = drafts[cid || "new"] || "";
  return (
    <div className="assistant-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">你的本地知识与服务助理</p>
          <h1>{conversation.data?.title || "今天有什么需要帮忙？"}</h1>
        </div>
        <select
          aria-label="当前资料库"
          value={
            cid
              ? conversation.data?.kb_id || ""
              : base || library.data?.bases[0]?.id || ""
          }
          disabled={binding.isPending || !!runId}
          onChange={(e) =>
            cid ? binding.mutate(e.target.value) : setBase(e.target.value)
          }
        >
          <option value="">选择资料库</option>
          {library.data?.bases.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </div>
      {conversation.error && <ErrorNotice error={conversation.error} />}
      {send.error && <ErrorNotice error={send.error} />}
      {start.error && <ErrorNotice error={start.error} />}
      {retry.error && <ErrorNotice error={retry.error} />}
      {binding.error && <ErrorNotice error={binding.error} />}
      {cid && !conversation.data?.kb_id && (
        <p className="muted">
          此会话尚未绑定资料库。知识提问可先选择资料库，再重试原消息；纯业务查询不需要资料库。
        </p>
      )}
      {!cid && (
        <div className="welcome">
          <p>查资料、了解政策，或办理电脑借用和 IT 报修。</p>
          <div className="quick-actions">
            <button onClick={() => input.current?.focus()}>问资料</button>
            <button onClick={() => setKind("loan")}>借用电脑</button>
            <button onClick={() => setKind("repair")}>IT 报修</button>
          </div>
        </div>
      )}
      {shownTask && task.data && (
        <button className="task-summary" onClick={() => openTask(shownTask)}>
          <strong>{task.data.title}</strong>
          <span>{task.data.status_label}</span>
          <span>查看参数与下一步 →</span>
        </button>
      )}
      <div className="messages">
        {conversation.isPending && cid ? (
          <p>正在打开会话…</p>
        ) : (
          conversation.data?.turns.map((turn) => (
            <article key={turn.id} className={"message " + turn.role}>
              <div className="message-role">
                {turn.role === "user"
                  ? "你"
                  : turn.role === "tool"
                    ? "资料查询"
                    : "ESA"}
              </div>
              {turn.role === "assistant" &&
              (turn.payload?.knowledge || turn.payload?.result?.sources) ? (
                <AnswerView
                  value={(turn.payload.knowledge || turn.payload) as Answer}
                />
              ) : (
                <ReactMarkdown>{turn.text}</ReactMarkdown>
              )}
              {turn.payload?.preview && (
                <p className="muted">完整预览已保存在事项详情中。</p>
              )}
              {turn.role === "user" &&
                ["FAILED", "CANCELLED", "INTERRUPTED"].includes(
                  turn.status,
                ) && (
                  <div className="retry-note">
                    <span>
                      {turn.status === "CANCELLED"
                        ? "本次执行已停止"
                        : "这次没有完成，原消息已保留"}
                    </span>
                    <button
                      disabled={!!runId || retry.isPending}
                      onClick={() => retry.mutate(turn.id)}
                    >
                      重试这条消息
                    </button>
                  </div>
                )}
            </article>
          ))
        )}
      </div>
      {runId && (
        <div className="run-progress" role="status">
          <span className="pulse" />
          {progress}
          <button
            onClick={() =>
              api("/api/runs/" + runId + "/cancel", "POST", {}).catch(() => {})
            }
          >
            停止本次执行
          </button>
        </div>
      )}
      <RunTrace id={runId || runs.data?.[0]?.id} />
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send.mutate();
        }}
      >
        <textarea
          ref={input}
          aria-label="给助理发消息"
          placeholder="问资料、补充信息，或告诉我需要怎样修改…"
          value={text}
          maxLength={2000}
          disabled={send.isPending}
          onChange={(e) => setDraft(cid || "new", e.target.value)}
          onCompositionStart={() => (composing.current = true)}
          onCompositionEnd={() => (composing.current = false)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing &&
              !composing.current &&
              e.keyCode !== 229
            ) {
              e.preventDefault();
              if (!runId && text.trim()) send.mutate();
            }
          }}
        />
        <div className="composer-bottom">
          <label className="inline">
            <input
              type="checkbox"
              checked={deep}
              onChange={(e) => setDeep(e.target.checked)}
            />
            深入比较
          </label>
          <span className="muted">Enter 发送 · Shift+Enter 换行</span>
          <button
            className="primary"
            disabled={!!runId || send.isPending || !text.trim()}
            type="submit"
          >
            发送
          </button>
        </div>
      </form>
      {cid && !active && (
        <div className="inline service-start">
          <span>继续办理</span>
          <button onClick={() => setKind("loan")}>借用电脑</button>
          <button onClick={() => setKind("repair")}>IT 报修</button>
        </div>
      )}
      <Drawer
        title={kind === "loan" ? "开始电脑借用事项" : "开始 IT 报修事项"}
        open={!!kind}
        onClose={() => setKind(null)}
      >
        <p>请选择本次需要做到哪一步。提交仍需要你核对当前预览后单独确认。</p>
        <div className="scope-options">
          {[
            ["READ_ONLY", "先了解：只查询，不准备申请"],
            ["PREVIEW_ONLY", "只生成完整预览，绝不提交"],
            ["SUBMIT_AFTER_CONFIRMATION", "准备申请，预览后由我确认提交"],
          ].map(([v, t]) => (
            <label key={v}>
              <input
                type="radio"
                name="scope"
                checked={scope === v}
                onChange={() => setScope(v)}
              />
              {t}
            </label>
          ))}
        </div>
        <button
          className="primary"
          disabled={start.isPending}
          onClick={() => start.mutate()}
        >
          按所选范围开始
        </button>
      </Drawer>
    </div>
  );
}
