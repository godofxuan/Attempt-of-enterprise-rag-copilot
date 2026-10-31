import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Task, type JSONRecord, label } from "../api/client";
import { Drawer, ErrorNotice, Parameters } from "../components/common";
import { AnswerView } from "../components/AnswerView";
import type { Answer, Run } from "../api/client";
export function TaskDetail({
  id,
  onClose,
  onRun,
}: {
  id: string | null;
  onClose: () => void;
  onRun: (run: Run, conversationId?: string | null) => void;
}) {
  const cache = useQueryClient();
  const [dirty, setDirty] = useState(false);
  const task = useQuery({
    queryKey: ["task", id],
    enabled: !!id,
    queryFn: () => api<Task>("/api/product/tasks/" + id),
  });
  const choices = useQuery({
    queryKey: ["alternatives", id, task.data?.revision],
    enabled: !!id && !!task.data?.can_edit,
    queryFn: () =>
      api<JSONRecord[]>("/api/product/tasks/" + id + "/alternatives"),
  });
  useEffect(() => setDirty(false), [id, task.data?.revision]);
  const action = useMutation({
    mutationFn: async ({
      path,
      body,
      method = "POST",
      continueTask = false,
      prepareAfter = false,
    }: {
      path: string;
      body?: unknown;
      method?: string;
      continueTask?: boolean;
      prepareAfter?: boolean;
    }) => {
      let value = await api<JSONRecord>(path, method, body);
      if (prepareAfter)
        value = await api<JSONRecord>(`/api/product/tasks/${id}/prepare`, "POST", {expected_facts_revision: value.facts_revision});
      if (continueTask)
        value = await api<JSONRecord>("/api/tasks/" + id + "/runs", "POST", {});
      await cache.invalidateQueries();
      if (value.id && ["queued", "running"].includes(value.status))
        onRun(value as Run, task.data?.conversation_id);
      return value;
    },
  });
  const t = task.data;
  return (
    <Drawer title="事项详情" open={!!id} onClose={onClose}>
      {task.isPending ? (
        <p>正在读取事项…</p>
      ) : task.error ? (
        <ErrorNotice error={task.error} />
      ) : (
        t && (
          <>
            <h3>{t.title}</h3>
            <p className="status-pill">{t.status_label}</p>
            <p>{t.next_step}</p>
            {t.turn_delivery?.status === "partial" && (
              <section className="card" role="status">
                <strong>本回合部分交付</strong>
                <p>{t.preview ? "当前预览已保留。" : "当前参数已保留。"} {t.turn_delivery.next_action}</p>
                {t.turn_delivery.pending?.includes("knowledge") && (
                  <button disabled={action.isPending} onClick={() => action.mutate({
                    path: `/api/product/conversations/${t.conversation_id}/turns/${t.turn_delivery!.turn_id}/retry`,
                    body: {},
                  })}>重试解释</button>
                )}
              </section>
            )}
            <p className="muted">
              {t.receipt
                ? "已提交。当前业务状态与提交当时的回执分别展示。"
                : t.ceiling === "READ_ONLY"
                  ? "当前只读，不准备申请"
                  : t.ceiling === "PREVIEW_ONLY"
                    ? "当前只生成预览，绝不提交"
                    : "提交前由你确认当前完整预览"}
            </p>
            {action.error && <ErrorNotice error={action.error} />}
            {t.pending_update && (
              <section className="card" role="status">
                <h3>上次消息尚未处理完</h3>
                <p>{t.pending_update.text}</p>
                <p className="muted">
                  已应用的参数保留。可重试原消息，或核对下方参数后继续当前范围；这不是提交确认。
                </p>
                {t.last_error && <p>原因：{t.last_error}</p>}
                <button
                  onClick={() =>
                    action.mutate({
                      path:
                        "/api/product/conversations/" +
                        t.conversation_id +
                        "/turns/" +
                        t.pending_update!.id +
                        "/retry",
                      body: {},
                    })
                  }
                >
                  重试原消息
                </button>
                <button
                  onClick={() =>
                    action.mutate({
                      path: "/api/tasks/" + t.id + "/resolve-update",
                      body: {
                        execution_ceiling: t.ceiling,
                        expected_facts_revision: t.revision,
                        reviewed: true,
                      },
                      continueTask: true,
                    })
                  }
                >
                  已核对参数，保留当前范围并继续
                </button>
              </section>
            )}
            {t.current_ticket && (
              <section className="card">
                <h3>当前办理结果</h3>
                <p>{label[t.current_ticket.status] || t.status_label}</p>
                <Parameters
                  value={{
                    ...t.current_ticket.parameters,
                    asset_id: t.current_ticket.asset_id,
                  }}
                />
                <p>{t.current_ticket.next_step}</p>
              </section>
            )}
            {t.can_edit ? (
              <FieldEditor
                key={t.id + ":" + t.revision}
                task={t}
                onDirty={setDirty}
                save={(changes) =>
                  action.mutate({
                    path: "/api/tasks/" + t.id + "/facts",
                    method: "PATCH",
                    prepareAfter: true,
                    body: { changes, expected_facts_revision: t.revision },
                  })
                }
                pending={action.isPending}
              />
            ) : !t.receipt ? (
              <Parameters
                value={Object.fromEntries(
                  t.fields.map((f) => [f.name, f.value]),
                )}
              />
            ) : null}
            {t.can_edit && (
              <details>
                <summary>可选设备与日期</summary>
                {choices.isPending ? (
                  <p>读取实际资源…</p>
                ) : choices.error ? (
                  <ErrorNotice error={choices.error} />
                ) : !choices.data?.length ? (
                  <p>当前条件下没有可选资源。可明确修改日期或要求后再查询。</p>
                ) : (
                  choices.data?.map((c, i) => (
                    <div
                      className="resource card"
                      key={c.asset_id + ":" + c.date_shift_days}
                    >
                      <strong>
                        {i + 1}. {c.asset_id}
                      </strong>
                      <Parameters value={{ ...c.details, ...c.parameters }} />
                      {c.notice && <p>{c.notice}</p>}
                      <button
                        disabled={dirty || action.isPending}
                        onClick={() =>
                          action.mutate({
                            path: "/api/tasks/" + t.id + "/asset",
                            prepareAfter: true,
                            body: {
                              asset_id: c.asset_id,
                              date_shift_days: c.date_shift_days || 0,
                              expected_facts_revision: t.revision,
                            },
                          })
                        }
                      >
                        选择并生成预览
                      </button>
                    </div>
                  ))
                )}
              </details>
            )}
            {dirty && (
              <p role="status">请先保存并继续修改，再运行或确认预览。</p>
            )}
            {t.can_edit && !dirty && !t.preview && !t.receipt && (
              <button disabled={action.isPending} onClick={() => action.mutate({
                path: `/api/product/tasks/${t.id}/prepare`,
                body: {expected_facts_revision: t.revision},
              })}>生成当前预览</button>
            )}
            {t.preview && !t.receipt && (
              <section className="card preview">
                <h3>当前完整预览</h3>
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
                <p>依据规则：{t.preview.content.rule_version}</p>
                <details>
                  <summary>核对完整预览内容</summary>
                  <pre>{JSON.stringify(t.preview.content, null, 2)}</pre>
                </details>
                {t.can_submit ? (
                  <button
                    className="primary"
                    disabled={dirty || action.isPending}
                    onClick={() =>
                      action.mutate({
                        path: "/api/tasks/" + t.id + "/submit",
                        body: {
                          proposal_id: t.preview!.proposal_id,
                          content_digest: t.preview!.content_digest,
                          expected_facts_revision: t.revision,
                          accepted: true,
                        },
                      })
                    }
                  >
                    确认并提交当前预览
                  </button>
                ) : (
                  <p>这份预览不可提交。</p>
                )}
              </section>
            )}
            {t.knowledge && <AnswerView value={t.knowledge as Answer} />}
            {t.outcome?.answer && <p>{t.outcome.answer}</p>}
            <div className="actions">
              {t.can_run && (
                <button
                  disabled={dirty || action.isPending}
                  onClick={() =>
                    action.mutate({
                      path: "/api/tasks/" + t.id + "/runs",
                      body: {},
                    })
                  }
                >
                  继续处理
                </button>
              )}
              {t.can_cancel && (
                <button
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      path: "/api/tasks/" + t.id + "/cancel",
                      body: {},
                    })
                  }
                >
                  结束这个事项
                </button>
              )}
            </div>
            {t.receipt && (
              <details>
                <summary>查看提交当时的回执</summary>
                <p>
                  {label[t.receipt.ticket?.status] || t.receipt.ticket?.status}
                </p>
                <Parameters
                  value={{
                    ...t.receipt.ticket?.parameters,
                    asset_id: t.receipt.ticket?.asset_id,
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
          </>
        )
      )}
    </Drawer>
  );
}
function FieldEditor({
  task,
  onDirty,
  save,
  pending,
}: {
  task: Task;
  onDirty: (v: boolean) => void;
  save: (v: Record<string, unknown>) => void;
  pending: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(task.fields.map((f) => [f.name, String(f.value ?? "")])),
  );
  return (
    <form
      className="field-grid"
      onSubmit={(e) => {
        e.preventDefault();
        const changes: Record<string, unknown> = {};
        for (const f of task.fields) {
          const value = values[f.name] || "";
          if (value !== String(f.value ?? ""))
            changes[f.name] = !value
              ? null
              : ["number", "integer"].includes(f.type)
                ? Number(value)
                : value;
        }
        save(changes);
      }}
    >
      {task.fields.map((f) => (
        <label key={f.name}>
          {f.label}
          {f.required ? " *" : ""}
          {f.type === "impact" ? (
            <select
              value={values[f.name]}
              onChange={(e) => {
                setValues({ ...values, [f.name]: e.target.value });
                onDirty(true);
              }}
            >
              <option value="">请选择</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          ) : (
            <input
              type={
                f.type === "date"
                  ? "date"
                  : ["number", "integer"].includes(f.type)
                    ? "number"
                    : "text"
              }
              value={values[f.name]}
              onChange={(e) => {
                setValues({ ...values, [f.name]: e.target.value });
                onDirty(true);
              }}
            />
          )}
        </label>
      ))}
      <button disabled={pending} type="submit">
        保存并生成预览
      </button>
    </form>
  );
}
