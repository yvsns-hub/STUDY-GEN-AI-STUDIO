import os
import json
from flask import Flask, request, jsonify, render_template
import openai
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

# ---- Configuration ----
# Retrieve API key from environment for security. Fallback to None if not set.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL_NAME = os.environ.get("MODEL_NAME", "google/gemini-2.0-flash-001")

if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY is not set in environment!")

# Initialize Firebase Admin
if not firebase_admin._apps:
    service_account_info = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if service_account_info:
        # Use service account from environment variable (for Render/Production)
        info = json.loads(service_account_info)
        cred = credentials.Certificate(info)
        firebase_admin.initialize_app(cred)
    else:
        # Fallback to default credentials (for local testing/Google Cloud)
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        except:
            print("No Firebase credentials found. Firestore will not work!")

db = firestore.client()
CHATS_COLLECTION = "user_chats"

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

app = Flask(__name__)

# ---- Utils (Firestore Migration) ----

def load_history():
    """Retrieve chat history from Firestore."""
    try:
        docs = db.collection(CHATS_COLLECTION).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
        history = []
        for doc in docs:
            chat_data = doc.to_dict()
            chat_data['id'] = doc.id
            # Remove timestamp for clean JSON return
            if 'timestamp' in chat_data:
                del chat_data['timestamp']
            history.append(chat_data)
        return history
    except Exception as e:
        print(f"Firestore Error: {str(e)}")
        return []

def save_chat(messages, chat_id=None):
    """Save/Update chat in Firestore."""
    user_msgs = [m for m in messages if m['role'] == 'user']
    title = "New Conversation"
    if user_msgs:
        title = user_msgs[0]['content'][:35] + ("..." if len(user_msgs[0]['content']) > 35 else "")

    chat_data = {
        "title": title,
        "messages": messages,
        "timestamp": firestore.SERVER_TIMESTAMP
    }

    if chat_id:
        # Update existing
        db.collection(CHATS_COLLECTION).document(chat_id).set(chat_data)
        return chat_id
    else:
        # Create new
        doc_ref = db.collection(CHATS_COLLECTION).add(chat_data)
        return doc_ref[1].id

# ---- Routes ----

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    messages = data.get("messages", [])
    chat_id = data.get("chat_id")
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": "You are a professional assistant."}] + messages
        )
        ai_response = response.choices[0].message.content
        messages.append({"role": "assistant", "content": ai_response})
        
        # Save/Update history and get the (possibly new) chat_id
        new_chat_id = save_chat(messages, chat_id)
        
        return jsonify({"response": ai_response, "chat_id": new_chat_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_history')
def get_history():
    return jsonify(load_history())

if __name__ == "__main__":
    app.run(debug=True, port=5000)



