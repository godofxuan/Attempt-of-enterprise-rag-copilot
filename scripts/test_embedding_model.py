from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

response = client.embeddings.create(
    model="bge-m3",
    input="客户可以在14天内申请退款。",
)

embedding = response.data[0].embedding

print("向量长度：", len(embedding))
print("前10个数：", embedding[:10])