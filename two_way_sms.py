import africastalking
from typing import List, Dict
import asyncio
from flask import Flask, request, jsonify
import google.generativeai as genai
import logging
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SENDER_NAME = "7833"

class EducationalChatbot:
    def __init__(self, username: str, api_key: str, gemini_api_key: str):
        self.username = username
        self.api_key = api_key
        self.gemini_api_key = gemini_api_key
        
        # Initialize Africa's Talking
        africastalking.initialize(username, api_key)
        self.sms = africastalking.SMS
        
        # Initialize Gemini AI
        genai.configure(api_key=gemini_api_key)
        self.model = "gemini-2.5-flash-preview-05-20"
        self.client = genai.GenerativeModel(self.model)
        self.config = {"response_modalities": ["TEXT"]}
        
        # Store conversation history for context
        self.conversations = {}
        
        # Educational system prompt
        self.system_prompt = """You are an educational SMS chatbot assistant. Your role is to:
        1. Help students with homework and study questions
        2. Explain concepts in simple, clear language suitable for SMS
        3. Provide educational resources and tips
        4. Keep responses concise (under 160 characters when possible) due to SMS limitations
        5. Be encouraging and supportive
        6. If asked non-educational questions, politely redirect to educational topics
        7. You can understand and respond in Swahili if the user speaks to you in Swahili, to support users in East African countries.
        
        Always be helpful, patient, and educational in your responses."""

    async def send_message(self, message: str, recipients: List, sender: str = SENDER_NAME) -> str:
        """Send SMS message to recipients"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.sms.send(message, recipients, sender)
            )
            logger.info(f"Message sent successfully: {response}")
            return f"Message sent successfully: {response}"
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            return f"Failed to send message: {str(e)}"

    async def get_gemini_response(self, user_message: str, phone_number: str) -> str:
        """Get response from Gemini AI with educational context"""
        try:
            # Get conversation history for context
            conversation_history = self.conversations.get(phone_number, [])
            
            # Build context from recent messages (last 5 exchanges)
            context = ""
            if conversation_history:
                recent_history = conversation_history[-10:]  # Last 10 messages (5 exchanges)
                for msg in recent_history:
                    context += f"{msg['role']}: {msg['content']}\n"
            
            # Create full prompt with system prompt, context, and current message
            full_prompt = f"{self.system_prompt}\n\nConversation history:\n{context}\nStudent: {user_message}\n\nEducational Assistant:"
            
            # Generate response using the new Gemini API
            ai_response = ""
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.generate_content(full_prompt)
            )
            if hasattr(response, 'text') and response.text:
                ai_response = response.text
            
            # Truncate response if too long for SMS
            if len(ai_response) > 300:
                ai_response = ai_response[:300] + "... (reply 'more' for continuation)"
            
            # Update conversation history
            if phone_number not in self.conversations:
                self.conversations[phone_number] = []
            
            self.conversations[phone_number].extend([
                {"role": "Student", "content": user_message, "timestamp": datetime.now().isoformat()},
                {"role": "Assistant", "content": ai_response, "timestamp": datetime.now().isoformat()}
            ])
            
            # Keep only last 20 messages per conversation to manage memory
            if len(self.conversations[phone_number]) > 20:
                self.conversations[phone_number] = self.conversations[phone_number][-20:]
            
            return ai_response.strip() if ai_response else "I'm having trouble generating a response. Please try again."
            
        except Exception as e:
            logger.error(f"Error getting Gemini response: {str(e)}")
            return "Sorry, I'm having trouble processing your question right now. Please try again later."

    async def handle_incoming_sms(self, phone_number: str, message: str) -> str:
        """Handle incoming SMS and generate educational response"""
        try:
            logger.info(f"Received SMS from {phone_number}: {message}")
            print(f"[LOG] Incoming SMS received from {phone_number}: {message}")
            # Get AI response
            ai_response = await self.get_gemini_response(message, phone_number)
            # Send response back to user
            await self.send_message(ai_response, [phone_number])
            return ai_response
        except Exception as e:
            logger.error(f"Error handling incoming SMS: {str(e)}")
            error_message = "Sorry, I encountered an error. Please try sending your question again."
            await self.send_message(error_message, [phone_number])
            return error_message

# Flask app for handling webhooks
app = Flask(__name__)

# Initialize your chatbot (you'll need to provide your actual API keys)
chatbot = None

def initialize_chatbot(username: str, africastalking_api_key: str, gemini_api_key: str):
    """Initialize the chatbot with API keys"""
    global chatbot
    chatbot = EducationalChatbot(username, africastalking_api_key, gemini_api_key)
    logger.info("Chatbot initialized successfully")

@app.route('/sms/callback', methods=['POST'])
def sms_callback():
    """Handle incoming SMS callbacks from Africa's Talking"""
    try:
        # Parse the incoming data
        data = request.form.to_dict()
        
        phone_number = data.get('from')
        message = data.get('text')
        message_id = data.get('id')
        
        logger.info(f"SMS callback received: {data}")
        
        if not phone_number or not message:
            return jsonify({"error": "Missing required fields"}), 400
        
        if chatbot is None:
            return jsonify({"error": "Chatbot not initialized"}), 500
        
        # Always create a new event loop in this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(chatbot.handle_incoming_sms(phone_number, message))
        loop.close()
        
        return jsonify({"status": "Message received and processing"}), 200
        
    except Exception as e:
        logger.error(f"Error in SMS callback: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/sms/delivery', methods=['POST'])
def delivery_callback():
    """Handle SMS delivery reports"""
    try:
        data = request.form.to_dict()
        logger.info(f"Delivery report: {data}")
        return jsonify({"status": "Delivery report received"}), 200
    except Exception as e:
        logger.error(f"Error in delivery callback: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

# Example usage and testing functions
async def test_send_message():
    """Test function to send a message"""
    if chatbot:
        response = await chatbot.send_message(
            "Hello! I'm your educational SMS assistant. Send me any study questions!",
            ["+1234567890"],  # Replace with actual phone number
            "EduBot"
        )
        print(response)

def run_flask_app():
    """Run the Flask application"""
    app.run(host='0.0.0.0', port=8000, debug=True)

if __name__ == "__main__":
    # Initialize the chatbot with your API keys
    # Replace these with your actual API keys
    USERNAME = "sandbox"
    AFRICASTALKING_API_KEY = "atsk_74691cad275149ae5c6fe3e45ac7e24420a4f5bf73ea92b391e94857aaaba69d8c3366cc"
    GEMINI_API_KEY = "AIzaSyCMvb2QcODkdvG4382iKUHrZtRZ59zzyRU"
    
    # Initialize chatbot
    initialize_chatbot(USERNAME, AFRICASTALKING_API_KEY, GEMINI_API_KEY)
    
    # Run Flask app
    print("Starting Educational SMS Chatbot server...")
    print("Webhook endpoints:")
    print("- SMS Callback: http://your-domain.com/sms/callback")
    print("- Delivery Reports: http://your-domain.com/sms/delivery")
    print("- Health Check: http://your-domain.com/health")
    
    run_flask_app()