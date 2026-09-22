from fastapi import FastAPI, Response, Cookie, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pwdlib import PasswordHash
import sqlite3
import secrets

app = FastAPI()

password_hash = PasswordHash.recommended()


def get_db():
    return sqlite3.connect("messenger.db")


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            username TEXT NOT NULL,
            receiver TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)

    try:
        db.execute(
            "ALTER TABLE messages ADD COLUMN receiver TEXT"
        )
    except sqlite3.OperationalError:
        pass

    db.commit()
    db.close()


class User(BaseModel):
    username: str
    password: str


class Message(BaseModel):
    text: str
    receiver: str


init_db()


# =========================
# WebSocket connections
# =========================

active_connections = {}


async def send_to_user(username, message):
    websocket = active_connections.get(username)

    if websocket:
        try:
            await websocket.send_json(message)
        except Exception:
            active_connections.pop(username, None)


# =========================
# Main page
# =========================

@app.get("/")
def home():
    return FileResponse("index.html")


# =========================
# Register
# =========================

@app.post("/register")
def register(user: User, response: Response):
    db = get_db()

    hashed_password = password_hash.hash(user.password)

    try:
        cursor = db.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (user.username, hashed_password)
        )
        db.commit()
        user_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        db.close()
        return {"error": "Такой пользователь уже существует"}

    token = secrets.token_urlsafe(32)

    db.execute(
        "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
        (token, user_id)
    )

    db.commit()
    db.close()

    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30
    )

    return {
        "id": user_id,
        "username": user.username
    }


# =========================
# Login
# =========================

@app.post("/login")
def login(user: User, response: Response):
    db = get_db()

    row = db.execute(
        "SELECT id, username, password FROM users WHERE username = ?",
        (user.username,)
    ).fetchone()

    if row is None:
        db.close()
        return {"error": "Пользователь не найден"}

    if not password_hash.verify(user.password, row[2]):
        db.close()
        return {"error": "Неверный пароль"}

    token = secrets.token_urlsafe(32)

    db.execute(
        "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
        (token, row[0])
    )

    db.commit()
    db.close()

    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30
    )

    return {
        "id": row[0],
        "username": row[1]
    }


# =========================
# Logout
# =========================

@app.post("/logout")
def logout(
    response: Response,
    session: str | None = Cookie(default=None)
):
    if session:
        db = get_db()

        db.execute(
            "DELETE FROM sessions WHERE token = ?",
            (session,)
        )

        db.commit()
        db.close()

    response.delete_cookie("session")

    return {"success": True}


# =========================
# Current user
# =========================

@app.get("/me")
def get_current_user(
    session: str | None = Cookie(default=None)
):
    if not session:
        return {"error": "Не авторизован"}

    db = get_db()

    row = db.execute("""
        SELECT users.id, users.username
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
    """, (session,)).fetchone()

    db.close()

    if row is None:
        return {"error": "Не авторизован"}

    return {
        "id": row[0],
        "username": row[1]
    }


# =========================
# Users
# =========================

@app.get("/users")
def get_users():
    db = get_db()

    rows = db.execute(
        "SELECT id, username FROM users ORDER BY username"
    ).fetchall()

    db.close()

    return [
        {
            "id": row[0],
            "username": row[1]
        }
        for row in rows
    ]


# =========================
# Get messages
# =========================

@app.get("/messages")
def get_messages(
    receiver: str,
    session: str | None = Cookie(default=None)
):
    if not session:
        return {"error": "Не авторизован"}

    db = get_db()

    user = db.execute("""
        SELECT users.username
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
    """, (session,)).fetchone()

    if user is None:
        db.close()
        return {"error": "Не авторизован"}

    current_username = user[0]

    rows = db.execute("""
        SELECT id, text, username, receiver
        FROM messages
        WHERE
            (username = ? AND receiver = ?)
            OR
            (username = ? AND receiver = ?)
        ORDER BY id
    """, (
        current_username,
        receiver,
        receiver,
        current_username
    )).fetchall()

    db.close()

    return [
        {
            "id": row[0],
            "text": row[1],
            "username": row[2],
            "receiver": row[3]
        }
        for row in rows
    ]


# =========================
# Send message
# =========================

@app.post("/messages")
async def send_message(
    message: Message,
    session: str | None = Cookie(default=None)
):
    if not session:
        return {"error": "Не авторизован"}

    db = get_db()

    user = db.execute("""
        SELECT users.username
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
    """, (session,)).fetchone()

    if user is None:
        db.close()
        return {"error": "Не авторизован"}

    current_username = user[0]

    receiver_exists = db.execute(
        "SELECT id FROM users WHERE username = ?",
        (message.receiver,)
    ).fetchone()

    if receiver_exists is None:
        db.close()
        return {"error": "Пользователь не найден"}

    cursor = db.execute("""
        INSERT INTO messages
        (text, username, receiver)
        VALUES (?, ?, ?)
    """, (
        message.text,
        current_username,
        message.receiver
    ))

    db.commit()

    message_id = cursor.lastrowid

    db.close()

    new_message = {
        "id": message_id,
        "text": message.text,
        "username": current_username,
        "receiver": message.receiver
    }

    # Отправляем сообщение получателю сразу через WebSocket
    await send_to_user(message.receiver, new_message)

    # Отправляем его также отправителю,
    # чтобы его интерфейс сразу обновился
    await send_to_user(current_username, new_message)

    return new_message


# =========================
# WebSocket
# =========================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session: str | None = Cookie(default=None)
):
    if not session:
        await websocket.close(code=1008)
        return

    db = get_db()

    user = db.execute("""
        SELECT users.username
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
    """, (session,)).fetchone()

    db.close()

    if user is None:
        await websocket.close(code=1008)
        return

    username = user[0]

    await websocket.accept()

    active_connections[username] = websocket

    print(f"WebSocket подключён: {username}")

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        if active_connections.get(username) is websocket:
            active_connections.pop(username, None)

        print(f"WebSocket отключён: {username}")

    except Exception:
        if active_connections.get(username) is websocket:
            active_connections.pop(username, None)