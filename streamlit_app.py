import os
import asyncio
import streamlit as st
from google.cloud import storage
from reag.client import ReagClient, Document
from google.cloud import storage
from google.oauth2 import service_account
import json
import base64

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


# Bucket name on Google Cloud Storage
BUCKET_NAME = "contracts_roy_drive"

# Load content from the bucket (runs once)
file_content = load_txt_from_gcs(BUCKET_NAME)

def query_gpt(user_query):
    """Asynchronous function to query the model"""
    async def run_query():
        async with ReagClient(model="gpt-4o-mini-2024-07-18") as client:
            response = await client.query(user_query, documents=[Document(name="MergedDocs", content=file_content)])
            
            # Extract content and reasoning fields and clean formatting
            response_text = str(response)
            content = ""
            reasoning = ""
            
            if "content=" in response_text:
                content = response_text.split("content=")[1].split(", reasoning=")[0].strip('"')
            if "reasoning=" in response_text:
                reasoning = response_text.split("reasoning=")[1].split(", is_irrelevant=")[0].strip('"')
            
            return content.replace("\\n", "\n"), reasoning.replace("\\n", "\n")
    
    return asyncio.run(run_query())

# Streamlit chat interface
st.title("Document Chatbot")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User input
user_input = st.chat_input("Ask something about the documents...")
if user_input:
    # Display user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Get response
    content, reasoning = query_gpt(user_input)
    
    # Display formatted response
    response_text = f"**Response:**\n\n{content}\n\n*Why this answer?*\n{reasoning}"
    st.session_state.messages.append({"role": "assistant", "content": response_text})
    with st.chat_message("assistant"):
        st.markdown(response_text)