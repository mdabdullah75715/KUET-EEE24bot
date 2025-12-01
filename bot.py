import os
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 5490832869  # Your admin ID
DATABASE_NAME = "kuet_eee_bot.db"

# Conversation states
(
    REG_NAME, REG_ROLL, REG_BATCH, REG_GENDER, REG_PHONE, 
    REG_PHOTO, REG_FB, REG_BLOOD, REG_HOME, REG_EMAIL
) = range(10)

# User roles
class UserRole(Enum):
    USER = "user"
    CO_ADMIN = "co_admin"
    ADMIN = "admin"

# File categories
FILE_CATEGORIES = [
    "Lectures", "Books", "Notes", 
    "Assignments", "Projects", "Others"
]

# ==================== DATABASE SETUP ====================
def init_database():
    """Initialize the SQLite database with required tables"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            name TEXT,
            roll TEXT,
            batch TEXT,
            gender TEXT,
            phone TEXT,
            photo_id TEXT,
            fb_link TEXT,
            blood_group TEXT,
            hometown TEXT,
            email TEXT,
            role TEXT DEFAULT 'user',
            is_approved INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Files table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            file_type TEXT,
            file_id TEXT,
            category TEXT,
            description TEXT,
            uploader_id INTEGER,
            uploader_name TEXT,
            is_approved INTEGER DEFAULT 0,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uploader_id) REFERENCES users(telegram_id)
        )
    """)
    
    # Dynamic menus table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menus (
            menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_name TEXT UNIQUE,
            menu_content TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # Initialize default menus
    default_menus = [
        ("📚 Study Materials", "Access lectures, books, and notes"),
        ("👥 Batch Profiles", "View batchmate profiles"),
        ("📷 Photo Gallery", "Batch photos and memories"),
        ("ℹ️ Help", "How to use this bot"),
    ]
    
    for menu_name, content in default_menus:
        cursor.execute(
            "INSERT OR IGNORE INTO menus (menu_name, menu_content) VALUES (?, ?)",
            (menu_name, content)
        )
    
    conn.commit()
    conn.close()

# ==================== DATABASE HELPERS ====================
def get_user(telegram_id: int):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user(telegram_id: int, field: str, value):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
    conn.commit()
    conn.close()

def add_file(file_data: dict):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO files (file_name, file_type, file_id, category, description, uploader_id, uploader_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        file_data['file_name'], file_data['file_type'], file_data['file_id'],
        file_data['category'], file_data.get('description', ''),
        file_data['uploader_id'], file_data['uploader_name']
    ))
    conn.commit()
    file_id = cursor.lastrowid
    conn.close()
    return file_id

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - begin registration for all users"""
    user_id = update.effective_user.id
    
    # Check if user exists
    user = get_user(user_id)
    
    if user:
        if user[14]:  # is_blocked
            await update.message.reply_text("❌ You have been blocked from using this bot.")
            return ConversationHandler.END
        
        if not user[13]:  # is_approved
            await update.message.reply_text(
                "⏳ Your registration is pending admin approval. "
                "You'll be notified once approved."
            )
            return ConversationHandler.END
        
        # Show main menu for approved users
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    # New user - start registration
    await update.message.reply_text(
        "👋 Welcome to KUET EEE'24 Official Bot!\n\n"
        "📝 You need to register first. Please provide your information:\n\n"
        "What is your full name?"
    )
    return REG_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store name and ask for roll"""
    context.user_data['name'] = update.message.text
    await update.message.reply_text("🎓 What is your roll number?")
    return REG_ROLL

