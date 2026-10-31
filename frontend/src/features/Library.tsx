import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type Library, type JSONRecord, label } from "../api/client";
import { Drawer, ErrorNotice } from "../components/common";
export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["library"],
    queryFn: () => api<Library>("/api/library"),
    refetchInterval: (q) =>
      q.state.data?.jobs.some((j) => ["RUNNING", "QUEUED"].includes(j.status))
        ? 1500
        : false,
  });
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [doc, setDoc] = useState<string | null>(null);
  const [oldDoc, setOldDoc] = useState<string | null>(null);
  const [rename, setRename] = useState("");
  const kb = params.get("kb") || query.data?.bases[0]?.id;
  const current = query.data?.bases.find((b) => b.id === kb);
  const mutation = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => {
      await fn();
      await cache.invalidateQueries();
    },
  });
  const content = useQuery({
    queryKey: ["document", doc],
    enabled: !!doc,
    queryFn: () => api<JSONRecord>("/api/documents/" + doc),
  });
  const previous = useQuery({
    queryKey: ["document", oldDoc],
    enabled: !!oldDoc,
    queryFn: () => api<JSONRecord>("/api/documents/" + oldDoc),
  });
  const build = () => api("/api/library/" + kb + "/build", "POST", {});
  const docs = query.data?.documents.filter((d) => d.kb_id === kb) || [];
  return (
    <div>
      <div className="page-heading">
        <div>
          <p className="eyebrow">文档与来源</p>
          <h1>资料库</h1>
        </div>
        <select
          aria-label="查看资料库"
          value={kb || ""}
          onChange={(e) => setParams({ kb: e.target.value })}
        >
          {query.data?.bases.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </div>
      {query.error && <ErrorNotice error={query.error} />}{" "}
      {mutation.error && <ErrorNotice error={mutation.error} />}
      <form
        className="inline"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate(async () => {
            const b = await api<{ id: string }>("/api/library", "POST", {
              name,
            });
            setParams({ kb: b.id });
            setName("");
          });
        }}
      >
        <input
          aria-label="新资料库名称"
          placeholder="新资料库名称"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button disabled={mutation.isPending}>新建资料库</button>
      </form>
      {kb ? (
        <>
          <section className="library-upload card">
            <h2>{current?.name}</h2>
            <p className="muted">
              已发布索引：
              {query.data?.publications?.[kb]?.published_run_id || "尚未发布"} ·
              更新状态：
              {query.data?.publications?.[kb]?.update_state || "待处理"}
            </p>
            <p className="muted">
              查询使用已发布资料，新变更成功后切换；主动停用立即从新查询排除。更新失败可重试，旧版本来源保持可查看。
            </p>
            <p className="muted">
              支持 PDF、Word、Markdown
              与文本。导入后自动处理，可在下方查看实际状态。
            </p>
            <label className="file-picker">
              选择文档并导入
              <input
                aria-label="上传文档"
                type="file"
                accept=".md,.txt,.pdf,.docx"
                multiple
                disabled={mutation.isPending}
                onChange={(e) => {
                  const files = Array.from(e.target.files || []);
                  if (!files.length) return;
                  mutation.mutate(async () => {
                    const body = new FormData();
                    files.forEach((f) => body.append("files", f));
                    const result = await api<JSONRecord>(
                      "/api/library/" + kb + "/documents/batch",
                      "POST",
                      body,
                    );
                    if (!result.index_job && result.successful) await build();
                  });
                  e.target.value = "";
                }}
              />
            </label>
            <div className="actions">
              <button
                disabled={mutation.isPending}
                onClick={() =>
                  mutation.mutate(async () => {
                    await api("/api/library/" + kb + "/samples", "POST", {});
                    await build();
                  })
                }
              >
                导入本地演示制度
              </button>
              <button
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(build)}
              >
                重新处理索引
              </button>
            </div>
          </section>
          <div role="status">
            {query.data?.jobs
              .filter((j) => j.kb_id === kb)
              .slice(0, 3)
              .map((j) => (
                <p key={j.id}>
                  {label[j.status] || j.status}
                  {j.error && <span>：{j.error}</span>}
                </p>
              ))}
          </div>
          <div className="document-list">
            {docs.length ? (
              docs.map((d) => (
                <article className="document-row" key={d.id}>
                  <div>
                    <strong>{d.name}</strong>
                    <p className="muted">
                      v{d.version} · {d.active ? "当前版本" : "历史或停用版本"}{" "}
                      · {label[d.status] || d.status}
                    </p>
                    {d.error && (
                      <details>
                        <summary>处理失败原因</summary>
                        {d.error}
                      </details>
                    )}
                  </div>
                  <div className="actions">
                    <button
                      onClick={() => {
                        setDoc(d.id);
                        setRename(d.name);
                        setOldDoc(null);
                      }}
                    >
                      查看详情
                    </button>
                    <button
                      disabled={mutation.isPending}
                      onClick={() =>
                        mutation.mutate(async () => {
                          await api("/api/documents/" + d.id, "PATCH", {
                            active: !d.active,
                          });
                          await build();
                        })
                      }
                    >
                      {d.active ? "停用" : "恢复"}
                    </button>
                    {d.status === "FAILED" && (
                      <button
                        onClick={() =>
                          mutation.mutate(async () => {
                            await api(
                              "/api/documents/" + d.id + "/retry",
                              "POST",
                              {},
                            );
                            await build();
                          })
                        }
                      >
                        重试解析
                      </button>
                    )}
                  </div>
                </article>
              ))
            ) : (
              <p className="empty">还没有文档。上传文件或导入演示制度开始。</p>
            )}
          </div>
          <details className="advanced">
            <summary>高级：关联本地目录与增量同步</summary>
            <form
              className="inline"
              onSubmit={(e) => {
                e.preventDefault();
                mutation.mutate(async () => {
                  const r = await api<{ id: string }>(
                    "/api/library/directories",
                    "POST",
                    { kb_id: kb, path },
                  );
                  await api(
                    "/api/library/directories/" + r.id + "/sync",
                    "POST",
                    {},
                  );
                  await build();
                });
              }}
            >
              <input
                aria-label="本地文档目录"
                placeholder="明确选择的本地目录"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                required
              />
              <button>关联并同步</button>
            </form>
            {query.data?.directory_sources
              ?.filter((d) => d.kb_id === kb)
              .map((d) => (
                <p key={d.id}>
                  {d.path}
                  <button
                    onClick={() =>
                      mutation.mutate(async () => {
                        await api(
                          "/api/library/directories/" + d.id + "/sync",
                          "POST",
                          {},
                        );
                        await build();
                      })
                    }
                  >
                    增量同步
                  </button>
                </p>
              ))}
          </details>
        </>
      ) : (
        <p>先新建一个资料库。</p>
      )}
      <Drawer
        title="文档详情"
        open={!!doc}
        onClose={() => {
          setDoc(null);
          setOldDoc(null);
        }}
      >
        {content.error ? (
          <ErrorNotice error={content.error} />
        ) : (
          content.data && (
            <>
              <form
                className="inline"
                onSubmit={(e) => {
                  e.preventDefault();
                  mutation.mutate(() =>
                    api("/api/documents/" + doc, "PATCH", { name: rename }),
                  );
                }}
              >
                <input
                  aria-label="文档显示名称"
                  value={rename}
                  onChange={(e) => setRename(e.target.value)}
                />
                <button>保存名称</button>
              </form>
              <p>原文 v{content.data.version}</p>
              <pre>{content.data.parsed?.text || "没有可提取的文字"}</pre>
              {docs
                .filter(
                  (d) =>
                    d.source_key ===
                      docs.find((x) => x.id === doc)?.source_key &&
                    d.id !== doc,
                )
                .map((d) => (
                  <button key={d.id} onClick={() => setOldDoc(d.id)}>
                    对照 v{d.version}
                  </button>
                ))}
              {previous.data && (
                <section>
                  <h3>对照原文 v{previous.data.version}</h3>
                  <pre>{previous.data.parsed?.text}</pre>
                </section>
              )}
            </>
          )
        )}
      </Drawer>
    </div>
  );
}
