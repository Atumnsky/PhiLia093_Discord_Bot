import time
from typing import Optional
from core import embedding_model, knowledge_collection

def retrieve_knowledge(query: str, top_k: int = 3):
    if knowledge_collection.count() == 0:
        return [], []
    query_emb = embedding_model.encode([query]).tolist()
    results = knowledge_collection.query(query_embeddings=query_emb, n_results=top_k)
    # 安全访问
    documents = results.get('documents')
    metadatas = results.get('metadatas')
    if documents and documents[0]:
        return documents[0], metadatas[0] if metadatas else []
    return [], []

async def add_to_knowledge(content: str, source: str = "user", url: Optional[str] = None) -> bool:
    """添加知识到知识库"""
    try:
        chunks = [content.strip()]
        embeddings = embedding_model.encode(chunks).tolist()
        base_id = str(int(time.time()))
        ids = [f"{base_id}_0"]
        metadatas = [{"source": source}]  # type: ignore
        if url:
            metadatas[0]["url"] = url
        knowledge_collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas  # type: ignore
        )
        return True
    except Exception as e:
        print(f"Error adding to knowledge: {e}")
        return False