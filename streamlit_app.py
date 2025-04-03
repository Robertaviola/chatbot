import os
import asyncio
import streamlit as st
from google.cloud import storage
from reag.client import ReagClient, Document
from google.oauth2 import service_account
import json
import base64
import re
import time

openai_api_key = st.secrets["openai"]["OPENAI_API_KEY"]
os.environ["OPENAI_API_KEY"] = openai_api_key

# Decode the base64-encoded JSON
json_content = base64.b64decode(st.secrets["gcp_credentials"]["GOOGLE_CLOUD_CREDENTIALS"]).decode("utf-8")
service_account_info = json.loads(json_content)

# Create credentials and a client at the start
credentials = service_account.Credentials.from_service_account_info(service_account_info)
client = storage.Client(credentials=credentials)

def load_txt_from_gcs(bucket_name):
    bucket = client.get_bucket(bucket_name)
    blobs = bucket.list_blobs()
    merged_content = ""

    for blob in blobs:
        if blob.name.endswith(".txt"):
            merged_content += blob.download_as_text() + "\n"

    return merged_content

BUCKET_NAME = "contracts_roy_drive"
file_content = load_txt_from_gcs(BUCKET_NAME)

def split_text_robust(text, num_parts=20):
    """Splits text into chunks while preserving complete sentences."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    avg_size = len(sentences) // num_parts
    chunks = []
    temp_chunk = []

    for sentence in sentences:
        temp_chunk.append(sentence)
        if len(temp_chunk) >= avg_size:
            chunks.append(" ".join(temp_chunk))
            temp_chunk = []

    if temp_chunk:
        chunks.append(" ".join(temp_chunk))  

    return chunks

async def query_chunk(client, user_query, doc):
    """Sends a query for a specific chunk and processes the response with rate limiting."""
    max_retries = 5
    retry_delay = 2  

    for attempt in range(max_retries):
        try:
            response = await client.query(user_query, documents=[doc])
            response_text = str(response)

            content, reasoning, is_irrelevant = "", "", True

            if "content=" in response_text:
                content = response_text.split("content=")[1].split(", reasoning=")[0].strip('"')
            if "reasoning=" in response_text:
                reasoning = response_text.split("reasoning=")[1].split(", is_irrelevant=")[0].strip('"')
            if "is_irrelevant=" in response_text:
                is_irrelevant = "True" in response_text.split("is_irrelevant=")[1].split(",")[0]

            return doc.content, content.replace("\\n", "\n"), reasoning.replace("\\n", "\n"), is_irrelevant
        
        except Exception as e:
            if "RateLimitError" in str(e) and attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                return doc.content, "", "", True

async def query_final(client, user_query, relevant_text):
    """Final query with all relevant text."""
    if not relevant_text:
        return "No relevant information found.", "" 

    doc = Document(name="FinalMergedDoc", content=relevant_text)
    response = await client.query(user_query, documents=[doc])
    
    response_text = str(response)
    content, reasoning = "", ""
    
    if "content=" in response_text:
        content = response_text.split("content=")[1].split(", reasoning=")[0].strip('"')
    if "reasoning=" in response_text:
        reasoning = response_text.split("reasoning=")[1].split(", is_irrelevant=")[0].strip('"')
    
    return content.replace("\\n", "\n"), reasoning.replace("\\n", "\n")

def query_gpt(user_query):
    """Processes the document in chunks, gathers relevant sections, and makes a final query."""
    async def run_queries():
        text_chunks = split_text_robust(file_content, num_parts=20)
        documents = [Document(name=f"Doc_part_{i}", content=chunk) for i, chunk in enumerate(text_chunks)]

        relevant_texts = []

        async with ReagClient(model="gpt-4o-mini-2024-07-18") as client:
            tasks = [query_chunk(client, user_query, doc) for doc in documents]
            responses = await asyncio.gather(*tasks)

            for original_text, _, _, is_irrelevant in responses:
                if not is_irrelevant:
                    relevant_texts.append(original_text)

            merged_text = "\n\n".join(relevant_texts)
            final_content, final_reasoning = await query_final(client, user_query, merged_text)

        return final_content, final_reasoning

    return asyncio.run(run_queries())

# Streamlit chat interface
st.title("Legal Amigo")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

user_input = st.chat_input("Ask something about the documents...")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    
    final_content, final_reasoning = query_gpt(user_input)
    
    response_text = f"**Final Answer:**\n\n{final_content}\n\n*Reasoning:*\n{final_reasoning}"
    st.session_state.messages.append({"role": "assistant", "content": response_text})
    with st.chat_message("assistant"):
        st.markdown(response_text)
