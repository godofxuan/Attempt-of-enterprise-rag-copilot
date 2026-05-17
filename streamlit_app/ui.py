import requests
import streamlit as st

API_BASE_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Enterprise RAG Copilot", layout="wide")
st.title("Enterprise RAG Copilot")

if "last_question" not in st.session_state:
    st.session_state.last_question = ""
if "last_answer" not in st.session_state:
    st.session_state.last_answer = ""
if "last_sources" not in st.session_state:
    st.session_state.last_sources = []

with st.sidebar:
    st.subheader("服务状态")

    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=3)
        response.raise_for_status()
        st.success("FastAPI 后端正常运行")
    except requests.RequestException:
        st.error("FastAPI 后端未运行")
        st.stop()

    st.markdown("---")
    st.subheader("知识库操作")

    if st.button("构建 / 重建知识库索引"):
        try:
            resp = requests.post(f"{API_BASE_URL}/ingest", timeout=180)
            resp.raise_for_status()
            data = resp.json()
            st.success(
                f"索引完成：文档 {data['document_count']} 个，chunks {data['chunk_count']} 个"
            )
        except requests.RequestException as exc:
            st.error(f"索引失败：{exc}")

st.subheader("提问")
question = st.text_area("请输入问题", value="退款期限是多少？", height=100)
top_k = st.number_input("检索返回的 top_k", min_value=1, max_value=10, value=3, step=1)

if st.button("Ask"):
    if not question.strip():
        st.warning("请输入问题后再提问。")
    else:
        try:
            resp = requests.post(
                f"{API_BASE_URL}/chat",
                json={"question": question, "top_k": int(top_k)},
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            st.session_state.last_question = question
            st.session_state.last_answer = data["answer"]
            st.session_state.last_sources = data["sources"]
        except requests.RequestException as exc:
            st.error(f"问答失败：{exc}")

if st.session_state.last_answer:
    st.markdown("## 回答")
    st.write(st.session_state.last_answer)

    st.markdown("## 来源")
    for i, item in enumerate(st.session_state.last_sources, start=1):
        with st.expander(f"[{i}] {item['source']} / {item['section']}"):
            st.write(f"chunk_id: {item['chunk_id']}")
            st.write(item["preview"])

    st.markdown("## 反馈")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("👍 有帮助"):
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/feedback",
                    json={
                        "question": st.session_state.last_question,
                        "answer": st.session_state.last_answer,
                        "helpful": True,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                st.success("已记录正向反馈")
            except requests.RequestException as exc:
                st.error(f"反馈提交失败：{exc}")

    with col2:
        if st.button("👎 没帮助"):
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/feedback",
                    json={
                        "question": st.session_state.last_question,
                        "answer": st.session_state.last_answer,
                        "helpful": False,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                st.success("已记录负向反馈")
            except requests.RequestException as exc:
                st.error(f"反馈提交失败：{exc}")