from openai import AsyncOpenAI
import chromadb
from sentence_transformers import SentenceTransformer
from config import DEEPSEEK_API_KEY, CHROMA_PATH

# DeepSeek 客户端
client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 嵌入模型
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# 知识库 Chroma 客户端
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
knowledge_collection = chroma_client.get_or_create_collection(name="my_knowledge")