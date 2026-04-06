import os
import json
from flask import Flask, request, jsonify, render_template
import openai

# ---- Configuration ----
OPENROUTER_API_KEY = "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"
MODEL_NAME = "google/gemini-2.0-flash-001"

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

app = Flask(__name__)
HISTORY_FILE = "chat_history.json"

# ---- Utils ----
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_chat(messages, chat_id=None):
    history = load_history()
    
    # Extract title from the first user message
    user_msgs = [m for m in messages if m['role'] == 'user']
    title = "New Conversation"
    if user_msgs:
        title = user_msgs[0]['content'][:35] + ("..." if len(user_msgs[0]['content']) > 35 else "")

    if chat_id:
        # Update existing chat
        for chat in history:
            if chat['id'] == chat_id:
                chat['messages'] = messages
                chat['title'] = title
                break
        else:
            # If ID not found, treat as new
            chat_id = os.urandom(4).hex()
            history.insert(0, {"id": chat_id, "title": title, "messages": messages})
    else:
        # Create new chat
        chat_id = os.urandom(4).hex()
        history.insert(0, {"id": chat_id, "title": title, "messages": messages})

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[:100], f, indent=4)
    return chat_id

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



