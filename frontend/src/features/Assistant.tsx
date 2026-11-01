import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router-dom";
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
import {
  refreshRunScope,
  refreshTaskScope,
  retryConversationTurn,
} from "../api/taskActions";
type RequestScope = { locationKey: string; conversationId: string | null };
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
  const location = useLocation();
  const currentLocation = useRef<string | null>(location.key);
  const currentDrafts = useRef(drafts);
  currentLocation.current = location.key;
  currentDrafts.current = drafts;
  useEffect(() => {
    currentLocation.current = location.key;
    return () => {
      currentLocation.current = null;
    };
  }, []);
  const requestScope = (): RequestScope => ({
    locationKey: location.key,
    conversationId: cid,
  });
  const belongsHere = (scope?: RequestScope) =>
    scope?.conversationId === cid &&
    (cid !== null || scope?.locationKey === location.key);
  const cache = useQueryClient();
  const [base, setBase] = useState("");
  const [deep, setDeep] = useState(false);
  const [kind, setKind] = useState<string | null>(null);
  const [scope, setScope] = useState("SUBMIT_AFTER_CONFIRMATION");
  const composing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const following = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  useEffect(() => {
    const track = () => {
      following.current =
        document.documentElement.scrollHeight - innerHeight - scrollY < 220;
      setShowLatest(!following.current);
    };
    window.addEventListener("scroll", track, { passive: true });
    return () => window.removeEventListener("scroll", track);
  }, []);
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
  useEffect(() => {
    if (following.current)
      requestAnimationFrame(() =>
        input.current?.scrollIntoView({ block: "end" }),
      );
  }, [conversation.data?.turns.length]);
  const progress = useRun(runId);
  const track = (r: Run) => {
    if (r.conversation_id)
      cache.setQueryData<Run[]>(
        ["conversation-runs", r.conversation_id],
        (old = []) => [r, ...old.filter((x) => x.id !== r.id)],
      );
    refreshRunScope(cache, r);
  };
  const binding = useMutation({
    mutationFn: ({ cid, kb_id }: { cid: string; kb_id: string }) =>
      api<Conversation>("/api/conversations/" + cid, "PATCH", {
        kb_id: kb_id || null,
      }),
    onSuccess: async (value) => {
      cache.setQueryData(["conversation", value.id], value);
      const ids = new Set(
        [value.task_id, value.active_task_id].filter(Boolean),
      );
      if (ids.size)
        await Promise.all(
          [...ids].map((id) => refreshTaskScope(cache, id!, value.id)),
        );
      else
        await Promise.all([
          cache.invalidateQueries({ queryKey: ["conversations"] }),
          cache.invalidateQueries({
            queryKey: ["conversation-runs", value.id],
          }),
        ]);
    },
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
    mutationFn: async (owner: RequestScope) => {
      const draftId = owner.conversationId || "new";
      const text = drafts[draftId] || "";
      if (!text.trim()) return;
      const target = await ensure();
      const r = await api<Run>(
        "/api/conversations/" + target + "/turns",
        "POST",
        { text, message_id: crypto.randomUUID(), detailed: deep },
      );
      if (currentDrafts.current[draftId] === text) setDraft(draftId, "");
      if (currentLocation.current === owner.locationKey)
        setParams({ c: target });
      track(r);
    },
  });
  const start = useMutation({
    mutationFn: async (owner: RequestScope) => {
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
      if (currentLocation.current === owner.locationKey) setKind(null);
      await refreshTaskScope(cache, task.task_id, target);
      // One navigation after the async creation. React Router's search-param
      // callbacks are not queued React state and can retain a pre-create URL.
      if (currentLocation.current === owner.locationKey)
        setParams({ c: target, task: task.task_id });
    },
  });
  const retry = useMutation({
    mutationFn: async ({
      id,
      knowledge,
    }: {
      id: string;
      knowledge: boolean;
    }) => {
      track(await retryConversationTurn(cid!, id, knowledge));
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
            cid
              ? binding.mutate({ cid, kb_id: e.target.value })
              : setBase(e.target.value)
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
      {belongsHere(send.variables) && send.error && (
        <ErrorNotice error={send.error} />
      )}
      {belongsHere(start.variables) && start.error && (
        <ErrorNotice error={start.error} />
      )}
      {retry.error && <ErrorNotice error={retry.error} />}
      {binding.error && <ErrorNotice error={binding.error} />}
      {binding.isSuccess && binding.data.id === cid && binding.data.kb_id && (
        <p role="status">资料库已选择，可继续刚才的问题。</p>
      )}
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
              ) : turn.role === "assistant" &&
                turn.payload?.turn_delivery?.status === "partial" ? (
                <>
                  <p>
                    {deliverySummary(
                      turn.payload.turn_delivery,
                      task.data?.turn_delivery,
                    )}
                  </p>
                  <details>
                    <summary>本次执行说明</summary>
                    <ReactMarkdown>{turn.text}</ReactMarkdown>
                  </details>
                </>
              ) : (
                <ReactMarkdown>{turn.text}</ReactMarkdown>
              )}
              {turn.payload?.preview && (
                <p className="muted">完整预览已保存在事项详情中。</p>
              )}
              <TurnRecovery
                turn={turn}
                task={task.data}
                busy={!!runId || retry.isPending}
                retry={(knowledge) => retry.mutate({ id: turn.id, knowledge })}
                hasLibrary={!!conversation.data?.kb_id}
                selectLibrary={() =>
                  document
                    .querySelector<HTMLSelectElement>(
                      '[aria-label="当前资料库"]',
                    )
                    ?.focus()
                }
                openTask={openTask}
              />
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
      {showLatest && (
        <button
          className="back-to-latest"
          onClick={() => {
            following.current = true;
            input.current?.scrollIntoView({
              block: "end",
              behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
                ? "auto"
                : "smooth",
            });
          }}
        >
          回到最新
        </button>
      )}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send.mutate(requestScope());
        }}
      >
        <textarea
          ref={input}
          aria-label="给助理发消息"
          placeholder="问资料、补充信息，或告诉我需要怎样修改…"
          value={text}
          maxLength={2000}
          disabled={send.isPending && belongsHere(send.variables)}
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
              if (!runId && text.trim()) send.mutate(requestScope());
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
            disabled={
              !!runId ||
              (send.isPending && belongsHere(send.variables)) ||
              !text.trim()
            }
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
          disabled={start.isPending && belongsHere(start.variables)}
          onClick={() => start.mutate(requestScope())}
        >
          按所选范围开始
        </button>
      </Drawer>
    </div>
  );
}

