import json, os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document

conn_str = "postgresql+psycopg://postgres:vectorpass@localhost:5433/vectordb"

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.environ["GOOGLE_API_KEY"]
)

vectorstore = PGVector(
    embeddings=embeddings,
    collection_name="products",
    connection=conn_str,
)

with open("src/productcatalogservice/products.json") as f:
    products = json.load(f)["products"]

docs = [
    Document(
        page_content=p["description"],
        metadata={"id": p["id"], "name": p["name"], "categories": str(p["categories"])}
    )
    for p in products
]

vectorstore.add_documents(docs)
print(f"Seeded {len(docs)} products into vector DB")