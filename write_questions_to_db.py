#!/usr/bin/env python3
"""
Migration script to populate MongoDB with question templates
Run this once to initialize your database with questions
"""

import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from questions import QUESTION_TEMPLATES

# MongoDB configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_bot")
COLLECTION_NAME = "question_templates"


def connect_to_mongodb():
    """Connect to MongoDB and return the collection"""
    try:
        client = MongoClient(MONGODB_URI)
        # Test the connection
        client.admin.command("ping")
        print(f"✅ Connected to MongoDB at {MONGODB_URI}")

        db = client[DATABASE_NAME]
        collection = db[COLLECTION_NAME]
        return collection
    except ConnectionFailure as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        return None


def migrate_questions(collection):
    """Migrate question templates to MongoDB"""
    try:
        # Clear existing questions (optional - comment out if you want to keep existing ones)
        result = collection.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} existing questions")

        # Insert new questions
        result = collection.insert_many(
            [{"hash": hash(q["question"]), **q} for q in QUESTION_TEMPLATES]
        )
        print(f"✅ Successfully inserted {len(result.inserted_ids)} question templates")

        # Create an index on question text for faster queries (optional)
        collection.create_index("question")
        print("📊 Created index on 'question' field")

        # create index for hash to ensure uniqueness
        collection.create_index("hash", unique=True)

        return True
    except Exception as e:
        print(f"❌ Error migrating questions: {e}")
        return False


def verify_migration(collection):
    """Verify that the migration was successful"""
    try:
        count = collection.count_documents({})
        print(f"📋 Total questions in database: {count}")

        # Show sample questions
        print("\n📝 Sample questions:")
        for i, question in enumerate(collection.find().limit(3)):
            print(f"  {i + 1}. {question['question'][:50]}...")
            print(f"     Type: {question['type']}, Options: {len(question['options'])}")

        return count > 0
    except Exception as e:
        print(f"❌ Error verifying migration: {e}")
        return False


def main():
    """Main migration function"""
    print("🚀 Starting MongoDB migration for question templates...")

    # Connect to MongoDB
    collection = connect_to_mongodb()
    if collection is None:
        return

    # Migrate questions
    if migrate_questions(collection):
        # Verify migration
        if verify_migration(collection):
            print("\n🎉 Migration completed successfully!")
            print(f"💡 Database: {DATABASE_NAME}")
            print(f"💡 Collection: {COLLECTION_NAME}")
            print(f"💡 MongoDB URI: {MONGODB_URI}")
        else:
            print("\n❌ Migration verification failed!")
    else:
        print("\n❌ Migration failed!")


if __name__ == "__main__":
    main()
