import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "./client";
import { refreshRunScope } from "./taskActions";
export function useRun(runId: string | null) {
  const cache = useQueryClient();
  const [progress, setProgress] = useState("正在准备");
  useEffect(() => {
    setProgress("正在准备");
    if (!runId) return;
    let disposed = false,
      source: EventSource | undefined,
      reconnect: ReturnType<typeof setTimeout> | undefined;
    let cursor = Number(sessionStorage.getItem("esa-cursor-" + runId) || 0);
    let done = false;
    let active: Run | undefined;
    const finish = () => {
      if (disposed || done) return;
      done = true;
      source?.close();
      if (active) refreshRunScope(cache, active);
    };
    const connect = async () => {
      try {
        const run = await api<Run>("/api/runs/" + runId);
        active = run;
        if (disposed) return;
        if (!["queued", "running"].includes(run.status)) {
          finish();
          return;
        }
        source = new EventSource(
          "/api/runs/" + runId + "/events?after_seq=" + cursor,
        );
        source.addEventListener("progress", (event) => {
          if (disposed) return;
          const row = JSON.parse((event as MessageEvent).data);
          cursor = row.seq;
          sessionStorage.setItem("esa-cursor-" + runId, String(cursor));
          if (
            [
              "model_decision",
              "tool_result",
              "preview_ready",
              "field_changes",
            ].includes(row.kind)
          )
            cache.invalidateQueries({ queryKey: ["run-events", runId] });
          setProgress(
            row.kind === "progress" && row.data?.tool
              ? "执行工具：" + row.data.tool
              : row.kind === "queued"
                ? "等待处理"
                : row.kind === "running"
                  ? "正在检索资料或处理事项"
                  : "正在读取结果",
          );
          if (
            ["finished", "failed", "cancelled", "interrupted"].includes(
              row.kind,
            )
          )
            finish();
        });
        source.onerror = () => {
          source?.close();
          if (!disposed && !done) reconnect = setTimeout(connect, 1200);
        };
      } catch {
        if (!disposed) reconnect = setTimeout(connect, 1500);
      }
    };
    connect();
    return () => {
      disposed = true;
      source?.close();
      clearTimeout(reconnect);
    };
  }, [runId, cache]);
  return progress;
}
