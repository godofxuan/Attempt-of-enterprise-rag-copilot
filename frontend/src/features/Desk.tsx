import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type JSONRecord, label } from "../api/client";
import { Drawer, ErrorNotice, Parameters } from "../components/common";
export function Desk() {
  const cache = useQueryClient();
  const q = useQuery({
    queryKey: ["desk"],
    queryFn: () =>
      api<{ tickets: JSONRecord[]; reservations: JSONRecord[] }>(
        "/api/service-desk",
      ),
  });
  const [selected, setSelected] = useState<JSONRecord | null>(null);
  const [note, setNote] = useState("");
  const [end, setEnd] = useState("");
  const [preview, setPreview] = useState<JSONRecord | null>(null);
  const action = useMutation({
    mutationFn: async (commit: boolean) => {
      if (commit) {
        await api("/api/service-desk/commit", "POST", {
          proposal_id: preview!.proposal_id,
          content_digest: preview!.content_digest,
          accepted: true,
        });
        setSelected(null);
        setPreview(null);
        await cache.invalidateQueries();
      } else
        setPreview(
          await api("/api/service-desk/proposals", "POST", {
            kind: selected!.kind,
            ticket_id: selected!.ticket.ticket_id,
            action: selected!.action,
            expected_version: selected!.ticket.version,
            note,
            ...(selected!.action === "extend" ? { loan_end: end } : {}),
          }),
        );
    },
  });
  return (
    <div>
      <p className="eyebrow">次级工具</p>
      <h1>演示服务台</h1>
      <p className="muted">仅处理本地合成 TEST 工单，不连接企业审批系统。</p>
      {q.error && <ErrorNotice error={q.error} />}
      <div className="request-grid">
        {q.data?.tickets.map((row) => (
          <article
            className="card"
            aria-label={"工单 " + row.ticket.ticket_id}
            key={row.ticket.ticket_id}
          >
            <h3>{row.kind === "loan" ? "电脑借用" : "IT 报修"}</h3>
            <p className="muted path">编号：{row.ticket.ticket_id}</p>
            <p>{label[row.ticket.status] || row.notice}</p>
            <Parameters
              value={{
                ...row.ticket.parameters,
                asset_id: row.ticket.asset_id,
              }}
            />
            <p>{row.notice}</p>
            <div className="actions">
              {row.actions.map((a: JSONRecord) => (
                <button
                  key={a.name}
                  onClick={() => {
                    setSelected({
                      ...row,
                      action: a.name,
                      action_label: a.label,
                    });
                    setNote("");
                    setEnd("");
                    setPreview(null);
                  }}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </article>
        ))}
      </div>
      <details>
        <summary>查看日期排期</summary>
        {q.data?.reservations.map((r) => (
          <p key={r.ticket_id}>
            {r.asset_id} · {r.start_date} 至 {r.end_exclusive}（不含结束边界）·{" "}
            {r.active ? "预留中" : "已释放"}
          </p>
        ))}
      </details>
      <Drawer
        title={selected?.action_label || "处理动作"}
        open={!!selected}
        onClose={() => {
          setSelected(null);
          setPreview(null);
        }}
      >
        {action.error && <ErrorNotice error={action.error} />}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action.mutate(false);
          }}
        >
          <label>
            处理说明
            <input
              required
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setPreview(null);
              }}
            />
          </label>
          {selected?.action === "extend" && (
            <label>
              新的结束日期
              <input
                type="date"
                required
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setPreview(null);
                }}
              />
            </label>
          )}
          <button disabled={action.isPending}>查看本次动作预览</button>
        </form>
        {preview && (
          <section className="card">
            <h3>确认本次处理</h3>
            <p>
              {selected?.action_label} · {note}
            </p>
            <Parameters value={preview.content.parameters} />
            <details>
              <summary>完整处理内容</summary>
              <pre>{JSON.stringify(preview.content, null, 2)}</pre>
            </details>
            <button
              className="primary"
              disabled={action.isPending}
              onClick={() => action.mutate(true)}
            >
              确认办理此动作
            </button>
          </section>
        )}
      </Drawer>
    </div>
  );
}
