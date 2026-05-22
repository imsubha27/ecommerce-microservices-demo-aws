from dotenv import load_dotenv

import json, os
import boto3
from langchain_aws import BedrockEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass 



AWS_REGION     = os.environ.get("AWS_REGION", "ap-south-1")
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Local: always use localhost:5433
# Kubernetes: assembles from ASSISTANT_DB_* env vars
if "ASSISTANT_DB_HOST" in os.environ:
    db_user     = os.environ["ASSISTANT_DB_USER"]
    db_password = os.environ["ASSISTANT_DB_PASSWORD"]
    db_host     = os.environ["ASSISTANT_DB_HOST"]
    db_port     = os.environ.get("ASSISTANT_DB_PORT", "5432")
    db_name     = os.environ.get("ASSISTANT_DB_NAME", "vectordb")
    conn_str = f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
else:
    conn_str = "postgresql+psycopg://postgres:vectorpass@localhost:5433/vectordb"

print(f"Connecting to: {conn_str}")

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

embeddings = BedrockEmbeddings(
    client=bedrock,
    model_id=EMBED_MODEL_ID,
)

vectorstore = PGVector(
    embeddings=embeddings,
    collection_name=os.environ.get("COLLECTION_NAME", "products"),
    connection=conn_str,
)

script_dir = os.path.dirname(os.path.abspath(__file__))
products_path = "/shoppingassistantservice/products.json"

with open(products_path) as f:
    products = json.load(f)["products"]

docs = [
    Document(
        page_content=p["description"],
        metadata={
            "id":         p["id"],
            "name":       p["name"],
            "categories": str(p["categories"]),
            "picture":    p["picture"],
            "price":      p["priceUsd"]["units"],
        }
    )
    for p in products
]

vectorstore.add_documents(docs)
print(f"Seeded {len(docs)} products into vector DB")