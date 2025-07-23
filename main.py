import logging
import random
import os
import asyncio
from datetime import time
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.error import TelegramError
import pytz
from telegram.ext import JobQueue

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# MongoDB configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_bot")
QUESTIONS_COLLECTION = "question_templates"
PARTICIPANTS_COLLECTION = "participants"
ASKED_QUESTIONS_COLLECTION = "asked_questions"

# Timezone configuration
PARIS_TZ = pytz.timezone("Europe/Paris")
SCHEDULED_TIME = time(0, 0)  # 00:00

# MongoDB connection
mongo_client = None
db = None


def connect_to_mongodb():
    """Initialize MongoDB connection"""
    global mongo_client, db
    try:
        mongo_client = MongoClient(MONGODB_URI)
        # Test the connection
        mongo_client.admin.command("ping")
        logger.info(f"Connected to MongoDB at {MONGODB_URI}")

        db = mongo_client[DATABASE_NAME]
        return True
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return False


def get_asked_question_hashes(chat_id):
    """Get list of question hashes that have been asked in this chat"""
    try:
        if db is None:
            logger.error("MongoDB database not initialized")
            return []

        asked_questions = db[ASKED_QUESTIONS_COLLECTION].find(
            {"chat_id": chat_id}, {"question_hash": 1, "_id": 0}
        )
        hashes = [q["question_hash"] for q in asked_questions]
        return hashes
    except Exception as e:
        logger.error(f"Error getting asked question hashes: {e}")
        return []


