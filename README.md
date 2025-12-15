# 🤖 AI Telegram Agent

A smart AI-powered Telegram assistant that communicates with users and can be fully controlled through an admin panel inside Telegram.

---

## ✨ Description

The bot responds to user questions using OpenAI and provides fast, helpful communication.  
Admins can customize the assistant’s behavior and manage files that enhance the model's knowledge.

The system supports dynamic updating of the agent’s instructions (system prompt) and integrates a knowledge base that improves the accuracy of the answers.

---

## 🔧 Admin Features

- Change the agent's system prompt directly inside Telegram
- Upload files to the agent’s knowledge base
- Files become a source of additional knowledge for the assistant
- View list of all uploaded files
- Download previously uploaded files
- Delete files from the database and completely remove them from OpenAI storage

---

## 🧠 Assistant Features

- Understands user questions naturally using OpenAI
- Provides helpful responses
- Uses admin-uploaded files as a knowledge source
- Automatically adapts answers based on updated prompt

---

##🧑‍💼 Admin Takeover & Chat Management

- Admins can take over conversations from the AI at any moment via a dedicated log chat
- Real-time client ↔ admin message routing inside Telegram
- Full conversation history is available when opening a client chat
- Soft chat closing with automatic fallback to AI after a timeout
- All client and operator messages are logged for transparency and monitoring
