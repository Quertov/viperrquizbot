import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue
)

# ================= НАСТРОЙКИ =================
TOKEN = "8122346611:AAH6_yMhtdraiQI-xCHJw4h8AratUHxfpok"
CHANNELS = ["@viperrtest", "@viperrtest2"]
ADMIN_IDS = [947059513, 1474840147]
QUESTION_TIME = 10      # секунд на вопрос
TIMER_ENABLED = True   # включён ли таймер

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

    not_subscribed = []

    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_subscribed.append(channel)
        except:
            not_subscribed.append(channel)

    if not_subscribed:
        text = "❌ Для использования бота подпишись на каналы:\n\n"
        for ch in not_subscribed:
            text += f"👉 {ch}\n"

        await update.message.reply_text(text)
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
        # запрет повторного прохождения квиза
    cursor.execute(
        "SELECT 1 FROM users WHERE user_id=? AND quiz_id=?",
        (query.from_user.id, quiz_id)
    )
    if cursor.fetchone():
        await query.message.reply_text(
            "❌ Вы уже проходили этот тест\n"
        )
        return
    context.user_data["quiz_id"] = quiz_id
    context.user_data["index"] = 0

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, quiz_id, score) VALUES (?, ?, 0)",
        (query.from_user.id, quiz_id)
    )
    conn.commit()

    await send_question(query, context)