async def register_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store roll and ask for batch"""
    context.user_data['roll'] = update.message.text
    keyboard = [['2k24'], ['2k23'], ['2k22'], ['Other']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text("📅 Select your batch:", reply_markup=reply_markup)
    return REG_BATCH

async def register_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store batch and ask for gender"""
    context.user_data['batch'] = update.message.text
    keyboard = [['Male'], ['Female']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text("⚧ Select your gender:", reply_markup=reply_markup)
    return REG_GENDER

async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store gender and ask for phone number"""
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("📱 What is your phone number?")
    return REG_PHONE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store phone and ask for photo (optional for females)"""
    context.user_data['phone'] = update.message.text
    
    if context.user_data.get('gender') == 'Female':
        keyboard = [['Skip Photo'], ['Upload Photo']]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text(
            "👤 Photo upload is optional for female students.\n"
            "Choose an option:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("📷 Please upload your photo for batch profiles:")
    return REG_PHOTO

async def register_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo upload or skip"""
    if update.message.text == 'Skip Photo':
        context.user_data['photo_id'] = None
    elif update.message.photo:
        context.user_data['photo_id'] = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("Please upload a photo or choose 'Skip Photo'")
        return REG_PHOTO
    
    await update.message.reply_text(
        "🔗 Please provide your Facebook profile link:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REG_FB

async def register_fb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store FB link and ask for blood group"""
    context.user_data['fb_link'] = update.message.text
    
    keyboard = [['A+'], ['A-'], ['B+'], ['B-'], ['O+'], ['O-'], ['AB+'], ['AB-']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text("💉 What is your blood group?", reply_markup=reply_markup)
    return REG_BLOOD

async def register_blood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store blood group and ask for hometown"""
    context.user_data['blood_group'] = update.message.text
    await update.message.reply_text(
        "🏠 What is your hometown?",
        reply_markup=ReplyKeyboardRemove()
    )
    return REG_HOME

async def register_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store hometown and ask for email"""
    context.user_data['hometown'] = update.message.text
    await update.message.reply_text("📧 What is your email address?")
    return REG_EMAIL

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store email and complete registration"""
    context.user_data['email'] = update.message.text
    user_data = context.user_data
    
    # Save to database
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Auto-approve admin
    is_approved = 1 if update.effective_user.id == ADMIN_ID else 0
    role = 'admin' if update.effective_user.id == ADMIN_ID else 'user'
    
    cursor.execute("""
        INSERT INTO users (
            telegram_id, name, roll, batch, gender, phone,
            photo_id, fb_link, blood_group, hometown, email,
            is_approved, role
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        update.effective_user.id,
        user_data['name'],
        user_data['roll'],
        user_data['batch'],
        user_data['gender'],
        user_data['phone'],
        user_data.get('photo_id'),
        user_data['fb_link'],
        user_data['blood_group'],
        user_data['hometown'],
        user_data['email'],
        is_approved,
        role
    ))
    
    conn.commit()
    conn.close()
    
    # Notify admin about new registration (except for admin themselves)
    if update.effective_user.id != ADMIN_ID:
        admin_message = (
            "🆕 New User Registration\n\n"
            f"Name: {user_data['name']}\n"
            f"Roll: {user_data['roll']}\n"
            f"Batch: {user_data['batch']}\n"
            f"Gender: {user_data['gender']}\n\n"
            "Use /admin to approve or reject."
        )
        await context.bot.send_message(ADMIN_ID, admin_message)
    
    # Respond to user
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "✅ Registration complete! You have admin privileges.\n"
            "Use /admin to access admin panel."
        )
        await show_main_menu(update, context)
    else:
        await update.message.reply_text(
            "✅ Registration submitted!\n"
            "⏳ Waiting for admin approval. You'll be notified once approved."
        )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel registration"""
    await update.message.reply_text(
        "Registration cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu to approved users"""
    keyboard = [
        [InlineKeyboardButton("📁 File Storage", callback_data='file_storage')],
        [InlineKeyboardButton("👥 Batch Profiles", callback_data='batch_profiles')],
        [InlineKeyboardButton("📷 Photo Gallery", callback_data='photo_gallery')],
        [InlineKeyboardButton("💬 Batch Chat", callback_data='batch_chat')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')],
    ]
    
    # Add admin menu for admins
    user = get_user(update.effective_user.id)
    if user and user[12] in ['admin', 'co_admin']:  # role
        keyboard.append([InlineKeyboardButton("🛠 Admin Panel", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🏠 Main Menu\n\nSelect an option:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🏠 Main Menu\n\nSelect an option:",
            reply_markup=reply_markup
        )

# ==================== ADMIN FEATURES ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    user = get_user(update.effective_user.id)
    if not user or user[12] not in ['admin', 'co_admin']:
        await update.message.reply_text("❌ Admin access required.")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 Pending Approvals", callback_data='pending_users')],
        [InlineKeyboardButton("📁 Pending Files", callback_data='pending_files')],
        [InlineKeyboardButton("📊 Statistics", callback_data='stats')],
        [InlineKeyboardButton("➕ Add Menu", callback_data='add_menu')],
        [InlineKeyboardButton("🔧 Manage Users", callback_data='manage_users')],
        [InlineKeyboardButton("🏠 Back to Main", callback_data='main_menu')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🛠 Admin Panel\n\nSelect an option:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🛠 Admin Panel\n\nSelect an option:",
            reply_markup=reply_markup
        )

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'main_menu':
        await show_main_menu(update, context)
    
    elif query.data == 'admin_panel':
        await admin_panel(update, context)
    
    elif query.data == 'file_storage':
        await show_file_categories(update, context)
    
    elif query.data == 'batch_chat':
        await query.edit_message_text(
            "💬 Batch Chat Feature\n\n"
            "This feature allows batch 2k24 students to chat with each other.\n"
            "Coming soon with navigation features!"
        )
    
    # Add more callback handlers as needed

# ==================== FILE MANAGEMENT ====================
async def show_file_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show file categories for uploading/downloading"""
    keyboard = []
    for category in FILE_CATEGORIES:
        keyboard.append([InlineKeyboardButton(category, callback_data=f'category_{category}')])
    
    keyboard.append([InlineKeyboardButton("📤 Upload File", callback_data='upload_file')])
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data='main_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "📁 File Storage\n\nSelect a category:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "📁 File Storage\n\nSelect a category:",
            reply_markup=reply_markup
        )

# ==================== MAIN FUNCTION ====================
def main():
    """Start the bot"""
    # Initialize database
    init_database()
    
    # Create Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Registration conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REG_ROLL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_roll)],
            REG_BATCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_batch)],
            REG_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_gender)],
            REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            REG_PHOTO: [
                MessageHandler(filters.PHOTO, register_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_photo)
            ],
            REG_FB: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_fb)],
            REG_BLOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_blood)],
            REG_HOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_home)],
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(CallbackQueryHandler(handle_callbacks))
    
    # Start the bot with error handling for Render deployment
    # Use polling with error handling to avoid conflicts[citation:9]
    print("Bot is starting...")
    
    # Error handling wrapper[citation:4]
    async def poll_with_error_handling():
        try:
            await application.initialize()
            await application.start()
            await application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            
            # Keep the application running
            while True:
                await asyncio.sleep(3600)
                
        except Exception as e:
            print(f"Error occurred: {e}")
            # Wait and restart
            await asyncio.sleep(5)
            await poll_with_error_handling()
    
    # Start the bot with proper error handling
    import asyncio
    asyncio.run(poll_with_error_handling())

if __name__ == '__main__':
    main()
