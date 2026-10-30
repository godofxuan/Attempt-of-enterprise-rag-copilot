import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { useQuery } from "@tanstack/react-query";
import { api, type Answer, type JSONRecord } from "../api/client";
import { Drawer, ErrorNotice } from "./common";
export function AnswerView({ value }: { value: Answer }) {
  const [source, setSource] = useState<JSONRecord | null>(null);
  const result = value.result;
  const detail = useQuery({
    queryKey: [
      "source",
      source?.doc_id,
      source?.index_run_id,
      source?.target_id,
    ],
    enabled: !!source,
    queryFn: () =>
      api<JSONRecord>(
        "/api/documents/" +
          source!.doc_id +
          "/excerpt?" +
          new URLSearchParams({
            index_run_id: source!.index_run_id,
            target_type: source!.target_type || "chunk",
            target_id: source!.target_id || source!.chunk_id,
          }),
      ),
  });
  return (
    <div className="answer">
      <ReactMarkdown>{result.answer}</ReactMarkdown>
      <p className="muted">
        {result.mode === "answered"
          ? "已交付有依据的回答"
          : result.mode === "partial"
            ? "部分内容仍缺依据"
            : "没有找到足够依据"}
      </p>
      {[...(result.warnings || []), ...(value.source_notices || [])].length >
        0 && (
        <details>
          <summary>回答范围与不足</summary>
          {[...(result.warnings || []), ...(value.source_notices || [])].map(
            (w, i) => (
              <p key={i}>{w}</p>
            ),
          )}
        </details>
      )}
      {(result.sources || []).length > 0 && (
        <div className="sources">
          {(result.sources || []).map((s, i) => (
            <button key={s.chunk_id} onClick={() => setSource(s)}>
              {i + 1}. {s.title || s.source_path}
            </button>
          ))}
        </div>
      )}
      <Drawer title="引用原文" open={!!source} onClose={() => setSource(null)}>
        {detail.isPending ? (
          <p>正在打开原版本…</p>
        ) : detail.error ? (
          <ErrorNotice error={detail.error} />
        ) : (
          <>
            <h3>
              {detail.data?.name} · v{detail.data?.version}
            </h3>
            <p className="muted">
              {detail.data?.active ? "当前导入版本" : "回答当时的历史版本"}
            </p>
            <p>
              {(detail.data?.source_spans || [])
                .map(
                  (s: JSONRecord) =>
                    `${s.locator_kind} ${s.locator_start} ${s.section_path.join(" / ")}`,
                )
                .join("；")}
            </p>
            <pre>{detail.data?.text || detail.data?.parsed?.text}</pre>
          </>
        )}
      </Drawer>
    </div>
  );
}
