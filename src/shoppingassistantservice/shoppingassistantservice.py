#!/usr/bin/python
import os
from urllib.parse import unquote
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector
from flask import Flask, request

DATABASE_URL    = os.environ["DATABASE_URL"]
COLLECTION_NAME = os.environ["COLLECTION_NAME"]
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
GOOGLE_API_KEY  = os.environ["GOOGLE_API_KEY"]

# Free Google embeddings
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=GOOGLE_API_KEY
)

vectorstore = PGVector(
    embeddings=embeddings,
    collection_name=COLLECTION_NAME,
    connection=DATABASE_URL,
)

def create_app():
    app = Flask(__name__)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    @app.route("/", methods=["POST"])
    def talkToGroq():
        print("Beginning RAG call")
        prompt = unquote(request.json["message"])
        image_url = request.json.get("image", "")

        # Step 1 — room description via Llama vision (Groq)
        llm_vision = ChatGroq(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            api_key=GROQ_API_KEY,
        )

        if image_url:
            vision_content = [
                {"type": "text", "text": "You are a professional interior designer. Give a detailed description of the style of the room in this image."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        else:
            vision_content = [
                {"type": "text", "text": "Describe a modern, neutral living room style."}
            ]

        description = llm_vision.invoke(
            [HumanMessage(content=vision_content)]
        ).content
        print(f"Room description: {description}")

        # Step 2 — vector similarity search
        docs = vectorstore.similarity_search(
            f"User request: {prompt}. Room style: {description}", k=4
        )
        print(f"Retrieved {len(docs)} docs")
        relevant = ", ".join(str(d.to_json()) for d in docs)

        # Step 3 — final recommendation via Llama 70b (Groq)
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=GROQ_API_KEY,
        )
        design_prompt = (
            f"You are an interior designer for Online Boutique. "
            f"Room description: {description}. "
            f"Relevant products: {relevant}. "
            f"Customer request: {prompt}. "
            f"Briefly describe the room style, then recommend the most relevant products. "
            f"End with the top 3 product IDs: [<id1>], [<id2>], [<id3>]"
        )
        result = llm.invoke(design_prompt)
        print(f"Response: {result.content}")
        return {"content": result.content}

    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    create_app().run(host="0.0.0.0", port=port)