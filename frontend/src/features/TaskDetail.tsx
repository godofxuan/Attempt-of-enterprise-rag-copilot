import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type Task,
  type JSONRecord,
  type Run,
  type Answer,
  label,
} from "../api/client";
import { useTaskActions } from "../api/taskActions";
import { Drawer, ErrorNotice, Parameters } from "../components/common";
import { AnswerView } from "../components/AnswerView";

export function TaskDetail({
  id,
  onClose,
  onRun,
}: {
  id: string | null;
  onClose: () => void;
  onRun: (run: Run, cid?: string | null) => void;
}) {
  const cache = useQueryClient();
  const [dirty, setDirty] = useState(false);
  const [choice, setChoice] = useState<JSONRecord | null>(null);
  const fields = useRef<HTMLDivElement>(null);
  const resources = useRef<HTMLDetailsElement>(null);
  const task = useQuery({
    queryKey: ["task", id],
    enabled: !!id,
    queryFn: ({ signal }) =>
      api<Task>("/api/product/tasks/" + id, "GET", undefined, signal),
  });
  const t = task.data;
  const actions = useTaskActions(id, onRun);
  const [deadlineReached, setDeadlineReached] = useState(false);
  useEffect(() => {
    setDeadlineReached(false);
    if (!t?.preview || t.receipt || t.preview_state !== "current") return;
    const refresh = () => {
      void cache.invalidateQueries({ queryKey: ["task", t.id] });
    };
    const timer = window.setTimeout(
      () => {
        setDeadlineReached(true);
        refresh();
      },
      Math.max(0, t.preview.expires_at - t.server_time) * 1000,
    );
    window.addEventListener("focus", refresh);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [
    t?.id,
    t?.preview?.proposal_id,
    t?.server_time,
    t?.preview_state,
    t?.receipt,
    cache,
  ]);
  const expired = deadlineReached || t?.preview_state === "expired";
  const previewCurrent = t?.preview_state === "current" && !deadlineReached;
  const kind =
    expired && t?.next_action?.kind === "preview"
      ? "prepare"
      : t?.next_action?.kind;
  const runs = useQuery({
    queryKey: ["conversation-runs", t?.conversation_id],
    enabled: kind === "running" && !!t?.conversation_id,
    queryFn: () =>
      api<Run[]>(`/api/product/conversations/${t!.conversation_id}/runs`),
    refetchInterval: kind === "running" ? 1000 : false,
  });
  const activeRun = runs.data?.find(
    (r) => r.target === id && ["queued", "running"].includes(r.status),
  );
  const choices = useQuery({
    queryKey: ["alternatives", id, t?.revision],
    enabled: !!id && !!t?.can_edit,
    queryFn: () => api<JSONRecord[]>(`/api/product/tasks/${id}/alternatives`),
  });
  useEffect(() => {
    setDirty(false);
    setChoice(null);
  }, [id]);
  useEffect(() => setChoice(null), [t?.revision]);
  useEffect(() => {
    if (kind === "choice" && resources.current) {
      resources.current.focus();
    } else if (kind === "input") {
      const first = t?.next_action?.fields[0];
      const node = first
        ? fields.current?.querySelector<HTMLInputElement>(
            `[data-field-name="${first}"]`,
          )
        : fields.current?.querySelector<HTMLInputElement>("input,select");
      node?.focus();
    }
  }, [id, kind, t?.next_action?.fields.join(",")]);
  const retry = () => {
    if (t?.turn_delivery && t.conversation_id) {
      actions.clearFeedback();
      actions.retryTurn.mutate({
        id: t.id,
        cid: t.conversation_id,
        turnId: t.turn_delivery.turn_id,
      });
    }
  };
  const pending = actions.busy || kind === "running";
  return (
    <Drawer
      title="事项详情"
      open={!!id}
      onClose={onClose}
      initialFocus={
        kind === "choice"
          ? ".resource-options"
          : kind === "input"
            ? t?.next_action?.fields[0]
              ? `[data-field-name="${t.next_action.fields[0]}"]`
              : "[data-field-name]"
            : undefined
      }
    >
      {!t ? (
        task.error ? (
          <ErrorNotice error={task.error} />
        ) : (
          <p>正在读取事项…</p>
        )
      ) : (
        <>
          <div className="detail-summary">
            <h2>{t.title}</h2>
            <span className="status-pill">{t.status_label}</span>
            <p>
              {expired
                ? "预览已过期，参数已保留。重新生成后再确认。"
                : actions.feedback?.message || t.next_step}
            </p>
            {actions.feedback?.error != null && (
              <ErrorNotice error={actions.feedback.error} />
            )}
            {actions.feedback?.detail != null && (
              <details>
                <summary>本次操作详情</summary>
                <pre>{String(actions.feedback.detail)}</pre>
              </details>
            )}
            {task.error && <ErrorNotice error={task.error} />}
            {t.turn_delivery &&
              Object.keys(t.turn_delivery.items).length > 0 && (
                <ul className="delivery-items" aria-label="本轮交付进度">
                  {Object.entries(t.turn_delivery.items).map(([name, raw]) => {
                    const item = raw as {
                      status: string;
                      blocked_by?: string[];
                    };
                    return (
                      <li key={name}>
                        {name === "knowledge" ? "知识回答" : "业务预览"}：
                        {item.status === "ready"
                          ? "已交付"
                          : item.blocked_by?.length
                            ? "等待补充业务条件"
                            : "尚未交付"}
                      </li>
                    );
                  })}
                </ul>
              )}
            <p className="muted">
              {t.receipt
                ? "当前业务状态与提交当时的回执分别保留。"
                : t.ceiling === "READ_ONLY"
                  ? "只读查询，不准备或提交申请。"
                  : t.ceiling === "PREVIEW_ONLY"
                    ? "仅生成预览，绝不提交。"
                    : "范围确认不等于提交确认；提交前需核对当前完整预览。"}
            </p>
            {kind === "retry_knowledge" && (
              <button className="primary" disabled={pending} onClick={retry}>
                重试解释
              </button>
            )}
            {activeRun && (
              <button
                onClick={() =>
                  actions.stopRun.mutate({ id: t.id, runId: activeRun.id })
                }
              >
                停止本次执行
              </button>
            )}
          </div>
          {t.pending_update && (
            <section className="card">
              <h3>核对未处理完的原消息</h3>
              <p>{t.pending_update.text}</p>
              <p className="muted">
                已保存参数保留。核对当前范围后继续，这不是提交确认。
              </p>
              {t.last_error && (
                <details>
                  <summary>上次执行详情</summary>
                  <pre>{t.last_error}</pre>
                </details>
              )}
              <button
                className="primary"
                disabled={pending}
                onClick={() => actions.resolveUpdate.mutate(t)}
              >
                已核对参数，保留当前范围并继续
              </button>
              <button
                disabled={pending}
                onClick={() =>
                  t.conversation_id &&
                  actions.retryTurn.mutate({
                    id: t.id,
                    cid: t.conversation_id,
                    turnId: t.pending_update!.id,
                  })
                }
              >
                重试原消息
              </button>
            </section>
          )}
          {t.current_ticket && (
            <section className="card">
              <h3>当前办理结果</h3>
              <p className="status-pill">
                {label[t.current_ticket.status] || t.status_label}
              </p>
              <Parameters
                value={{
                  ...t.current_ticket.parameters,
                  asset_id: t.current_ticket.asset_id,
                }}
              />
              <p>{t.current_ticket.next_step}</p>
            </section>
          )}
          <div ref={fields}>
            {t.can_edit ? (
              <FieldEditor
                key={t.id}
                task={t}
                onDirty={setDirty}
                pending={pending}
                savedRevision={
                  actions.saveFacts.data?.id === t.id
                    ? actions.saveFacts.data.revision
                    : null
                }
                save={(changes, revision) =>
                  actions.saveAndPrepare({ id: t.id, revision, changes })
                }
              />
            ) : (
              !t.receipt && (
                <Parameters
                  value={Object.fromEntries(
                    t.fields.map((f) => [f.name, f.value]),
                  )}
                />
              )
            )}
          </div>
          {t.can_edit && (
            <details
              ref={resources}
              open={kind === "choice" ? true : undefined}
              tabIndex={-1}
              className="resource-options"
            >
              <summary>可选设备与日期</summary>
              {choices.isPending ? (
                <p>读取实际资源…</p>
              ) : choices.error ? (
                <>
                  <ErrorNotice error={choices.error} />
                  <button onClick={() => choices.refetch()}>
                    重试库存查询
                  </button>
                </>
              ) : !choices.data?.length ? (
                <p>当前条件下没有可选资源。可明确修改日期或要求后再查询。</p>
              ) : (
                <>
                  <div
                    className="resource-grid"
                    role="radiogroup"
                    aria-label="选择实际设备"
                  >
                    {choices.data.map((c) => (
                      <div
                        className={
                          "resource card" +
                          (choice?.option_id === c.option_id ? " selected" : "")
                        }
                        key={c.option_id}
                      >
                        <label className="resource-heading">
                          <input
                            type="radio"
                            name={"resource-" + t.id}
                            aria-label={"选择设备 " + c.asset_id}
                            checked={choice?.option_id === c.option_id}
                            disabled={dirty || pending}
                            onChange={() => setChoice(c)}
                          />
                          <strong>{c.asset_id}</strong>
                        </label>
                        <Parameters
                          value={{
                            memory_gb: c.details?.memory_gb,
                            pickup_location: c.details?.pickup_location,
                            loan_start: c.parameters?.loan_start,
                            loan_end: c.parameters?.loan_end,
                          }}
                        />
                        {c.notice && <span className="muted">{c.notice}</span>}
                        <details>
                          <summary>设备更多信息</summary>
                          <pre>{JSON.stringify(c, null, 2)}</pre>
                        </details>
                      </div>
                    ))}
                  </div>
                  <button
                    className={kind === "choice" ? "primary" : ""}
                    disabled={!choice || dirty || pending}
                    onClick={() =>
                      choice &&
                      actions.selectAndPrepare({
                        id: t.id,
                        revision: t.revision,
                        assetId: choice.asset_id,
                        shift: choice.date_shift_days || 0,
                      })
                    }
                  >
                    选择并生成预览
                  </button>
                </>
              )}
            </details>
          )}
          {dirty && (
            <p className="notice" role="status">
              有未保存的修改。请先保存，再核对当前预览。
            </p>
          )}
          {t.can_edit &&
            !dirty &&
            (!t.preview || !previewCurrent) &&
            !t.receipt &&
            kind === "prepare" && (
              <button
                className="primary"
                disabled={pending}
                onClick={() => {
                  actions.clearFeedback();
                  actions.prepareTask.mutate({
                    id: t.id,
                    revision: t.revision,
                  });
                }}
              >
                {t.preview ? "重新生成预览" : "生成当前预览"}
              </button>
            )}
          {t.preview && !t.receipt && (
            <section className="card preview">
              <h3>
                {previewCurrent
                  ? "当前完整预览"
                  : expired
                    ? "已过期的预览（仅供参考）"
                    : "已失效的预览（仅供参考）"}
              </h3>
              <Parameters
                value={{
                  ...t.preview.content.parameters,
                  asset_id: t.preview.content.target,
                }}
              />
              <p>
                {t.preview.content.effect_notice ||
                  t.preview.content.notice ||
                  t.preview.content.next_step}
              </p>
              <p className="muted">
                依据规则：{t.preview.content.rule_version}
              </p>
              <details>
                <summary>核对完整预览内容</summary>
                <pre>{JSON.stringify(t.preview.content, null, 2)}</pre>
              </details>
              {t.can_submit && previewCurrent ? (
                <button
                  className={!dirty && kind === "preview" ? "primary" : ""}
                  disabled={dirty || pending}
                  onClick={() => {
                    actions.clearFeedback();
                    actions.submitTask.mutate(t);
                  }}
                >
                  确认并提交当前预览
                </button>
              ) : (
                <p>这份预览不可提交。</p>
              )}
            </section>
          )}
          {t.knowledge && (
            <section className="knowledge-result">
              <h3>知识回答与来源</h3>
              <AnswerView value={t.knowledge as Answer} inlineSources />
            </section>
          )}
          {t.outcome?.answer && <p>{t.outcome.answer}</p>}
          {t.can_run && kind === "continue" && (
            <button
              className="primary"
              disabled={dirty || pending}
              onClick={() => {
                actions.clearFeedback();
                actions.continueTask.mutate(t.id);
              }}
            >
              继续处理
            </button>
          )}
          {t.receipt && (
            <details>
              <summary>查看提交当时的回执</summary>
              <p>{label[t.receipt.ticket.status] || t.receipt.ticket.status}</p>
              <Parameters
                value={{
                  ...t.receipt.ticket.parameters,
                  asset_id: t.receipt.ticket.asset_id,
                }}
              />
              {t.preview && (
                <details>
                  <summary>查看提交时的完整预览</summary>
                  <pre>{JSON.stringify(t.preview.content, null, 2)}</pre>
                </details>
              )}
              <button
                onClick={() =>
                  cache.invalidateQueries({ queryKey: ["task", id] })
                }
              >
                重新读回当前结果
              </button>
            </details>
          )}
          {t.can_cancel && (
            <details className="advanced">
              <summary>其他操作</summary>
              <button
                disabled={pending}
                onClick={() => actions.cancelTask.mutate(t)}
              >
                结束这个事项
              </button>
            </details>
          )}
        </>
      )}
    </Drawer>
  );
}

function FieldEditor({
  task,
  onDirty,
  save,
  pending,
  savedRevision,
}: {
  task: Task;
  onDirty: (v: boolean) => void;
  save: (v: Record<string, unknown>, revision: number) => void;
  pending: boolean;
  savedRevision: number | null;
}) {
  // Only unsubmitted edits live here. The response/Query cache owns saved facts.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [baseRevision, setBaseRevision] = useState(task.revision);
  const dirty = Object.keys(draft).length > 0;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => {
    if (savedRevision != null) {
      setDraft({});
      setBaseRevision(savedRevision);
    }
  }, [savedRevision]);
  const conflict = dirty && baseRevision !== task.revision;
  const reset = () => {
    setDraft({});
    setBaseRevision(task.revision);
  };
  return (
    <section className="parameter-editor">
      <h3>当前任务参数</h3>
      <p className="muted">
        {dirty ? "未保存草稿" : "已保存参数"} · 版本{" "}
        {dirty ? baseRevision : task.revision}
      </p>
      {conflict && (
        <div className="notice" role="status">
          <p>服务器参数已更新，你的草稿保留。请比较最新值后重新编辑。</p>
          <details>
            <summary>查看服务器当前参数</summary>
            <Parameters
              value={Object.fromEntries(
                task.fields.map((f) => [f.name, f.value]),
              )}
            />
          </details>
          <button type="button" onClick={reset}>
            载入服务器最新值
          </button>
        </div>
      )}
      <form
        className="field-grid"
        onSubmit={(e) => {
          e.preventDefault();
          const changes: Record<string, unknown> = {};
          for (const f of task.fields)
            if (draft[f.name] !== undefined) {
              const value = draft[f.name];
              changes[f.name] = !value
                ? null
                : ["number", "integer"].includes(f.type)
                  ? Number(value)
                  : value;
            }
          save(changes, dirty ? baseRevision : task.revision);
        }}
      >
        {task.fields.map((f) => {
          const value = draft[f.name] ?? String(f.value ?? "");
          const change = (value: string) => {
            if (!dirty) setBaseRevision(task.revision);
            setDraft((old) => {
              const updated = { ...old, [f.name]: value };
              if (value === String(f.value ?? "")) delete updated[f.name];
              return updated;
            });
          };
          return (
            <label key={f.name}>
              {f.label}
              {f.required ? " *" : ""}
              {f.type === "impact" ? (
                <select
                  data-field-name={f.name}
                  value={value}
                  disabled={pending}
                  onChange={(e) => change(e.target.value)}
                >
                  <option value="">请选择</option>
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                </select>
              ) : (
                <input
                  data-field-name={f.name}
                  type={
                    f.type === "date"
                      ? "date"
                      : ["number", "integer"].includes(f.type)
                        ? "number"
                        : "text"
                  }
                  value={value}
                  disabled={pending}
                  onChange={(e) => change(e.target.value)}
                />
              )}
            </label>
          );
        })}
        <button
          className={dirty ? "primary" : ""}
          disabled={pending || !dirty}
          type="submit"
        >
          {["input", "choice"].includes(task.next_action?.kind || "")
            ? "保存参数"
            : "保存并生成预览"}
        </button>
      </form>
    </section>
  );
}
