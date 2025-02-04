import logging
import random
import nest_asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, Application, CallbackContext
from pymongo import MongoClient
from datetime import datetime, timedelta

# Apply nest_asyncio
nest_asyncio.apply()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")  # MongoDB local connection
db = client.society_complaints  # Database name
complaints_collection = db.complaints  # Collection to store complaints

# Define states for conversation handler
NEW_REQUEST, FOLLOW_UP, CATEGORY, USER_DETAILS, ISSUE_DETAILS, CONFIRM_NUMBER = range(6)

# Category contact numbers
category_contacts = {
    "Plumbing": "1234567890",
    "Seepage": "2345678901",
    "Cleanliness": "3456789012",
    "Parking": "4567890123",
    "Official document": "5678901234",
    "Lift": "6789012345",
    "Water": "7890123456",
    "Electricity": "8901234567",
    "Gas": "9012345678",
    "Security": "0123456789"
}

# Define categories with icons and colors
categories = {
    "Plumbing": ("💧", "blue"),
    "Seepage": ("🌧️", "gray"),
    "Cleanliness": ("🧹", "green"),
    "Parking": ("🚗", "yellow"),
    "Official document": ("📄", "orange"),
    "Lift": ("🛗", "purple"),
    "Water": ("🚰", "lightblue"),
    "Electricity": ("💡", "red"),
    "Gas": ("⛽", "green"),
    "Security": ("🔒", "darkblue")
}

# Start command to initiate the conversation
async def start(update: Update, context: CallbackContext) -> int:
    context.user_data['chat_id'] = update.message.chat_id
    await update.message.reply_text(
        "Hi! Welcome to the TPC Society Complaints Bot. How can I assist you today?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("New Request", callback_data=str(NEW_REQUEST))],
            [InlineKeyboardButton("Follow Up", callback_data=str(FOLLOW_UP))]
        ])
    )
    return NEW_REQUEST

# Handle new request and category selection
async def new_request(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please select the category for your complaint:",
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton(f"{emoji} {category}", callback_data=category)]
                                      for category, (emoji, color) in categories.items()
                                  ]))
    return CATEGORY

# Handle category selection
async def category_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    category = query.data
    context.user_data['category'] = category
    await query.edit_message_text(f"You selected: {category}. Please provide the following details:\n\n"
                                  "1. Name of Owner or person registering the complaint\n"
                                  "2. Flat number\n"
                                  "3. Contact number")
    return USER_DETAILS

# Collect user details
async def user_details(update: Update, context: CallbackContext) -> int:
    context.user_data['user_details'] = update.message.text
    await update.message.reply_text("Please provide detailed information about the issue.")
    return ISSUE_DETAILS

# Collect issue details
async def issue_details(update: Update, context: CallbackContext) -> int:
    context.user_data['issue_details'] = update.message.text
    await store_complaint(update, context)
    return ConversationHandler.END

# Handle storing complaint and notifying contact person
async def store_complaint(update: Update, context: CallbackContext) -> None:
    # Generate complaint number (e.g., TPC12345)
    complaint_number = f"TPC{random.randint(10000, 20000)}"
    resolution_time = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    complaint_data = {
        "complaint_number": complaint_number,
        "category": context.user_data['category'],
        "user_details": context.user_data['user_details'],
        "issue_details": context.user_data['issue_details'],
        "resolution_time": resolution_time,
        "status": "Open",
        "created_at": datetime.now()
    }

    complaints_collection.insert_one(complaint_data)

    # Send the complaint details to the category contact number
    contact_number = category_contacts.get(context.user_data['category'])
    message = f"New complaint registered:\n\n" \
              f"Complaint ID: {complaint_number}\n" \
              f"Category: {context.user_data['category']}\n" \
              f"Details: {context.user_data['issue_details']}\n" \
              f"User Details: {context.user_data['user_details']}\n" \
              f"Resolution Time: {resolution_time}\n\n" \
              f"Note: This will be escalated if it takes more than 48 hours to resolve."

    # Send the complaint to the category contact number
    await context.bot.send_message(chat_id=contact_number, text=message)
    
    await update.message.reply_text(f"Thank you for your complaint! Your complaint number is {complaint_number}. "
                                   f"We aim to resolve it within 24 hours. Please share the image or video with the contact person along with the complaint ID.")

async def follow_up(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Please provide your complaint ID to follow up.")
    return FOLLOW_UP

async def handle_follow_up(update: Update, context: CallbackContext) -> int:
    complaint_id = update.message.text
    context.user_data['complaint_id'] = complaint_id
    await update.message.reply_text(f"Is this the correct complaint ID: {complaint_id}? (Yes/No)")
    return CONFIRM_NUMBER

async def confirm_number(update: Update, context: CallbackContext) -> int:
    user_response = update.message.text.lower()
    if user_response == 'yes':
        complaint_id = context.user_data['complaint_id']
        complaint = complaints_collection.find_one({"complaint_number": complaint_id})
        if complaint:
            time_elapsed = datetime.now() - complaint['created_at']
            if time_elapsed.total_seconds() > 172800:  # 48 hours
                await update.message.reply_text(f"Your complaint {complaint_id} is more than 48 hours old. Please wait for someone to contact you or reach out directly to the provided contact number.")
            else:
                await update.message.reply_text(f"Your complaint {complaint_id} is still within the 48-hour resolution window. Please check with the contact person for an update.")
        else:
            await update.message.reply_text(f"Complaint {complaint_id} not found.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Please enter the correct complaint ID.")
        return FOLLOW_UP

# Function to check complaints older than 48 hours and send escalation messages
async def send_escalation(update: Update, context: CallbackContext) -> None:
    complaints = complaints_collection.find({"status": "Open"})
    for complaint in complaints:
        time_difference = datetime.now() - complaint['created_at']
        if time_difference > timedelta(hours=48):
            contact_number = category_contacts.get(complaint['category'])
            escalation_message = f"Escalation: Complaint ID {complaint['complaint_number']} has not been resolved in 48 hours.\n\n" \
                                 f"Details: {complaint['issue_details']}\n" \
                                 f"User: {complaint['user_details']}"
            # Send escalation message to the category contact number
            await context.bot.send_message(chat_id=contact_number, text=escalation_message)

# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f"Update {update} caused error {context.error}")
    if update:
        await update.message.reply_text("Sorry, something went wrong. Please try again later.")

# Main function to set up the bot
async def main() -> None:
    application = Application.builder().token("7397501447:AAHk_cg_NfwVqNMiLff1URRRdByl08AOuRM").build()

    # Add error handler to the dispatcher
    application.add_error_handler(error)

    # Schedule the send_escalation function to run periodically, e.g., once a day
    job_queue = application.job_queue
    job_queue.run_repeating(send_escalation, interval=86400, first=0)  # Run once a day

   # Conversation handler for the bot
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NEW_REQUEST: [CallbackQueryHandler(new_request, pattern='^' + str(NEW_REQUEST) + '$')],
            CATEGORY: [CallbackQueryHandler(category_selection)],
            USER_DETAILS: [MessageHandler(filters.Text(), user_details)],
            ISSUE_DETAILS: [MessageHandler(filters.Text(), issue_details)],
            FOLLOW_UP: [MessageHandler(filters.Text(), follow_up)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
