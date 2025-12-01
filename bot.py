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
TOKEN = os.getenv("BOT_TOKEN") 
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

    # Check if Super Admin exists (Initial Dummy Setup)
    c.execute("SELECT * FROM users WHERE user_id = ?", (ADMIN_ID,))
    if not c.fetchone():
        c.execute("""INSERT INTO users (user_id, name, roll, batch, role, joined_date) 
                     VALUES (?, 'Super Admin', '000000', 'Admin', 'admin', ?)""", 
                     (ADMIN_ID, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    else:
        # Ensure ID 5490832869 is always admin
        c.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (ADMIN_ID,))
        
    conn.commit()
    conn.close()

# --- CONVERSATION STATES ---
(NAME, ROLL, BATCH, GENDER, PHONE, PHOTO, FB_LINK, BLOOD, HOMETOWN, EMAIL) = range(10)
(UPLOAD_CATEGORY, UPLOAD_CONFIRM) = range(10, 12)

# --- DATABASE HELPERS ---

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
        ["📂 My Files", "👥 Batch Profiles"],
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

# --- REGISTRATION & PROFILE HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    db_user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()
    conn.close()

    if db_user:
        if db_user['role'] == 'blocked':
            await update.message.reply_text("⛔ You are blocked.")
            return
        if db_user['role'] == 'pending':
            await update.message.reply_text("⏳ Registration pending approval.")
            return
        
        # Super Admin First Run Prompt
        if user.id == ADMIN_ID and db_user['name'] == 'Super Admin':
            await update.message.reply_text("👋 **Welcome Super Admin!**\nYour profile is currently empty. Please use /update_profile to register your real details (Photo, Name, Roll) so you appear correctly in the profiles.")
        
        await update.message.reply_text(f"Welcome back, {db_user['name']}!", reply_markup=await get_main_menu_keyboard(user.id))
    else:
        await update.message.reply_text("🎓 **Welcome to KUET EEE'24 Bot**\nLet's get you registered!", parse_mode='Markdown')
        await update.message.reply_text("What is your **Full Name**?")
        return NAME

async def update_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows Admin (or users) to re-register to fix details."""
    await update.message.reply_text("🔄 **Updating Profile**\nWhat is your **Full Name**? (Type /cancel to stop)")
    return NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("What is your **Roll Number**?")
    return ROLL

async def reg_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['roll'] = update.message.text
    reply_keyboard = [["2k24", "Other"]]
    await update.message.reply_text("Which **Batch**?", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return BATCH

async def reg_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['batch'] = update.message.text
    reply_keyboard = [["Male", "Female"]]
    await update.message.reply_text("Select **Gender**:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return GENDER

async def reg_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender = update.message.text
    if gender not in ["Male", "Female"]:
        await update.message.reply_text("Select Male or Female.")
        return GENDER
    context.user_data['gender'] = gender
    await update.message.reply_text("Share **Phone Number**:", reply_markup=ReplyKeyboardRemove())
    return PHONE

async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    # Logic: 2k24 needs photo. Admin needs photo.
    is_2k24 = context.user_data.get('batch') == '2k24'
    is_admin_user = (update.effective_user.id == ADMIN_ID)
    is_female = context.user_data.get('gender') == 'Female'
    
    msg = "📸 **Photo Upload**"
    if is_2k24 or is_admin_user:
        if is_female and not is_admin_user:
            msg += "\n(Optional for Females - Type 'skip' to pass)"
        else:
            msg += "\n(Required for 2k24/Admin)"
        
        await update.message.reply_text(msg)
        return PHOTO
    else:
        context.user_data['photo_id'] = None
        await update.message.reply_text("🔗 **Facebook Profile Link**?")
        return FB_LINK

async def reg_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['photo_id'] = update.message.photo[-1].file_id
    else:
        is_female = context.user_data.get('gender') == 'Female'
        # Admin cannot skip photo, Female users can
        if (is_female and update.message.text.lower() == 'skip' and update.effective_user.id != ADMIN_ID):
             context.user_data['photo_id'] = None
        else:
            await update.message.reply_text("❌ Photo required. Please upload.")
            return PHOTO
    await update.message.reply_text("🔗 **Facebook Profile Link**?")
    return FB_LINK

async def reg_fb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fb_link'] = update.message.text
    await update.message.reply_text("🩸 **Blood Group**?")
    return BLOOD

async def reg_blood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['blood_group'] = update.message.text
    await update.message.reply_text("🏠 **Home Town**?")
    return HOMETOWN

async def reg_town(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hometown'] = update.message.text
    await update.message.reply_text("📧 **Email Address**?")
    return EMAIL

async def reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_data['email'] = update.message.text
    uid = update.effective_user.id
    
    conn = get_db_connection()
    exists = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone()
    
    if exists:
        # UPDATE existing user (e.g., Admin fixing profile)
        conn.execute("""UPDATE users SET 
            name=?, roll=?, batch=?, gender=?, phone=?, photo_id=?, fb_link=?, blood_group=?, hometown=?, email=?
            WHERE user_id=?""",
            (user_data['name'], user_data['roll'], user_data['batch'], user_data['gender'], 
             user_data['phone'], user_data['photo_id'], user_data['fb_link'], user_data['blood_group'], 
             user_data['hometown'], user_data['email'], uid))
        msg = "✅ Profile Updated Successfully!"
        role = conn.execute("SELECT role FROM users WHERE user_id=?", (uid,)).fetchone()['role']
    else:
        # NEW Registration
        conn.execute("""INSERT INTO users 
            (user_id, name, roll, batch, gender, phone, photo_id, fb_link, blood_group, hometown, email, joined_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, user_data['name'], user_data['roll'], user_data['batch'],
             user_data['gender'], user_data['phone'], user_data['photo_id'], user_data['fb_link'],
             user_data['blood_group'], user_data['hometown'], user_data['email'], 
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        msg = "✅ Registration Complete! Waiting for Admin approval."
        role = 'pending'

    conn.commit()
    conn.close()
    
    if role == 'pending':
        await context.bot.send_message(ADMIN_ID, f"🔔 **New User**\n{user_data['name']}\n/admin to approve.")
    
    await update.message.reply_text(msg, reply_markup=await get_main_menu_keyboard(uid))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Action canceled.", reply_markup=await get_main_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

# --- FILE UPLOAD (With Cancel) ---

async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_approved(update.effective_user.id):
        await update.message.reply_text("🔒 Not approved.")
        return ConversationHandler.END
        
    await update.message.reply_text("📤 **Upload File**\nSend a Document, Photo, Video, or Audio.\n\n(Type /cancel to stop)")
    return UPLOAD_CATEGORY

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    # Check validity
    if not (msg.document or msg.photo or msg.video or msg.audio):
        await update.message.reply_text("❌ Invalid file. Send a file or /cancel.")
        return UPLOAD_CATEGORY

    if msg.document: file_obj, f_type = msg.document, "document"
    elif msg.photo: file_obj, f_type = msg.photo[-1], "photo"
    elif msg.video: file_obj, f_type = msg.video, "video"
    elif msg.audio: file_obj, f_type = msg.audio, "audio"
    
    context.user_data['up_fid'] = file_obj.file_id
    context.user_data['up_uid'] = file_obj.file_unique_id
    context.user_data['up_type'] = f_type
    context.user_data['up_cap'] = msg.caption or "No caption"
    
    cats = [
        [InlineKeyboardButton("Lectures", callback_data="cat_Lectures"), InlineKeyboardButton("Books", callback_data="cat_Books")],
        [InlineKeyboardButton("Notes", callback_data="cat_Notes"), InlineKeyboardButton("Assignments", callback_data="cat_Assignments")],
        [InlineKeyboardButton("Projects", callback_data="cat_Projects"), InlineKeyboardButton("Others", callback_data="cat_Others")],
        [InlineKeyboardButton("Album: Profiles", callback_data="cat_Album_Profiles"), InlineKeyboardButton("Album: Gallery", callback_data="cat_Album_Gallery")],
        [InlineKeyboardButton("❌ Cancel Upload", callback_data="cat_CANCEL")]
    ]
    await update.message.reply_text("📂 **Select Category**:", reply_markup=InlineKeyboardMarkup(cats))
    return UPLOAD_CONFIRM

async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "cat_CANCEL":
        await query.edit_message_text("❌ Upload canceled.")
        return ConversationHandler.END
        
    category = data.split("_", 1)[1].replace("_", " ")
    
    conn = get_db_connection()
    conn.execute("""INSERT INTO files (file_id, file_unique_id, file_type, category, caption, uploader_id, upload_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (context.user_data['up_fid'], context.user_data['up_uid'], context.user_data['up_type'], 
         category, context.user_data['up_cap'], update.effective_user.id, 
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"✅ Submitted to **{category}**. Pending Admin approval.")
    await context.bot.send_message(ADMIN_ID, f"🔔 **New File** in {category}\n/admin to review.")
    return ConversationHandler.END

# --- BROWSING & DELETING ---

async def browse_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = [
        [InlineKeyboardButton("Lectures", callback_data="view_Lectures"), InlineKeyboardButton("Books", callback_data="view_Books")],
        [InlineKeyboardButton("Notes", callback_data="view_Notes"), InlineKeyboardButton("Assignments", callback_data="view_Assignments")],
        [InlineKeyboardButton("Projects", callback_data="view_Projects"), InlineKeyboardButton("Others", callback_data="view_Others")],
        [InlineKeyboardButton("Album: Profiles", callback_data="view_Album Profiles"), InlineKeyboardButton("Album: Gallery", callback_data="view_Album Gallery")]
    ]
    await update.message.reply_text("📂 **Browse Files**", reply_markup=InlineKeyboardMarkup(cats))

async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's own files with delete option."""
    uid = update.effective_user.id
    conn = get_db_connection()
    files = conn.execute("SELECT id, caption, category, status FROM files WHERE uploader_id = ? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
    conn.close()
    
    if not files:
        await update.message.reply_text("📂 You haven't uploaded any files.")
        return

    await update.message.reply_text("📂 **My Uploads** (Tap Trash to Delete)")
    for f in files:
        status_icon = "✅" if f['status'] == 'approved' else "⏳"
        keyboard = [[InlineKeyboardButton("🗑 Delete", callback_data=f"del_own_{f['id']}")]]
        await update.message.reply_text(
            f"{status_icon} [{f['category']}] {f['caption']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

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

    is_adm = await is_admin(query.from_user.id)
    await query.message.reply_text(f"📂 **{category}** (Latest)")
    
    for f in files:
        caption = f"📄 {f['caption']}\n📅 {f['upload_date']}"
        # Admin gets a delete button on EVERY file
        keyboard = [[InlineKeyboardButton("🗑 Delete (Admin)", callback_data=f"del_adm_{f['id']}")]] if is_adm else None
        
        try:
            if f['file_type'] == 'document':
                await context.bot.send_document(query.message.chat_id, document=f['file_id'], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
            elif f['file_type'] == 'photo':
                await context.bot.send_photo(query.message.chat_id, photo=f['file_id'], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
            elif f['file_type'] == 'video':
                await context.bot.send_video(query.message.chat_id, video=f['file_id'], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
            elif f['file_type'] == 'audio':
                await context.bot.send_audio(query.message.chat_id, audio=f['file_id'], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        except Exception as e:
            logger.error(f"Error sending file: {e}")

async def delete_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = get_db_connection()
    
    if data.startswith("del_own_"):
        fid = data.split("_")[2]
        # Verify ownership
        file_rec = conn.execute("SELECT uploader_id FROM files WHERE id=?", (fid,)).fetchone()
        if file_rec and file_rec['uploader_id'] == query.from_user.id:
            conn.execute("DELETE FROM files WHERE id=?", (fid,))
            conn.commit()
            await query.edit_message_text("🗑 File deleted.")
        else:
            await query.edit_message_text("❌ Error: Not your file.")
            
    elif data.startswith("del_adm_"):
        if not await is_admin(query.from_user.id): return
        fid = data.split("_")[2]
        conn.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        await query.edit_message_text("🗑 File deleted by Admin.")
        
    conn.close()

# --- ADMIN PANEL ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    keyboard = [[InlineKeyboardButton("👥 Pending Users", callback_data="admin_users"), InlineKeyboardButton("📁 Pending Files", callback_data="admin_files")]]
    await update.message.reply_text("👨‍💼 **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = get_db_connection()
    
    if data == "admin_users":
        users = conn.execute("SELECT user_id, name, roll FROM users WHERE role = 'pending'").fetchall()
        if not users: await query.edit_message_text("✅ No pending users.")
        for u in users:
            k = [[InlineKeyboardButton("Approve", callback_data=f"appr_u_{u['user_id']}"), InlineKeyboardButton("Reject", callback_data=f"rej_u_{u['user_id']}")]]
            await context.bot.send_message(query.message.chat_id, f"👤 {u['name']} ({u['roll']})", reply_markup=InlineKeyboardMarkup(k))
            
    elif data == "admin_files":
        files = conn.execute("SELECT id, caption, category FROM files WHERE status = 'pending'").fetchall()
        if not files: await query.edit_message_text("✅ No pending files.")
        for f in files:
            k = [[InlineKeyboardButton("Approve", callback_data=f"appr_f_{f['id']}"), InlineKeyboardButton("Reject", callback_data=f"rej_f_{f['id']}")]]
            await context.bot.send_message(query.message.chat_id, f"📄 [{f['category']}] {f['caption']}", reply_markup=InlineKeyboardMarkup(k))
    conn.close()

async def decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, type_, id_ = data.split("_")
    conn = get_db_connection()
    
    if type_ == "u": # User
        if action == "appr":
            conn.execute("UPDATE users SET role='user' WHERE user_id=?", (id_,))
            try: await context.bot.send_message(id_, "🎉 Account Approved! /start to begin.")
            except: pass
            await query.edit_message_text("User Approved")
        else:
            conn.execute("DELETE FROM users WHERE user_id=?", (id_,))
            await query.edit_message_text("User Rejected")
            
    elif type_ == "f": # File
        if action == "appr":
            conn.execute("UPDATE files SET status='approved' WHERE id=?", (id_,))
            await query.edit_message_text("File Approved")
        else:
            conn.execute("DELETE FROM files WHERE id=?", (id_,))
            await query.edit_message_text("File Deleted")
    conn.commit()
    conn.close()

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    roll = update.message.text
    if not roll.isdigit(): return
    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE roll = ?", (roll,)).fetchone()
    conn.close()
    if target:
        is_adm = await is_admin(update.effective_user.id)
        phone = target['phone']
        if target['gender'] == 'Female' and not is_adm:
            phone = "🔒 Hidden"
            
        msg = f"👤 {target['name']}\nRoll: {target['roll']}\nBatch: {target['batch']}\nBlood: {target['blood_group']}\nHome: {target['hometown']}\nPhone: {phone}"
        if target['photo_id']: await update.message.reply_photo(target['photo_id'], caption=msg)
        else: await update.message.reply_text(msg)
    else: await update.message.reply_text("❌ Not found.")

# --- FLASK SERVER (Keep Alive) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- MAIN EXECUTABLE ---

def main():
    if not TOKEN:
        print("Error: BOT_TOKEN is not set.")
        return

    init_db()
    
    application = Application.builder().token(TOKEN).build()

    # Conversation: Registration & Update
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("update_profile", update_profile_command)],
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
    
    # Conversation: File Upload
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
    
    # Menus
    application.add_handler(MessageHandler(filters.Regex("^🛠 Admin Panel$"), admin_panel))
    application.add_handler(MessageHandler(filters.Regex("^📂 Browse Files$"), browse_menu))
    application.add_handler(MessageHandler(filters.Regex("^📂 My Files$"), my_files))
    
    # Callbacks
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(decision_handler, pattern="^(appr|rej)_"))
    application.add_handler(CallbackQueryHandler(delete_file_handler, pattern="^del_"))
    application.add_handler(CallbackQueryHandler(view_category, pattern="^view_"))
    
    # Search / Text Handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler))

    # Run Flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Bot
    application.run_polling()

if __name__ == '__main__':
    main()