async def send_question(query, context):
    user_id = query.from_user.id
    user_data = context.application.user_data.get(user_id)

    if not user_data:
        return

    quiz_id = user_data["quiz_id"]
    index = user_data["index"]

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
    images = image.split(",") if image else []

    random.shuffle(options)

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"answer|{q_id}|{opt}")]
        for opt in options
    ]

    if images:
        media = []

        caption = question
        if TIMER_ENABLED:
            caption += f"\n\n⏱ У вас {QUESTION_TIME} секунд на ответ"

        # первое фото — с вопросом
        media.append(
            InputMediaPhoto(
                media=images[0],
                caption=caption
            )
        )

        # остальные фото
        for img in images[1:]:
            media.append(InputMediaPhoto(media=img))

        # отправляем альбом
        await query.message.reply_media_group(media)

        # кнопки отправляем отдельным сообщением
        msg = await query.message.reply_text(
            "Выберите ответ:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.application.user_data[user_id]["last_buttons_msg"] = msg.message_id
    else:
        text = question
        if TIMER_ENABLED:
            text += f"\n\n⏱ У вас {QUESTION_TIME} секунд на ответ"

        msg = await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.application.user_data[user_id]["last_buttons_msg"] = msg.message_id

    # ⏱ запускаем таймер на вопрос
    if TIMER_ENABLED:
        context.job_queue.run_once(
            question_timeout,
            when=QUESTION_TIME,
            data={
                "query": query,
                "quiz_id": quiz_id,
                "index": index,
                "user_id": query.from_user.id
            }
        )

async def question_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    query = data["query"]
    quiz_id = data["quiz_id"]
    index = data["index"]
    user_id = data["user_id"]

    user_data = context.application.user_data.get(user_id)
    if not user_data:
        return

    # 🧹 удаляем старые кнопки
    msg_id = user_data.get("last_buttons_msg")
    if msg_id:
        try:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=msg_id
            )
        except:
            pass

    # если пользователь уже ответил — ничего не делаем
    if user_data.get("index") != index:
        return

    cursor.execute(
        "SELECT answer FROM questions WHERE quiz_id=? ORDER BY id LIMIT 1 OFFSET ?",
        (quiz_id, index)
    )
    row = cursor.fetchone()
    if not row:
        return

    correct = row[0]

    await query.message.reply_text(
        f"⏰ Время вышло!\nПравильный ответ: {correct}"
    )

    user_data["index"] += 1
    await send_question(query, context)

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ⛔ отменяем таймеры вопросов
    for job in context.job_queue.jobs():
        if job.callback == question_timeout:
            job.schedule_removal()

    user_id = update.effective_user.id
    user_data = context.application.user_data.get(user_id)

    if not user_data:
        return

    # 🧹 удаляем старые кнопки
    msg_id = user_data.get("last_buttons_msg")
    if msg_id:
        try:
            await context.bot.delete_message(
                chat_id=update.callback_query.message.chat_id,
                message_id=msg_id
            )
        except:
            pass

    query = update.callback_query
    await query.answer()

    _, q_id, selected = query.data.split("|")

    cursor.execute("SELECT answer FROM questions WHERE id=?", (q_id,))
    correct = cursor.fetchone()[0]

    if selected == correct:
        text = "✅ Верно!"
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, quiz_id, score) VALUES (?, ?, 0)",
            (query.from_user.id, user_data["quiz_id"])
        )
        cursor.execute(
            "UPDATE users SET score = score + 1 WHERE user_id=? AND quiz_id=?",
            (query.from_user.id, user_data["quiz_id"])
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

    user_data["index"] += 1
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

async def admin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    global QUESTION_TIME, TIMER_ENABLED

    if not context.args:
        status = "включён" if TIMER_ENABLED else "выключен"
        await update.message.reply_text(
            f"⏱ Таймер сейчас {status}\n"
            f"⏳ Время на вопрос: {QUESTION_TIME} сек\n\n"
            "Команды:\n"
            "/timer on\n"
            "/timer off\n"
            "/timer 15"
        )
        return

    arg = context.args[0].lower()

    if arg == "on":
        TIMER_ENABLED = True
        await update.message.reply_text("✅ Таймер включён")
    elif arg == "off":
        TIMER_ENABLED = False
        await update.message.reply_text("⛔ Таймер выключен")
    elif arg.isdigit():
        QUESTION_TIME = int(arg)
        await update.message.reply_text(
            f"⏱ Время на вопрос установлено: {QUESTION_TIME} сек"
        )
    else:
        await update.message.reply_text("❌ Неверная команда")

async def save_media_group(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    group_id = job_data["group_id"]

    groups = context.bot_data.get("media_groups", {})
    if group_id not in groups:
        return

    data = groups.pop(group_id)

    image = ",".join(data["images"])

    cursor.execute(
        "INSERT INTO questions (quiz_id, question, answer, options, image) VALUES (?, ?, ?, ?, ?)",
        (data["quiz_id"], data["question"], data["correct"], data["options"], image)
    )
    conn.commit()

    await context.bot.send_message(
        chat_id=data["chat_id"],
        text="✅ Вопрос с несколькими фото добавлен"
    )


async def admin_add_question_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    # если фото нет — это обычный текстовый вопрос
    if not update.message.photo:
        await admin_add_question(update, context)
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

        # берём ТОЛЬКО самое большое фото (последний элемент)
        photo = update.message.photo[-1]
        file_id = photo.file_id

        # media group (альбом)
        group_id = update.message.media_group_id

        if group_id:
            if "media_groups" not in context.bot_data:
                context.bot_data["media_groups"] = {}

            if group_id not in context.bot_data["media_groups"]:
                context.bot_data["media_groups"][group_id] = {
                    "quiz_id": quiz_id,
                    "question": question,
                    "correct": correct,
                    "options": options,
                    "images": [],
                    "chat_id": update.effective_chat.id
                }

                # запускаем таймер сохранения (1 секунда)
                context.job_queue.run_once(
                    save_media_group,
                    when=1.0,
                    data={"group_id": group_id},
                    name=str(group_id)
                )

            context.bot_data["media_groups"][group_id]["images"].append(file_id)
            return
        else:
            # одиночное фото
            image = file_id

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
app.add_handler(CommandHandler("timer", admin_timer))
app.add_handler(CommandHandler("leaderboard", show_leaderboard))
app.add_handler(
    MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r"^/add_question"),
        admin_add_question_photo
    )
)


app.run_polling()