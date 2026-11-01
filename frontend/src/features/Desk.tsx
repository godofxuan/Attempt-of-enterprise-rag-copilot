import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type JSONRecord, label } from "../api/client";
import { Drawer, ErrorNotice, Parameters } from "../components/common";
import { refreshTaskScope } from "../api/taskActions";
export function Desk() {
  const cache = useQueryClient();
  const q = useQuery({
    queryKey: ["desk"],
    queryFn: () =>
      api<{ tickets: JSONRecord[]; reservations: JSONRecord[] }>(
        "/api/service-desk",
      ),
  });
  const [search, setSearch] = useState("");
  const tickets = q.data?.tickets || [];
  const term = search.trim().toLocaleLowerCase();
  const visibleTickets = tickets.filter((row) =>
    [
      row.ticket.ticket_id,
      row.ticket.asset_id,
      row.kind === "loan" ? "电脑借用" : "IT 报修",
      row.ticket.status,
      label[row.ticket.status],
      ...Object.values(row.ticket.parameters || {}),
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(term),
  );
  const [selected, setSelected] = useState<JSONRecord | null>(null);
  const [note, setNote] = useState("");
  const [end, setEnd] = useState("");
  const [preview, setPreview] = useState<JSONRecord | null>(null);
  const selectionKey = selected
    ? `${selected.kind}:${selected.ticket.ticket_id}:${selected.action}`
    : null;
  const currentSelection = useRef(selectionKey);
  currentSelection.current = selectionKey;
  const prepareAction = useMutation({
    mutationFn: ({
      row,
      note,
      end,
      key,
    }: {
      row: JSONRecord;
      note: string;
      end: string;
      key: string;
    }) =>
      api<JSONRecord>("/api/service-desk/proposals", "POST", {
        kind: row.kind,
        ticket_id: row.ticket.ticket_id,
        action: row.action,
        expected_version: row.ticket.version,
        note,
        ...(row.action === "extend" ? { loan_end: end } : {}),
      }).then((value) => ({ value, key })),
    onSuccess: ({ value, key }) => {
      if (currentSelection.current === key) setPreview(value);
    },
  });
  const commitAction = useMutation({
    mutationFn: ({
      proposal,
    }: {
      proposal: JSONRecord;
      row: JSONRecord;
      key: string;
    }) =>
      api("/api/service-desk/commit", "POST", {
        proposal_id: proposal.proposal_id,
        content_digest: proposal.content_digest,
        accepted: true,
      }),
    onSuccess: (_, request) => {
      if (currentSelection.current === request.key) {
        setSelected(null);
        setPreview(null);
      }
      void cache.invalidateQueries({ queryKey: ["desk"] });
      void refreshTaskScope(cache, request.row.ticket.task_id);
    },
  });
  const busy = prepareAction.isPending || commitAction.isPending;
  return (
    <div>
      <p className="eyebrow">次级工具</p>
      <h1>演示服务台</h1>
      <p className="muted">仅处理本地合成 TEST 工单，不连接企业审批系统。</p>
      <input
        type="search"
        aria-label="搜索工单"
        placeholder="搜索工单号、设备、用途、故障描述或状态"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {search && <button onClick={() => setSearch("")}>清空搜索</button>}
      {q.error && <ErrorNotice error={q.error} />}
      {q.isPending ? (
        <p>正在读取工单…</p>
      ) : q.data ? (
        <p className="muted" role="status">
          显示 {visibleTickets.length} / {tickets.length} 张工单
        </p>
      ) : null}
      {q.data && !visibleTickets.length && (
        <p className="empty">
          {term ? "没有匹配的工单，请缩短关键词或清空搜索。" : "还没有工单。"}
        </p>
      )}
      <div className="request-grid">
        {visibleTickets.map((row) => (
          <article
            className="card"
            aria-label={"工单 " + row.ticket.ticket_id}
            key={row.ticket.ticket_id}
          >
            <h3>{row.kind === "loan" ? "电脑借用" : "IT 报修"}</h3>
            <details>
              <summary>工单详情</summary>
              <p className="path">编号：{row.ticket.ticket_id}</p>
            </details>
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
                    prepareAction.reset();
                    commitAction.reset();
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
        {(prepareAction.error || commitAction.error) && (
          <ErrorNotice error={prepareAction.error || commitAction.error} />
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (selected && selectionKey)
              prepareAction.mutate({
                row: selected,
                note,
                end,
                key: selectionKey,
              });
          }}
        >
          <label>
            处理说明
            <input
              required
              disabled={busy}
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
                disabled={busy}
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setPreview(null);
                }}
              />
            </label>
          )}
          <button className={!preview ? "primary" : ""} disabled={busy}>
            查看本次动作预览
          </button>
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
              disabled={busy}
              onClick={() =>
                selected &&
                preview &&
                selectionKey &&
                commitAction.mutate({
                  row: selected,
                  proposal: preview,
                  key: selectionKey,
                })
              }
            >
              确认办理此动作
            </button>
          </section>
        )}
      </Drawer>
    </div>
  );
}