def mark_question_as_asked(chat_id, question_hash):
    """Mark a question as asked in this chat"""
    try:
        if db is None:
            return False

        from datetime import datetime

        # Use upsert to avoid duplicates
        db[ASKED_QUESTIONS_COLLECTION].update_one(
            {"chat_id": chat_id, "question_hash": question_hash},
            {
                "$set": {
                    "chat_id": chat_id,
                    "question_hash": question_hash,
                    "asked_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error marking question as asked: {e}")
        return False


def reset_asked_questions(chat_id):
    """Reset all asked questions for a chat (used when all questions have been asked)"""
    try:
        if db is None:
            return False

        result = db[ASKED_QUESTIONS_COLLECTION].delete_many({"chat_id": chat_id})
        logger.info(f"Reset {result.deleted_count} asked questions for chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error resetting asked questions: {e}")
        return False


def get_random_question_from_db(chat_id):
    """Get a random question template from MongoDB that hasn't been asked in this chat"""
    try:
        if db is None:
            logger.error("MongoDB database not initialized")
            return None

        # Get list of already asked question hashes for this chat
        asked_hashes = get_asked_question_hashes(chat_id)

        # Build the query to exclude already asked questions
        query = {}
        if asked_hashes:
            query["hash"] = {"$nin": asked_hashes}

        # Use MongoDB's $sample aggregation to get one random question
        pipeline = [{"$match": query}, {"$sample": {"size": 1}}]

        questions = list(db[QUESTIONS_COLLECTION].aggregate(pipeline))

        if questions:
            question = questions[0]
            # Remove MongoDB _id field but keep the hash
            question.pop("_id", None)
            return question
        else:
            # Check if we have any questions at all
            total_questions = db[QUESTIONS_COLLECTION].count_documents({})
            if total_questions == 0:
                logger.error("No questions found in database")
                return None
            else:
                # All questions have been asked, reset and try again
                logger.info(
                    f"All questions have been asked in chat {chat_id}, resetting..."
                )
                reset_asked_questions(chat_id)

                # Try again with fresh slate
                pipeline = [{"$sample": {"size": 1}}]
                questions = list(db[QUESTIONS_COLLECTION].aggregate(pipeline))

                if questions:
                    question = questions[0]
                    question.pop("_id", None)
                    return question
                else:
                    logger.error("No questions found even after reset")
                    return None

    except Exception as e:
        logger.error(f"Error getting random question from database: {e}")
        return None


def is_user_participating(user_id, chat_id):
    """Check if user is participating in the specific chat/group"""
    try:
        if db is None:
            return False

        participant = db[PARTICIPANTS_COLLECTION].find_one(
            {"user_id": user_id, "chat_id": chat_id}
        )
        return participant is not None
    except Exception as e:
        logger.error(f"Error checking participation: {e}")
        return False


def add_participant(user_id, chat_id, username=None):
    """Add user to participants for specific chat/group"""
    try:
        if db is None:
            return False

        # Use upsert to avoid duplicates
        db[PARTICIPANTS_COLLECTION].update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {
                "$set": {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "username": username,
                    "joined_at": {"$currentDate": True},
                }
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error adding participant: {e}")
        return False


def remove_participant(user_id, chat_id):
    """Remove user from participants for specific chat/group"""
    try:
        if db is None:
            return False

        result = db[PARTICIPANTS_COLLECTION].delete_one(
            {"user_id": user_id, "chat_id": chat_id}
        )
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error removing participant: {e}")
        return False


def get_participants_names(chat_id):
    """Get list of participant names for specific chat/group"""
    try:
        if db is None:
            return []

        participants = db[PARTICIPANTS_COLLECTION].find(
            {"chat_id": chat_id}, {"username": 1, "_id": 0}
        )
        names = [p["username"] for p in participants if p.get("username")]
        return names
    except Exception as e:
        logger.error(f"Error getting participant names: {e}")
        return []


def get_participants_count(chat_id):
    """Get count of participants for specific chat/group"""
    try:
        if db is None:
            return 0

        count = db[PARTICIPANTS_COLLECTION].count_documents({"chat_id": chat_id})
        return count
    except Exception as e:
        logger.error(f"Error getting participants count: {e}")
        return 0


def get_all_active_chats():
    """Get all chat_ids that have participants"""
    try:
        if db is None:
            return []

        # Get distinct chat_ids from participants collection
        chat_ids = db[PARTICIPANTS_COLLECTION].distinct("chat_id")
        return chat_ids
    except Exception as e:
        logger.error(f"Error getting active chats: {e}")
        return []


def generate_random_question(chat_id):
    """Generate a random question with options for specific chat/group"""
    # Get a random question from database that hasn't been asked yet
    template = get_random_question_from_db(chat_id)

    if not template:
        logger.error("No questions available from database")
        return "Sorry, no questions available!", ["Error"], None

    if template["type"] == "member_options":
        # Question with participant names as options
        participant_names = get_participants_names(chat_id)

        if len(participant_names) < 3:
            return (
                "Sorry, need at least 3 participants for this type of question!",
                ["Error"],
                None,
            )

        # Randomly pick 3 to 8 participants (but not more than available)
        members_count = random.randint(3, min(6, len(participant_names)))
        selected_members = random.sample(participant_names, members_count)

        question = template["question"]
        options = selected_members
    elif template["type"] == "custom_options":
        # Question about a specific participant with custom options
        participant_names = get_participants_names(chat_id)

        if not participant_names:
            return (
                "Sorry, no participants available for this question!",
                ["Error"],
                None,
            )

        member = random.choice(participant_names)
        question = template["question"].format(member=member)
        options = template["options"]
    else:
        logger.error(f"Unknown question type: {template['type']}")
        return "Sorry, invalid question type!", ["Error"], None

    return question, options, template.get("hash")


async def send_scheduled_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Send a scheduled question to a specific chat"""
    try:
        # Check if there are participants in this chat
        participant_count = get_participants_count(chat_id)
        if participant_count == 0:
            logger.info(
                f"No participants in chat {chat_id}, skipping scheduled question"
            )
            return

        # Generate question and options
        question, options, question_hash = generate_random_question(chat_id)

        # Check for errors
        if options == ["Error"]:
            logger.error(f"Error generating question for chat {chat_id}: {question}")
            return

        # Try to find Floooooood topic
        flood_topic_id = 2082

        # Prepare poll parameters
        poll_params = {
            "chat_id": chat_id,
            "question": f"🌅 Daily Question!\n\n{question}",
            "options": options,
            "is_anonymous": False,
            "allows_multiple_answers": True,
        }

        # First, try to send to the specific topic
        try:
            poll_params["message_thread_id"] = flood_topic_id
            logger.info(
                f"Attempting to send scheduled question to Floooooood topic {flood_topic_id} in chat {chat_id}"
            )

            await context.bot.send_poll(**poll_params)
            logger.info(
                f"Successfully sent scheduled question to Floooooood topic in chat {chat_id}"
            )

            # Mark question as asked only after successful send
            if question_hash:
                mark_question_as_asked(chat_id, question_hash)

        except TelegramError as topic_error:
            # Check if the error is related to topic not existing
            error_message = str(topic_error).lower()
            if any(
                keyword in error_message
                for keyword in [
                    "message thread not found",
                    "thread not found",
                    "topic not found",
                    "bad request",
                ]
            ):
                logger.warning(
                    f"Floooooood topic {flood_topic_id} not found in chat {chat_id}, falling back to general chat"
                )

                # Remove the message_thread_id and try again in general chat
                poll_params.pop("message_thread_id", None)

                logger.info(f"Sending scheduled question to general chat {chat_id}")
                await context.bot.send_poll(**poll_params)
                logger.info(
                    f"Successfully sent scheduled question to general chat {chat_id}"
                )

                # Mark question as asked only after successful send
                if question_hash:
                    mark_question_as_asked(chat_id, question_hash)

            else:
                # Re-raise the error if it's not related to topic not existing
                raise topic_error

    except TelegramError as e:
        logger.error(
            f"Telegram error sending scheduled question to chat {chat_id}: {e}"
        )
    except Exception as e:
        logger.error(f"Error sending scheduled question to chat {chat_id}: {e}")


async def daily_question_job(context: ContextTypes.DEFAULT_TYPE):
    """Job function to send daily questions to all active chats"""
    logger.info("Running daily question job...")

    # Get all active chats
    active_chats = get_all_active_chats()

    if not active_chats:
        logger.info("No active chats found")
        return

    logger.info(f"Sending daily questions to {len(active_chats)} chats")

    # Send questions to all active chats
    for chat_id in active_chats:
        await send_scheduled_question(context, chat_id)
        # Small delay between messages to avoid rate limiting
        await asyncio.sleep(1)

    logger.info("Daily question job completed")


async def post_init(application: Application):
    """Post-initialization hook to schedule daily questions"""
    job_queue = application.job_queue

    if job_queue is None:
        logger.error(
            "JobQueue is not available. Please install python-telegram-bot[job-queue]"
        )
        return

    # Create a time object with timezone info for Paris
    import datetime as dt

    paris_midnight = dt.time(0, 0, tzinfo=PARIS_TZ)

    # Schedule daily job at 00:00 Paris time
    job_queue.run_daily(
        daily_question_job,
        time=paris_midnight,
        name="daily_questions",
    )

    logger.info(f"Scheduled daily questions at {paris_midnight} Paris time")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user

    # Send welcome message
    await update.message.reply_text(
        f"Hi {user.first_name}! 👋\n\n"
        f"Welcome to the Group Questions Bot! 🎉\n\n"
        f"To participate in the fun questions, use the command:\n"
        f"/participate\n\n"
        f"Then use /question to get a random question about group members!\n"
        f"Use /participants to see who's participating.\n\n"
        f"🌅 I'll also send a daily question every day at 00:00 Paris time automatically!"
    )


async def participate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /participate command"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_user_participating(user.id, chat_id):
        username = user.first_name or user.username or f"User{user.id}"
        if add_participant(user.id, chat_id, username):
            await update.message.reply_text(
                f"🎊 Great! {user.first_name} is now participating! 🎊\n"
                f"You can now answer questions. Use /question to get started!\n"
                f"Daily questions will be sent automatically at 00:00 Paris time! 🌅"
            )
        else:
            await update.message.reply_text(
                f"❌ Sorry, there was an error adding you to participants. Please try again."
            )
    else:
        await update.message.reply_text(
            f"You're already participating, {user.first_name}! 😊\n"
            f"Use /question to get a random question!"
        )


async def unparticipate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unparticipate command"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if is_user_participating(user.id, chat_id):
        if remove_participant(user.id, chat_id):
            await update.message.reply_text(
                f"👋 {user.first_name} has stopped participating.\n"
                f"You can rejoin anytime with /participate!"
            )
        else:
            await update.message.reply_text(
                f"❌ Sorry, there was an error removing you from participants. Please try again."
            )
    else:
        await update.message.reply_text(
            f"You're not currently participating, {user.first_name}.\n"
            f"Use /participate to join the fun!"
        )


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random question as a poll"""
    return await update.message.reply_text("The feature is currently disabled.")
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Check if user is participating in this specific chat/group
    if not is_user_participating(user.id, chat_id):
        await update.message.reply_text(
            f"You need to participate first! Use:\n/participate"
        )
        return

    # Generate question and options using actual participants
    question, options, question_hash = generate_random_question(chat_id)

    # Check for errors
    if options == ["Error"]:
        await update.message.reply_text(question)
        return

    # Create and send poll
    await context.bot.send_poll(
        chat_id=chat_id,
        question=question,
        options=options,
        is_anonymous=False,  # Show who voted for what
        allows_multiple_answers=True,  # Only one answer per person
    )

    # Mark question as asked only after successful send
    if question_hash:
        mark_question_as_asked(chat_id, question_hash)


async def show_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of participants for this chat/group"""
    chat_id = update.effective_chat.id

    participant_count = get_participants_count(chat_id)

    if participant_count == 0:
        await update.message.reply_text(
            "No participants yet in this group! Be the first to join! 🎯"
        )
        return

    await update.message.reply_text(
        f"👥 Total participants in this group: {participant_count}\n\n"
        f"Keep the fun going with /question!\n"
        f"🌅 Daily questions are sent automatically at 00:00 Paris time!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
🤖 *Group Questions Bot Commands*

/start - Welcome message and instructions
/participate - Join the fun and start participating
/unparticipate - Stop participating (you can rejoin anytime)
/question - Get a random question poll (must be participating)
/participants - See how many people are participating
/help - Show this help message

🌅 *Automatic Daily Questions*
I'll send a daily question every day at 00:00 Paris time to all groups with participants!

*Have fun voting on questions about your group members!* 🎉
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")


def main():
    """Start the bot."""
    # Initialize MongoDB connection
    if not connect_to_mongodb():
        logger.error("Failed to connect to MongoDB. Exiting...")
        return

    logger.info("Bot starting with MongoDB integration and scheduled questions")

    application = Application.builder().token(BOT_TOKEN).job_queue(JobQueue()).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("participate", participate))
    application.add_handler(CommandHandler("unparticipate", unparticipate))
    application.add_handler(CommandHandler("question", ask_question))
    application.add_handler(CommandHandler("participants", show_participants))

    # Set up post-initialization hook to schedule daily questions
    application.post_init = post_init

    # Run the bot until the user presses Ctrl-C
    try:
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        # Close MongoDB connection
        if mongo_client:
            mongo_client.close()
            logger.info("MongoDB connection closed")


if __name__ == "__main__":
    main()
