#!/usr/bin/python
import os, boto3
from urllib.parse import unquote
from langchain_aws import BedrockEmbeddings, ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_postgres import PGVector
from flask import Flask, request

# ── AWS / DB config ───────────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    db_user     = os.environ["ASSISTANT_DB_USER"]
    db_password = os.environ["ASSISTANT_DB_PASSWORD"]
    db_host     = os.environ["ASSISTANT_DB_HOST"]
    db_port     = os.environ.get("ASSISTANT_DB_PORT", "5432")
    db_name     = os.environ["ASSISTANT_DB_NAME"]
    DATABASE_URL = (
        f"postgresql+psycopg://{db_user}:{db_password}"
        f"@{db_host}:{db_port}/{db_name}"
    )

COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "products")

# Quick-reply suggestions shown after each response
QUICK_REPLIES = [
    "Show me something for my kitchen",
    "I need a gift under $50",
    "What's good for outdoor use?",
    "Show me accessories",
    "Something stylish for my home",
    "What do you recommend for travel?",
]


def create_app():
    app = Flask(__name__)

    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    embeddings = BedrockEmbeddings(
        client=bedrock_client,
        model_id="amazon.titan-embed-text-v2:0",
    )

    vectorstore = PGVector(
        embeddings=embeddings,
        collection_name=COLLECTION_NAME,
        connection=DATABASE_URL,
    )

    # Claude 3 Haiku for recommendations (fast + cheap)
    llm = ChatBedrock(
        client=bedrock_client,
        model_id="apac.amazon.nova-lite-v1:0",
        model_kwargs={"max_tokens": 1024},
    )

    # Claude 3.5 Sonnet for vision
    llm_vision = ChatBedrock(
        client=bedrock_client,
        model_id="apac.amazon.nova-pro-v1:0",
        model_kwargs={"max_tokens": 1024},
    )

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    @app.route("/", methods=["POST"])
    def talkToBedrock():
        print("Beginning RAG call")
        body      = request.json
        prompt    = unquote(body["message"])
        image_url = body.get("image", "")

        # ── Conversation history ──────────────────────────────────────────────
        # Frontend sends history as [{role, content}, ...] so the LLM remembers
        # previous turns. Falls back to empty list if not provided.
        raw_history = body.get("history", [])
        history_messages = []
        for turn in raw_history:
            if turn["role"] == "user":
                history_messages.append(HumanMessage(content=turn["content"]))
            elif turn["role"] == "assistant":
                history_messages.append(AIMessage(content=turn["content"]))

        # Step 1 — room description via Claude 3.5 Sonnet vision
        if image_url:
            if image_url.startswith("data:"):
                header, b64data = image_url.split(",", 1)
                media_type = header.split(":")[1].split(";")[0]
            else:
                b64data    = image_url
                media_type = "image/jpeg"

            vision_content = [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": media_type,
                        "data":       b64data,
                    },
                },
                {
                    "type": "text",
                    "text": "You are a professional interior designer. Give a detailed description of the style of the room in this image.",
                },
            ]
            description = llm_vision.invoke(
                [HumanMessage(content=vision_content)]
            ).content
        else:
            description = "A modern, neutral living room with clean lines and a calm atmosphere."

        print(f"Room description: {description}")

        # Step 2 — vector similarity search
        docs = vectorstore.similarity_search(
            f"User request: {prompt}. Room style: {description}", k=4
        )
        print(f"Retrieved {len(docs)} docs")

        relevant = ", ".join(
            f"id={d.metadata['id']} name={d.metadata['name']} "
            f"description={d.page_content} categories={d.metadata['categories']}"
            for d in docs
        )

        # Step 3 — multi-turn recommendation via Claude 3 Haiku
        system = SystemMessage(content=(
            "You are a friendly, knowledgeable shopping assistant for Online Boutique. "
            "You help customers find products that match their style, needs, and budget. "
            "Keep responses concise and conversational. "
            "When recommending products, briefly explain why each fits the customer's request. "
            "Always end your response with exactly 3 DIFFERENT product IDs on the last line "
            "in this exact format with no extra text after: [id1], [id2], [id3]. "
            "Never repeat the same ID. Only use IDs from the provided product list."
        ))

        # Build the current turn message with context injected
        current_message = HumanMessage(content=(
            f"Available products: {relevant}\n"
            f"Room/style context: {description}\n"
            f"Customer message: {prompt}"
        ))

        # Full message chain: system + history + current
        messages = [system] + history_messages + [current_message]

        result = llm.invoke(messages)
        print(f"Response: {result.content}")

        # Pick 3 quick replies that weren't the current prompt
        import random
        suggestions = [q for q in QUICK_REPLIES if q.lower() != prompt.lower()]
        random.shuffle(suggestions)
        quick_replies = suggestions[:3]

        return {
            "content":      result.content,
            "quick_replies": quick_replies,
        }

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    create_app().run(host="0.0.0.0", port=port)