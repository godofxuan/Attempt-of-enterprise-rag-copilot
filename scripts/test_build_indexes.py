from app.retriever import build_indexes

doc_count, chunk_count = build_indexes()

print("文档数量：", doc_count)
print("chunk 数量：", chunk_count)
print("索引构建完成。")