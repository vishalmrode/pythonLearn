from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
from pymongo import MongoClient
import gridfs
import random
import datetime

# MongoDB setup
client = MongoClient('mongodb://localhost:27017/')
db = client['society_complaints']
complaints_collection = db['complaints']
fs = gridfs.GridFS(db)

# States for conversation
CATEGORY, DETAILS, IMAGE, CONFIRMATION, FOLLOW_UP, CLOSE_COMPLAINT, NEW_OR_FOLLOW_UP, REQUEST_NUMBER, CONFIRM_NUMBER = range(9)

# Categories and contact details
categories = {
    "🔧 Plumbing": "Contact: Mr. Ballal, Phone: 1234567890",
    "💧 Seepage": "Contact: Mr. Karanjkar, Phone: 0987654321",
    "🧹 Cleanliness": "Contact: Mrs. Vasekar, Phone: 1122334455",
    "🚗 Parking": "Contact: Mr. Godbole, Phone: 2233445566",
    "📄 Official document": "Contact: Mrs. Ghadge, Phone: 3344556677",
    "🛗 Lift": "Contact: Mr. Kelkar, Phone: 4455667788",
    "💦 Water": "Contact: Mr. Gokhale, Phone: 5566778899",
    "💡 Electricity": "Contact: Mr. Vasekar, Phone: 6677889900",
    "🔥 Gas": "Contact: Mr. Rode, Phone: 7788990016661",
    "🔒 Security": "Contact: Mr. Jagtap, Phone: 88990066661122"
}

async def start(update: Update, context: CallbackContext) -> int:
    context.user_data['chat_id'] = update.message.chat_id
    await update.message.reply_text(
        "Welcome! Do you want to register a new complaint or follow up on an existing complaint? (new/follow-up)"
    )
    return NEW_OR_FOLLOW_UP

async def new_or_follow_up(update: Update, context: CallbackContext) -> int:
    user_response = update.message.text.lower()
    if user_response == 'new':
        await update.message.reply_text(
            "Do you want to register a complaint? (yes/no)"
        )
        return CATEGORY
    elif user_response == 'follow-up':
        await update.message.reply_text(
            "Please provide your complaint number."
        )
        return REQUEST_NUMBER
    else:
        await update.message.reply_text("Invalid response. Please type 'new' or 'follow-up'.")
        return NEW_OR_FOLLOW_UP

async def request_number(update: Update, context: CallbackContext) -> int:
    context.user_data['complaint_number'] = update.message.text
    await update.message.reply_text(
        f"Is this the correct complaint number: {context.user_data['complaint_number']}? (yes/no)"
    )
    return CONFIRM_NUMBER

async def confirm_number(update: Update, context: CallbackContext) -> int:
    user_response = update.message.text.lower()
    if user_response == 'yes':
        complaint_number = context.user_data['complaint_number']
        complaint = complaints_collection.find_one({"complaint_number": complaint_number})
        if complaint:
            time_elapsed = datetime.datetime.now() - complaint['timestamp']
            if time_elapsed.total_seconds() > 86400:
                await context.bot.send_message(chat_id=complaint['chat_id'], text=f"Escalation: Complaint {complaint_number} has not been resolved within 24 hours. Please address it urgently.")
                await update.message.reply_text(f"Your complaint {complaint_number} has been escalated. We will resolve it as soon as possible.")
            else:
                await update.message.reply_text(f"Your complaint {complaint_number} is still within the 24-hour resolution window. Please check with the contact person for an update.")
        else:
            await update.message.reply_text(f"Complaint {complaint_number} not found.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Please enter the correct complaint number.")
        return REQUEST_NUMBER

async def category(update: Update, context: CallbackContext) -> int:
    user_response = update.message.text.lower()
    if user_response == 'yes':
        reply_keyboard = [[category] for category in categories]
        await update.message.reply_text(
            "Please choose a category:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return DETAILS
    else:
        await update.message.reply_text("Okay, let me know if you need anything else.")
        return ConversationHandler.END

async def details(update: Update, context: CallbackContext) -> int:
    context.user_data['category'] = update.message.text
    await update.message.reply_text(
        "Please provide your name, flat number, and contact number."
    )
    return IMAGE

async def image(update: Update, context: CallbackContext) -> int:
    context.user_data['details'] = update.message.text
    await update.message.reply_text(
        "Please provide detailed information on the issue and upload an image if you have one."
    )
    return CONFIRMATION

async def confirmation(update: Update, context: CallbackContext) -> int:
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        image_id = fs.put(photo_bytes, filename=f"{photo_file.file_id}.jpg")
        context.user_data['image_id'] = image_id

    context.user_data['issue'] = update.message.text
    complaint_number = f"TaranganComplaint{random.randint(1, 20000)}"
    context.user_data['complaint_number'] = complaint_number
    context.user_data['timestamp'] = datetime.datetime.now()

    # Remove _id from context.user_data to avoid DuplicateKeyError
    if '_id' in context.user_data:
        del context.user_data['_id']

    # Store the complaint in MongoDB
    complaints_collection.insert_one(context.user_data)

    category = context.user_data['category']
    contact_info = categories.get(category, "No contact information available")

    await update.message.reply_text(
        f"Your complaint has been noted. Your complaint number is {complaint_number}. We will resolve it within 24 hours.\n\nFor {category} issues, you can contact: {contact_info}"
    )

    # Notify the relevant contact person
    await context.bot.send_message(chat_id=context.user_data['chat_id'], text=f"New complaint registered for {category}. Complaint number: {complaint_number}. Details: {context.user_data['details']}")

    # Schedule a job to follow up after 24 hours
    context.job_queue.run_once(follow_up, 86400, context=update.message.chat_id, name=str(complaint_number))

    return ConversationHandler.END

async def follow_up(context: CallbackContext) -> None:
    job = context.job
    complaint = complaints_collection.find_one({"complaint_number": job.name})
    if complaint and not complaint.get('resolved'):
        await context.bot.send_message(job.context, text=f"Follow-up: Your complaint {job.name} is still pending. We are working on it.")
        # Escalate the complaint
        await context.bot.send_message(chat_id=complaint['chat_id'], text=f"Escalation: Complaint {job.name} has not been resolved within 24 hours. Please address it urgently.")

async def close_complaint(update: Update, context: CallbackContext) -> int:
    complaint_number = update.message.text.split()[-1]
    complaint = complaints_collection.find_one({"complaint_number": complaint_number})
    if complaint:
        complaints_collection.update_one({"complaint_number": complaint_number}, {"$set": {"resolved": True}})
        await update.message.reply_text(f"Complaint {complaint_number} has been closed. Thank you for your patience.")
    else:
        await update.message.reply_text(f"Complaint {complaint_number} not found.")
    return ConversationHandler.END

async def done(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Thank you! If you have any more complaints, feel free to let us know.")
    return ConversationHandler.END

async def restart(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Restarting the bot...")
    main()
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token("YOUR_TELEGRAM_BOT_TOKEN").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NEW_OR_FOLLOW_UP: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_or_follow_up)],
            REQUEST_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, request_number)],
            CONFIRM_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_number)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category)],
            DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, details)],
            IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, image)],
            CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmation)],
            FOLLOW_UP: [MessageHandler(filters.TEXT & ~filters.COMMAND, follow_up)],
            CLOSE_COMPLAINT: [MessageHandler(filters.TEXT & ~filters.COMMAND, close_complaint)],
        },
        fallbacks=[CommandHandler('done', done), CommandHandler('restart', restart)],
    )

    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
