# AskUs Telegram Bot

A Telegram group engagement bot that sends daily icebreaker questions as interactive polls to keep your community active and engaged.

## Features

- **Daily Questions**: Automatically sends random questions at a scheduled time
- **Interactive Polls**: Questions are sent as polls where participants vote
- **Participation System**: Users can join/leave with `/participate` and `/unparticipate`
- **Question Types**: Supports "Who would most likely..." questions with member names as options, or custom predefined options
- **No Repeats**: Tracks asked questions per group to avoid repetition

## Tech Stack

- Python 3.11
- python-telegram-bot v22.1
- MongoDB

## Quick Start

1. **Set environment variables**:
   ```
   BOT_TOKEN=<your_telegram_bot_token>   # Required
   MONGODB_URI=mongodb://localhost:27017/
   DATABASE_NAME=telegram_bot
   TIMEZONE=Europe/Paris
   SCHEDULED_TIME=00:00
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Populate questions**:
   ```bash
   python write_questions_to_db.py
   ```

4. **Run the bot**:
   ```bash
   python main.py
   ```

## Docker

```bash
docker build -t askus-telegram-bot .
docker run -e BOT_TOKEN=<token> -e MONGODB_URI=<uri> askus-telegram-bot
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Show available commands |
| `/participate` | Join the question game |
| `/unparticipate` | Leave the question game |
| `/participants` | Show participant count |

## License

MIT
