import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { components } from "../api/generated";
import { ErrorNotice } from "./common";
type Row = components["schemas"]["RunEventView"];
export function RunTrace({ id }: { id?: string | null }) {
  const query = useQuery({
    queryKey: ["run-events", id],
    enabled: !!id,
    queryFn: () => api<Row[]>("/api/product/runs/" + id + "/events"),
  });
  if (!id) return null;
  return (
    <details className="run-trace">
      <summary>查看本次执行记录</summary>
      <p className="muted">
        模型提出调用，程序执行工具。此处显示真实记录；执行结束不等于审批完成。
      </p>
      {query.error && <ErrorNotice error={query.error} />}
      <ol>
        {query.data?.map((row, index) => (
          <li key={row.seq + ":" + index}>
            <strong>
              {{ model: "模型", tool: "工具", program: "程序" }[row.actor]} ·{" "}
              {row.action}
            </strong>
            <span className="muted"> · {row.status}</span>
            <p>{row.observation}</p>
            {row.details && (
              <details>
                <summary>结果详情</summary>
                <pre>{JSON.stringify(row.details, null, 2)}</pre>
              </details>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}
