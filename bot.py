import logging
import sqlite3
import threading
import os
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")  # Will be set in Render Environment Variables
ADMIN_ID = 5490832869
PORT = int(os.environ.get("PORT", 10000))

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DB_NAME = "kuet_eee24.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Users Table
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
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
        role TEXT DEFAULT 'pending',
        joined_date TEXT
    )""")
    
    # Files Table
    c.execute("""CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT,
        file_unique_id TEXT,
        file_type TEXT,
        category TEXT,
        caption TEXT,
        uploader_id INTEGER,
        status TEXT DEFAULT 'pending',
        upload_date TEXT
    )""")

    # Check if Super Admin exists in DB, if not, add/update
    c.execute("SELECT * FROM users WHERE user_id = ?", (ADMIN_ID,))
    if not c.fetchone():
        # Pre-register the super admin
        c.execute("""INSERT INTO users (user_id, name, roll, batch, role, joined_date) 
                     VALUES (?, 'Super Admin', '000000', 'Admin', 'admin', ?)""", 
                     (ADMIN_ID, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    else:
        c.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (ADMIN_ID,))
        
    conn.commit()
    conn.close()

# --- CONVERSATION STATES ---
(NAME, ROLL, BATCH, GENDER, PHONE, PHOTO, FB_LINK, BLOOD, HOMETOWN, EMAIL, CONFIRM) = range(11)
(UPLOAD_CATEGORY, UPLOAD_CONFIRM) = range(11, 13)

# --- HELPERS ---

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

async def is_admin(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return user and user['role'] in ['admin', 'co-admin']

async def is_approved(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return user and user['role'] not in ['pending', 'blocked']

async def get_main_menu_keyboard(user_id):
    keyboard = [
        ["📂 Browse Files", "📤 Upload File"],
        ["👥 Batch Profiles", "📸 Photo Gallery"],
        ["ℹ️ My Profile", "📞 Contact Admins"]
    ]
    
    conn = get_db_connection()
    user = conn.execute("SELECT batch, role FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()

    if user and user['batch'] == '2k24':
        keyboard.insert(0, ["💬 2k24 Batch Chat"])
    
    if user and user['role'] in ['admin', 'co-admin']:
        keyboard.append(["🛠 Admin Panel"])
        
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- REGISTRATION HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    db_user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()
    conn.close()

    if db_user:
        if db_user['role'] == 'blocked':
            await update.message.reply_text("⛔ You have been blocked from using this bot.")
            return
        if db_user['role'] == 'pending':
            await update.message.reply_text("⏳ Your registration is pending admin approval.")
            return
        
        await update.message.reply_text(f"Welcome back, {db_user['name']}!", reply_markup=await get_main_menu_keyboard(user.id))
    else:
        await update.message.reply_text(
            "🎓 **Welcome to KUET EEE'24 Bot**\n\nPlease register to access course materials and batch info.",
            parse_mode='Markdown'
        )
        await update.message.reply_text("Let's start! What is your **Full Name**?")
        return NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Got it. What is your **Roll Number**?")
    return ROLL

async def reg_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['roll'] = update.message.text
    reply_keyboard = [["2k24", "Other"]]
    await update.message.reply_text(
        "Which **Batch** do you belong to?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return BATCH

async def reg_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['batch'] = update.message.text
    reply_keyboard = [["Male", "Female"]]
    await update.message.reply_text(
        "Select your **Gender**:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return GENDER

async def reg_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender = update.message.text
    if gender not in ["Male", "Female"]:
        await update.message.reply_text("Please select Male or Female.")
        return GENDER
    context.user_data['gender'] = gender
    
    msg = "Please share your **Phone Number**."
    if gender == "Female":
        msg += "\n(🔒 Protected: Visible ONLY to Admins)"
    
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return PHONE

async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    # Photo Logic
    is_2k24 = context.user_data.get('batch') == '2k24'
    is_female = context.user_data.get('gender') == 'Female'
    
    if is_2k24:
        if is_female:
            await update.message.reply_text("📸 **Photo Upload** (Optional for Females).\nSend a photo or type 'skip'.")
            return PHOTO
        else:
            await update.message.reply_text("📸 **Photo Upload** (Required for 2k24).\nPlease send a clear photo of yourself.")
            return PHOTO
    else:
        context.user_data['photo_id'] = None
        await update.message.reply_text("🔗 What is your **Facebook Profile Link**?")
        return FB_LINK

async def reg_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['photo_id'] = update.message.photo[-1].file_id
    else:
        # Check if allowed to skip
        is_female = context.user_data.get('gender') == 'Female'
        if is_female and update.message.text.lower() == 'skip':
            context.user_data['photo_id'] = None
        else:
            await update.message.reply_text("❌ Photo is required for Male 2k24 students. Please upload a photo.")
            return PHOTO
            
    await update.message.reply_text("🔗 What is your **Facebook Profile Link**?")
    return FB_LINK

async def reg_fb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fb_link'] = update.message.text
    await update.message.reply_text("🩸 What is your **Blood Group**?")
    return BLOOD

async def reg_blood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['blood_group'] = update.message.text
    await update.message.reply_text("🏠 What is your **Home Town**?")
    return HOMETOWN

async def reg_town(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hometown'] = update.message.text
    await update.message.reply_text("📧 What is your **Email Address**?")
    return EMAIL

async def reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_data['email'] = update.message.text
    
    # Save to DB
    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO users 
            (user_id, name, roll, batch, gender, phone, photo_id, fb_link, blood_group, hometown, email, joined_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (update.effective_user.id, user_data['name'], user_data['roll'], user_data['batch'],
             user_data['gender'], user_data['phone'], user_data['photo_id'], user_data['fb_link'],
             user_data['blood_group'], user_data['hometown'], user_data['email'], 
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ You are already registered or an error occurred.")
        return ConversationHandler.END
    finally:
        conn.close()
        
    # Notify Admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 **New User Registration**\nName: {user_data['name']}\nRoll: {user_data['roll']}\nBatch: {user_data['batch']}\n\n/approve_user_{update.effective_user.id}",
        parse_mode='Markdown'
    )
    
    await update.message.reply_text("✅ Registration Complete! Please wait for Admin approval.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration canceled.")
    return ConversationHandler.END

# --- ADMIN HANDLERS ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return
        
    keyboard = [
        [InlineKeyboardButton("👥 Pending Users", callback_data="admin_users"),
         InlineKeyboardButton("📁 Pending Files", callback_data="admin_files")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")]
    ]
    await update.message.reply_text("👨‍💼 **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    conn = get_db_connection()
    
    if data == "admin_users":
        users = conn.execute("SELECT user_id, name, roll FROM users WHERE role = 'pending'").fetchall()
        if not users:
            await query.edit_message_text("✅ No pending users.")
        else:
            for u in users:
                keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"appr_u_{u['user_id']}"),
                             InlineKeyboardButton("❌ Reject", callback_data=f"rej_u_{u['user_id']}")]]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"👤 **Pending User**\nName: {u['name']}\nRoll: {u['roll']}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
    
    elif data == "admin_files":
        files = conn.execute("SELECT id, caption, category, uploader_id FROM files WHERE status = 'pending'").fetchall()
        if not files:
            await query.edit_message_text("✅ No pending files.")
        else:
            for f in files:
                uploader = conn.execute("SELECT name FROM users WHERE user_id = ?", (f['uploader_id'],)).fetchone()
                uploader_name = uploader['name'] if uploader else "Unknown"
                keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"appr_f_{f['id']}"),
                             InlineKeyboardButton("❌ Delete", callback_data=f"rej_f_{f['id']}")]]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"📄 **Pending File**\nCategory: {f['category']}\nCaption: {f['caption']}\nUploader: {uploader_name}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

    elif data == "admin_stats":
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM files WHERE status='approved'").fetchone()[0]
        await query.edit_message_text(f"📊 **Statistics**\n\nTotal Users: {user_count}\nTotal Files: {file_count}")

    conn.close()

async def approve_reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = get_db_connection()
    
    if data.startswith("appr_u_"):
        uid = int(data.split("_")[2])
        conn.execute("UPDATE users SET role = 'user' WHERE user_id = ?", (uid,))
        conn.commit()
        await context.bot.send_message(uid, "🎉 Your account has been approved! Use /start to see the menu.")
        await query.edit_message_text("User Approved.")
        
    elif data.startswith("rej_u_"):
        uid = int(data.split("_")[2])
        conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        conn.commit()
        await query.edit_message_text("User Rejected and Removed.")

    elif data.startswith("appr_f_"):
        fid = int(data.split("_")[2])
        conn.execute("UPDATE files SET status = 'approved' WHERE id = ?", (fid,))
        conn.commit()
        await query.edit_message_text("File Approved and Published.")
        
    elif data.startswith("rej_f_"):
        fid = int(data.split("_")[2])
        conn.execute("DELETE FROM files WHERE id = ?", (fid,))
        conn.commit()
        await query.edit_message_text("File Rejected and Deleted.")
        
    conn.close()

# --- FILE HANDLING ---

async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_approved(update.effective_user.id):
        await update.message.reply_text("🔒 Account not approved.")
        return ConversationHandler.END
        
    await update.message.reply_text("📤 Please send the File (Document, Photo, Video, or Audio).")
    return UPLOAD_CATEGORY

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = None
    file_type = ""
    
    if msg.document:
        file_obj = msg.document
        file_type = "document"
    elif msg.photo:
        file_obj = msg.photo[-1]
        file_type = "photo"
    elif msg.video:
        file_obj = msg.video
        file_type = "video"
    elif msg.audio:
        file_obj = msg.audio
        file_type = "audio"
    else:
        await update.message.reply_text("❌ Unsupported file type.")
        return ConversationHandler.END
        
    context.user_data['upload_file_id'] = file_obj.file_id
    context.user_data['upload_unique_id'] = file_obj.file_unique_id
    context.user_data['upload_type'] = file_type
    context.user_data['upload_caption'] = msg.caption or "No caption"
    
    cats = [
        [InlineKeyboardButton("Lectures", callback_data="cat_Lectures"), InlineKeyboardButton("Books", callback_data="cat_Books")],
        [InlineKeyboardButton("Notes", callback_data="cat_Notes"), InlineKeyboardButton("Assignments", callback_data="cat_Assignments")],
        [InlineKeyboardButton("Projects", callback_data="cat_Projects"), InlineKeyboardButton("Others", callback_data="cat_Others")],
        [InlineKeyboardButton("Album: Profiles", callback_data="cat_Album_Profiles"), InlineKeyboardButton("Album: Gallery", callback_data="cat_Album_Gallery")]
    ]
    await update.message.reply_text("📂 Select a Category:", reply_markup=InlineKeyboardMarkup(cats))
    return UPLOAD_CONFIRM

async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("_", 1)[1].replace("_", " ")
    
    conn = get_db_connection()
    conn.execute("""INSERT INTO files (file_id, file_unique_id, file_type, category, caption, uploader_id, upload_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (context.user_data['upload_file_id'], context.user_data['upload_unique_id'], 
         context.user_data['upload_type'], category, context.user_data['upload_caption'],
         update.effective_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"✅ File submitted to **{category}**. Waiting for Admin approval.", parse_mode='Markdown')
    
    # Notify Admin
    await context.bot.send_message(ADMIN_ID, f"🔔 **New File Uploaded**\nCategory: {category}\n/admin to review.")
    
    return ConversationHandler.END

# --- BROWSING ---

async def browse_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = [
        [InlineKeyboardButton("Lectures", callback_data="view_Lectures"), InlineKeyboardButton("Books", callback_data="view_Books")],
        [InlineKeyboardButton("Notes", callback_data="view_Notes"), InlineKeyboardButton("Assignments", callback_data="view_Assignments")],
        [InlineKeyboardButton("Projects", callback_data="view_Projects"), InlineKeyboardButton("Others", callback_data="view_Others")],
        [InlineKeyboardButton("Album: Profiles", callback_data="view_Album Profiles"), InlineKeyboardButton("Album: Gallery", callback_data="view_Album Gallery")]
    ]
    await update.message.reply_text("📂 **Browse Files**", reply_markup=InlineKeyboardMarkup(cats))

async def view_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("_", 1)[1]
    
    conn = get_db_connection()
    files = conn.execute("SELECT * FROM files WHERE category = ? AND status = 'approved' ORDER BY id DESC LIMIT 10", (category,)).fetchall()
    conn.close()
    
    if not files:
        await query.edit_message_text(f"📂 **{category}**\nNo files found.")
        return

    await query.message.reply_text(f"📂 **{category}** (Latest 10)")
    for f in files:
        caption = f"📄 {f['caption']}\n📅 {f['upload_date']}"
        if f['file_type'] == 'document':
            await context.bot.send_document(chat_id=query.message.chat_id, document=f['file_id'], caption=caption)
        elif f['file_type'] == 'photo':
            await context.bot.send_photo(chat_id=query.message.chat_id, photo=f['file_id'], caption=caption)
        elif f['file_type'] == 'video':
            await context.bot.send_video(chat_id=query.message.chat_id, video=f['file_id'], caption=caption)
        elif f['file_type'] == 'audio':
            await context.bot.send_audio(chat_id=query.message.chat_id, audio=f['file_id'], caption=caption)

# --- BATCH PROFILES & PRIVACY ---

async def batch_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Logic to show profiles
    # For demo, asking for Roll number
    await update.message.reply_text("🔍 Please reply with the **Roll Number** to search user.")

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    roll = update.message.text
    requester_id = update.effective_user.id
    
    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE roll = ?", (roll,)).fetchone()
    conn.close()
    
    if not target:
        # Check if it was a menu click or chat msg. If digits, assume search.
        if roll.isdigit(): 
            await update.message.reply_text("❌ User not found.")
        return

    # Privacy Check
    requester_is_admin = await is_admin(requester_id)
    phone = target['phone']
    if target['gender'] == 'Female' and not requester_is_admin:
        phone = "🔒 Hidden (Admin Only)"

    msg = (f"👤 **Student Profile**\n"
           f"Name: {target['name']}\n"
           f"Roll: {target['roll']}\n"
           f"Batch: {target['batch']}\n"
           f"Blood: {target['blood_group']}\n"
           f"Hometown: {target['hometown']}\n"
           f"Phone: {phone}\n"
           f"FB: {target['fb_link']}")
           
    if target['photo_id']:
        await update.message.reply_photo(target['photo_id'], caption=msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

# --- 2k24 CHAT FEATURE ---
async def chat_2k24(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    user = conn.execute("SELECT batch FROM users WHERE user_id = ?", (update.effective_user.id,)).fetchone()
    conn.close()
    
    if user and user['batch'] == '2k24':
        # In a real scenario, this would generate a temporary invite link or open a topic
        await update.message.reply_text("💬 **Batch 2k24 Exclusive**\n\nCreate a private Telegram Group and put the link here or use this as a discussion thread command.")
    else:
        await update.message.reply_text("⛔ This section is only for Batch 2k24.")

# --- FLASK SERVER (Keep Alive) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "KUET EEE'24 Bot is Running!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- MAIN ---

def main():
    if not TOKEN:
        print("Error: BOT_TOKEN is not set.")
        return

    init_db()
    
    application = Application.builder().token(TOKEN).build()

    # Conversation for Registration
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            ROLL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_roll)],
            BATCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_batch)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_gender)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)],
            PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, reg_photo)],
            FB_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_fb)],
            BLOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_blood)],
            HOMETOWN: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_town)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Conversation for File Upload
    upload_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📤 Upload File$"), upload_start)],
        states={
            UPLOAD_CATEGORY: [MessageHandler(filters.ATTACHMENT | filters.PHOTO, receive_file)],
            UPLOAD_CONFIRM: [CallbackQueryHandler(save_file, pattern="^cat_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(reg_conv)
    application.add_handler(upload_conv)
    
    # Admin Handlers
    application.add_handler(MessageHandler(filters.Regex("^🛠 Admin Panel$"), admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(approve_reject_handler, pattern="^(appr|rej)_"))
    
    # General Handlers
    application.add_handler(MessageHandler(filters.Regex("^📂 Browse Files$"), browse_menu))
    application.add_handler(CallbackQueryHandler(view_category, pattern="^view_"))
    application.add_handler(MessageHandler(filters.Regex("^👥 Batch Profiles$"), batch_profiles))
    application.add_handler(MessageHandler(filters.Regex("^💬 2k24 Batch Chat$"), chat_2k24))
    
    # Search Handler (catch-all text for rolls)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(📂|📤|👥|📸|ℹ️|📞|🛠|💬)"), search_handler))

    # Run Flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Bot
    application.run_polling()

if __name__ == '__main__':
    main()
