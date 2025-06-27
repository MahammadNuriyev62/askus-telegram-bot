import logging
import random
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

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


def get_random_question_from_db():
    """Get a random question template from MongoDB"""
    try:
        if db is None:
            logger.error("MongoDB database not initialized")
            return None

        # Use MongoDB's $sample aggregation to get one random question
        pipeline = [{"$sample": {"size": 1}}]
        questions = list(db[QUESTIONS_COLLECTION].aggregate(pipeline))

        if questions:
            question = questions[0]
            # Remove MongoDB _id field
            question.pop("_id", None)
            return question
        else:
            logger.error("No questions found in database")
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


def generate_random_question(chat_id):
    """Generate a random question with options for specific chat/group"""
    # Get a random question from database
    template = get_random_question_from_db()

    if not template:
        logger.error("No questions available from database")
        return "Sorry, no questions available!", ["Error"]

    if template["type"] == "member_options":
        # Question with participant names as options
        participant_names = get_participants_names(chat_id)

        if len(participant_names) < 3:
            return "Sorry, need at least 3 participants for this type of question!", [
                "Error"
            ]

        # Randomly pick 3 or 4 participants (but not more than available)
        max_options = min(len(participant_names), 4)
        members_count = (
            random.choice([3, max_options]) if max_options >= 4 else max_options
        )
        selected_members = random.sample(participant_names, members_count)

        question = template["question"]
        options = selected_members
    elif template["type"] == "custom_options":
        # Question about a specific participant with custom options
        participant_names = get_participants_names(chat_id)

        if not participant_names:
            return "Sorry, no participants available for this question!", ["Error"]

        member = random.choice(participant_names)
        question = template["question"].format(member=member)
        options = template["options"]
    else:
        logger.error(f"Unknown question type: {template['type']}")
        return "Sorry, invalid question type!", ["Error"]

    return question, options


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
        f"Use /participants to see who's participating."
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
                f"You can now answer questions. Use /question to get started!"
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
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Check if user is participating in this specific chat/group
    if not is_user_participating(user.id, chat_id):
        await update.message.reply_text(
            f"You need to participate first! Use:\n/participate"
        )
        return

    # Generate question and options using actual participants
    question, options = generate_random_question(chat_id)

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
        f"Keep the fun going with /question!"
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

*Have fun voting on questions about your group members!* 🎉
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")


def main():
    """Start the bot."""
    # Initialize MongoDB connection
    if not connect_to_mongodb():
        logger.error("Failed to connect to MongoDB. Exiting...")
        return

    logger.info("Bot starting with MongoDB integration")

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("participate", participate))
    application.add_handler(CommandHandler("unparticipate", unparticipate))
    application.add_handler(CommandHandler("question", ask_question))
    application.add_handler(CommandHandler("participants", show_participants))

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
