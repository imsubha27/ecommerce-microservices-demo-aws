import json, os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document

# Build connection string from env vars (same pattern as the shopping assistant)
db_host     = os.environ["ASSISTANT_DB_HOST"]
db_port     = os.environ.get("ASSISTANT_DB_PORT", "5432")
db_name     = os.environ.get("ASSISTANT_DB_NAME", "vectordb")
db_user     = os.environ["ASSISTANT_DB_USER"]
db_password = os.environ["ASSISTANT_DB_PASSWORD"]

conn_str = f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.environ["GOOGLE_API_KEY"]
)

vectorstore = PGVector(
    embeddings=embeddings,
    collection_name=os.environ.get("COLLECTION_NAME", "products"),
    connection=conn_str,
)

# __file__ resolves to wherever the script is inside the container
script_dir = os.path.dirname(os.path.abspath(__file__))
products_path = os.path.join(script_dir, "products.json")

with open(products_path) as f:
    products = json.load(f)["products"]

docs = [
    Document(
        page_content=p["description"],
        metadata={"id": p["id"], "name": p["name"], "categories": str(p["categories"]), "picture": p["picture"], "price": p["priceUsd"]["units"]}
    )
    for p in products
]

vectorstore.add_documents(docs)
print(f"Seeded {len(docs)} products into vector DB")