import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type TaskPage } from "../api/client";
import { ErrorNotice, Parameters } from "../components/common";
export function Requests({ openTask }: { openTask: (id: string) => void }) {
  const [filter, setFilter] = useState("");
  const q = useInfiniteQuery({
    queryKey: ["tasks", filter],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam, signal }) =>
      api<TaskPage>(
        "/api/product/tasks/page?" +
          new URLSearchParams({
            q: filter,
            limit: "20",
            ...(pageParam !== null ? { cursor: String(pageParam) } : {}),
          }),
        "GET",
        undefined,
        signal,
      ),
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = q.data?.pages.flatMap((page) => page.items) || [];
  return (
    <div>
      <p className="eyebrow">办理进展</p>
      <h1>我的事项</h1>
      <input
        type="search"
        aria-label="搜索事项"
        placeholder="搜索用途、日期或事项编号"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {q.error && <ErrorNotice error={q.error} />}{" "}
      {q.isPending ? (
        <p>正在读取…</p>
      ) : !rows.length ? (
        <p className="empty">
          {filter
            ? "没有匹配的事项。"
            : "还没有事项。在助理里选择借用电脑或 IT 报修。"}
        </p>
      ) : (
        ["待我处理", "处理中", "已结束"].map((group) => (
          <section key={group}>
            <h2>{group}</h2>
            <div className="request-grid">
              {rows
                .filter(
                  (t) =>
                    (t.closed
                      ? "已结束"
                      : t.current_ticket
                        ? "处理中"
                        : "待我处理") === group,
                )
                .map((t) => (
                  <article className="card" key={t.id}>
                    <h3>{t.title}</h3>
                    <p className="status-pill">{t.status_label}</p>
                    <Parameters
                      value={
                        t.current_ticket
                          ? {
                              loan_start:
                                t.current_ticket.parameters.loan_start,
                              loan_end: t.current_ticket.parameters.loan_end,
                              asset_id: t.current_ticket.asset_id,
                              purpose: t.current_ticket.parameters.purpose,
                            }
                          : Object.fromEntries(
                              t.fields
                                .filter(
                                  (f) =>
                                    f.value != null &&
                                    [
                                      "loan_start",
                                      "loan_end",
                                      "asset_id",
                                      "purpose",
                                      "description",
                                    ].includes(f.name),
                                )
                                .map((f) => [f.name, f.value]),
                            )
                      }
                    />
                    <p>{t.next_step}</p>
                    <div className="actions">
                      <button onClick={() => openTask(t.id)}>查看事项</button>
                      {t.conversation_id && (
                        <Link to={"/assistant?c=" + t.conversation_id}>
                          在助理中继续
                        </Link>
                      )}
                    </div>
                  </article>
                ))}
            </div>
          </section>
        ))
      )}
      {q.hasNextPage && (
        <button
          disabled={q.isFetchingNextPage}
          onClick={() => q.fetchNextPage()}
        >
          {q.isFetchingNextPage ? "正在读取…" : "更多事项"}
        </button>
      )}
    </div>
  );
}
