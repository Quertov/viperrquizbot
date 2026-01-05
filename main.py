import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ================= НАСТРОЙКИ =================
TOKEN = "8122346611:AAH6_yMhtdraiQI-xCHJw4h8AratUHxfpok"
CHANNEL_USERNAME = "@viperrtest"
ADMIN_IDS = [947059513, 1474840147]

# ================= БАЗА ДАННЫХ =================
conn = sqlite3.connect("quiz_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER,
    question TEXT,
    answer TEXT,
    options TEXT,
    image TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    quiz_id INTEGER,
    score INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, quiz_id)
)
""")

conn.commit()

# ================= БОТ =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if member.status not in ["member", "administrator", "creator"]:
            raise Exception()
    except:
        await update.message.reply_text(
            f"❌ Подпишись на канал {CHANNEL_USERNAME}"
        )
        return

    cursor.execute("SELECT id, title FROM quizzes")
    quizzes = cursor.fetchall()

    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"quiz|{qid}")]
        for qid, title in quizzes
    ]

    await update.message.reply_text(
        "📚 Выбери квиз:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= КВИЗ =================

async def quiz_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    quiz_id = int(query.data.split("|")[1])
    context.user_data["quiz_id"] = quiz_id
    context.user_data["index"] = 0

    await send_question(query, context)


async def send_question(query, context):
    quiz_id = context.user_data["quiz_id"]
    index = context.user_data["index"]

    cursor.execute(
        "SELECT id, question, answer, options, image FROM questions WHERE quiz_id=? ORDER BY id LIMIT 1 OFFSET ?",
        (quiz_id, index)
    )

    row = cursor.fetchone()

    if not row:
        cursor.execute(
            "SELECT score FROM users WHERE user_id=? AND quiz_id=?",
            (query.from_user.id, context.user_data["quiz_id"])
        )
        result = cursor.fetchone()
        score = result[0] if result else 0

        await query.message.reply_text(
            f"🎉 Квиз завершён!\n\n"
            f"Ваш результат: {score} баллов"
        )
        return

    q_id, question, answer, options, image = row
    options = options.split(",")

    random.shuffle(options)

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"answer|{q_id}|{opt}")]
        for opt in options
    ]

    if image:
        await query.message.reply_photo(
            photo=image,
            caption=question,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.message.reply_text(
            question,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, q_id, selected = query.data.split("|")

    cursor.execute("SELECT answer FROM questions WHERE id=?", (q_id,))
    correct = cursor.fetchone()[0]

    if selected == correct:
        text = "✅ Верно!"
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, quiz_id, score) VALUES (?, ?, 0)",
            (query.from_user.id, context.user_data["quiz_id"])
        )
        cursor.execute(
            "UPDATE users SET score = score + 1 WHERE user_id=? AND quiz_id=?",
            (query.from_user.id, context.user_data["quiz_id"])
        )
    else:
        text = f"❌ Неверно! Ответ: {correct}"

    conn.commit()

    # безопасное редактирование сообщения
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(caption=text)
        else:
            await query.edit_message_text(text)
    except:
        # если сообщение уже нельзя редактировать — отправляем новое
        await query.message.reply_text(text)

    context.user_data["index"] += 1
    await send_question(query, context)
    
# ================= ЛИДЕРБОРД =================

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute(
        "SELECT user_id, SUM(score) as total_score "
        "FROM users "
        "GROUP BY user_id "
        "ORDER BY total_score DESC "
        "LIMIT 10"
    )
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("❌ Таблица лидеров пуста.")
        return

    text = "🏆 Общая таблица лидеров:\n\n"

    for i, (user_id, score) in enumerate(rows, 1):
        try:
            user = await context.bot.get_chat(user_id)
            name = user.full_name
        except:
            name = f"ID {user_id}"

        text += f"{i}. {name} — {score} баллов\n"

    await update.message.reply_text(text)


# ================= АДМИНКА =================

async def admin_add_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    title = " ".join(context.args)
    cursor.execute("INSERT INTO quizzes (title) VALUES (?)", (title,))
    conn.commit()

    await update.message.reply_text("✅ Квиз добавлен")


async def admin_add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    try:
        text = update.message.text
        parts = text.split(" ", 2)

        quiz_id = int(parts[1])
        data = parts[2]

        chunks = [x.strip() for x in data.split(",")]

        question = chunks[0]
        correct = chunks[1]
        options = ",".join(chunks[1:])

        cursor.execute(
            "INSERT INTO questions (quiz_id, question, answer, options) VALUES (?, ?, ?, ?)",
            (quiz_id, question, correct, options)
        )
        conn.commit()

        await update.message.reply_text("✅ Вопрос добавлен")

    except:
        await update.message.reply_text(
            "❌ Формат:\n"
            "/add_question 1 Вопрос,Ответ,Вариант1,Вариант2"
        )

async def admin_add_question_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    caption = update.message.caption
    if not caption or not caption.startswith("/add_question"):
        await update.message.reply_text(
            "❌ Подпись должна начинаться с команды:\n"
            "/add_question ID Вопрос,Ответ,Вариант1,Вариант2"
        )
        return

    try:
        # /add_question 3 Вопрос,Ответ,Вар1,Вар2,...
        parts = caption.split(" ", 2)
        if len(parts) < 3:
            raise ValueError("Неверный формат команды")

        quiz_id = int(parts[1].strip())
        data = parts[2].strip()

        chunks = [x.strip() for x in data.split(",") if x.strip()]
        if len(chunks) < 2:
            raise ValueError("Недостаточно данных")

        question = chunks[0]
        correct = chunks[1]
        options = ",".join(chunks[1:])  # варианты включают правильный

        photo = update.message.photo[-1]
        image = photo.file_id  # Telegram file_id

        cursor.execute(
            "INSERT INTO questions (quiz_id, question, answer, options, image) VALUES (?, ?, ?, ?, ?)",
            (quiz_id, question, correct, options, image)
        )
        conn.commit()

        await update.message.reply_text("✅ Вопрос с фото добавлен")

    except Exception as e:
        await update.message.reply_text(
            "❌ Ошибка добавления вопроса.\n\n"
            "Правильный формат:\n"
            "📷 + подпись:\n"
            "/add_question ID Вопрос,Ответ,Вариант1,Вариант2,Вариант3"
        )


# ================= ЗАПУСК =================

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(quiz_select, pattern=r"^quiz\|"))
app.add_handler(CallbackQueryHandler(answer_handler, pattern=r"^answer\|"))
app.add_handler(CommandHandler("add_quiz", admin_add_quiz))
app.add_handler(CommandHandler("add_question", admin_add_question))
app.add_handler(CommandHandler("leaderboard", show_leaderboard))
app.add_handler(
    MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r"^/add_question"),
        admin_add_question_photo
    )
)


app.run_polling()