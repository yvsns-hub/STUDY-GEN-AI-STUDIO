import os
import json
from flask import Flask, request, jsonify, render_template, Response
import openai
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

# ---- Configuration ----
# Retrieve API key from environment for security. Fallback to None if not set.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
MODEL_NAME = os.environ.get("MODEL_NAME", "google/gemini-2.0-flash-001").strip()

if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY is not set in environment!")

# Initialize Firebase Admin
if not firebase_admin._apps:
    service_account_info = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if service_account_info:
        try:
            # Use service account from environment variable (for Render/Production)
            info = json.loads(service_account_info)
            cred = credentials.Certificate(info)
            firebase_admin.initialize_app(cred)
            print("Firebase Admin initialized with Cloud Certificate.")
        except Exception as e:
            print(f"FIREBASE INIT ERROR: Could not parse JSON key. Error: {str(e)}")
    else:
        # Fallback to default credentials (for local testing/Google Cloud)
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
            print("Firebase Admin initialized with ApplicationDefault.")
        except Exception as e:
            print(f"FIREBASE INIT ERROR: No credentials found. Firestore will be disabled. Error: {str(e)}")

try:
    db = firestore.client()
    CHATS_COLLECTION = "user_chats"
    print("Firestore client connected successfully.")
except Exception as e:
    print(f"FIRESTORE ERROR: Could not connect to database. Error: {str(e)}")
    db = None

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

app = Flask(__name__)

@app.after_request
def add_header(response):
    # Fix for Cross-Origin-Opener-Policy blocking Firebase Auth popups
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
    return response


# ---- Utils (Firestore Migration) ----

def load_history():
    """Retrieve chat history from Firestore."""
    if not db:
        return []
    try:
        docs = db.collection(CHATS_COLLECTION).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
        history = []
        for doc in docs:
            chat_data = doc.to_dict()
            chat_data['id'] = doc.id
            if 'timestamp' in chat_data:
                del chat_data['timestamp']
            history.append(chat_data)
        return history
    except Exception as e:
        print(f"LOAD_HISTORY ERROR: {str(e)}")
        return []

def save_chat(messages, chat_id=None):
    """Save/Update chat in Firestore."""
    if not db:
        return os.urandom(4).hex()
        
    try:
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
            db.collection(CHATS_COLLECTION).document(chat_id).set(chat_data)
            return chat_id
        else:
            doc_ref = db.collection(CHATS_COLLECTION).add(chat_data)
            return doc_ref[1].id
    except Exception as e:
        print(f"SAVE_CHAT ERROR: {str(e)}")
        return os.urandom(4).hex()

# ---- Routes ----

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    messages = data.get("messages", [])
    chat_id = data.get("chat_id")
    
    if not OPENROUTER_API_KEY:
        return jsonify({"error": "AI API Key missing on server"}), 500

    def generate():
        try:
            # We want to enable streaming for that 'line-by-line' effect
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": "You are a professional assistant. Use clear markdown and provide helpful, concise responses."}] + messages,
                stream=True
            )
            
            full_content = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_content += content
                    yield f"data: {json.dumps({'content': content})}\n\n"
            
            # After stream finishes, save to history in background (don't block the UI)
            messages.append({"role": "assistant", "content": full_content})
            save_chat(messages, chat_id)
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/get_chat/<chat_id>')
def get_chat(chat_id):
    """Retrieve highly specific chat history."""
    if not db: return jsonify({"error": "No DB"}), 500
    try:
        doc = db.collection(CHATS_COLLECTION).document(chat_id).get()
        if doc.exists:
            return jsonify(doc.to_dict())
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_history')
def get_history():
    return jsonify(load_history())

@app.route('/delete_chat/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    """Permanently remove a chat from Firestore."""
    if not db:
        return jsonify({"error": "Database not connected"}), 500
    try:
        db.collection(CHATS_COLLECTION).document(chat_id).delete()
        return jsonify({"status": "success", "message": "Chat deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)