function deliverySummary(
  record: { turn_id?: string },
  current?: Task["turn_delivery"],
) {
  if (record.turn_id !== current?.turn_id)
    return "这条历史记录曾有未交付内容，当前状态见事项。";
  return current?.status === "complete"
    ? "这条记录的未完成内容已续办，结果见后续回答。"
    : "已保存部分结果。" +
        (current?.next_action || "查看当前事项继续未完成内容。");
}

function TurnRecovery({
  turn,
  task,
  busy,
  retry,
  openTask,
  hasLibrary,
  selectLibrary,
}: {
  turn: Conversation["turns"][number];
  task?: Task;
  busy: boolean;
  retry: (knowledge: boolean) => void;
  hasLibrary: boolean;
  selectLibrary: () => void;
  openTask: (id: string) => void;
}) {
  if (turn.role !== "user") return null;
  const latest = task?.turn_delivery?.turn_id === turn.id;
  const delivery = latest ? task!.turn_delivery : turn.payload?.turn_delivery;
  const status =
    latest && delivery?.status === "complete"
      ? "DONE"
      : latest && delivery?.status === "partial"
        ? "PARTIAL"
        : turn.status;
  if (
    !["FAILED", "CANCELLED", "INTERRUPTED", "PARTIAL", "WAITING_USER"].includes(
      status,
    )
  )
    return null;
  const finished =
    task?.id === turn.payload?.task_id && (task?.closed || !!task?.receipt);
  const canRetry =
    delivery?.retryable !== false &&
    status !== "WAITING_USER" &&
    (!finished || delivery?.pending?.includes("knowledge"));
  const knowledge = !!delivery?.pending?.includes("knowledge");
  const missingLibrary = (knowledge || !turn.payload?.task_id) && !hasLibrary;
  return (
    <div className="retry-note">
      <span>
        {canRetry
          ? "未完成的内容可继续，已有结果保留"
          : status === "WAITING_USER"
            ? latest && !finished
              ? "等待补充必要信息"
              : "当时曾等待补充，查看事项了解当前状态"
            : "本次执行已停止或尚未完成"}
      </span>
      {canRetry ? (
        <button
          disabled={busy}
          onClick={() => (missingLibrary ? selectLibrary() : retry(knowledge))}
        >
          {missingLibrary
            ? "选择资料库后继续解释"
            : delivery?.next_action || "重试这条消息"}
        </button>
      ) : (
        turn.payload?.task_id && (
          <button onClick={() => openTask(turn.payload!.task_id!)}>
            {latest && !finished ? "补充事项信息" : "查看事项"}
          </button>
        )
      )}
    </div>
  );
}
