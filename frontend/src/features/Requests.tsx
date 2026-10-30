import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Task } from "../api/client";
import { ErrorNotice, Parameters } from "../components/common";
export function Requests({ openTask }: { openTask: (id: string) => void }) {
  const q = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<Task[]>("/api/product/tasks"),
  });
  const ended = new Set(["CANCELLED", "CLOSED", "RETURNED", "REJECTED"]);
  return (
    <div>
      <p className="eyebrow">办理进展</p>
      <h1>我的事项</h1>
      {q.error && <ErrorNotice error={q.error} />}{" "}
      {q.isPending ? (
        <p>正在读取…</p>
      ) : !q.data?.length ? (
        <p className="empty">还没有事项。在助理里选择借用电脑或 IT 报修。</p>
      ) : (
        ["待我处理", "处理中", "已结束"].map((group) => (
          <section key={group}>
            <h2>{group}</h2>
            <div className="request-grid">
              {q.data
                ?.filter(
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
                        t.current_ticket?.parameters ||
                        Object.fromEntries(
                          t.fields
                            .filter((f) => f.value != null)
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
    </div>
  );
}
