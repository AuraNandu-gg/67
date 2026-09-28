#!/usr/bin/env python3
"""AuraQuest — multiplayer trivia server (HTTP + WebSocket)."""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA_FILE = ROOT / "data.json"
HTTP_PORT = int(os.environ.get("PORT", "3000"))
WS_PORT = int(os.environ.get("WS_PORT", "3001"))

QUESTIONS = [
    {"q": "What is the largest planet in our solar system?", "a": ["Earth", "Jupiter", "Saturn", "Mars"], "c": 1},
    {"q": "How many continents are there on Earth?", "a": ["5", "6", "7", "8"], "c": 2},
    {"q": "What gas do plants absorb from the air?", "a": ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"], "c": 2},
    {"q": "Which animal is known as the King of the Jungle?", "a": ["Tiger", "Lion", "Elephant", "Bear"], "c": 1},
    {"q": "What is the capital of Japan?", "a": ["Seoul", "Beijing", "Tokyo", "Osaka"], "c": 2},
    {"q": "How many colors are in a rainbow?", "a": ["5", "6", "7", "8"], "c": 2},
    {"q": "Which ocean is the largest?", "a": ["Atlantic", "Indian", "Arctic", "Pacific"], "c": 3},
    {"q": "What do bees make?", "a": ["Milk", "Honey", "Silk", "Wax only"], "c": 1},
    {"q": "How many minutes are in an hour?", "a": ["30", "60", "90", "100"], "c": 1},
    {"q": "Which planet is closest to the Sun?", "a": ["Venus", "Earth", "Mercury", "Mars"], "c": 2},
    {"q": "What is H2O better known as?", "a": ["Salt", "Water", "Sugar", "Air"], "c": 1},
    {"q": "Which bird cannot fly?", "a": ["Eagle", "Penguin", "Sparrow", "Parrot"], "c": 1},
    {"q": "How many sides does a hexagon have?", "a": ["5", "6", "7", "8"], "c": 1},
    {"q": "What is the fastest land animal?", "a": ["Lion", "Horse", "Cheetah", "Leopard"], "c": 2},
    {"q": "Which country is home to the kangaroo?", "a": ["India", "Brazil", "Australia", "Kenya"], "c": 2},
    {"q": "What do you call a baby cat?", "a": ["Puppy", "Cub", "Kitten", "Calf"], "c": 2},
    {"q": "How many days are in a leap year?", "a": ["365", "366", "364", "360"], "c": 1},
    {"q": "Which instrument has 88 keys?", "a": ["Guitar", "Violin", "Piano", "Flute"], "c": 2},
    {"q": "What is the smallest prime number?", "a": ["0", "1", "2", "3"], "c": 2},
    {"q": "Which fruit is typically yellow and curved?", "a": ["Apple", "Banana", "Grape", "Orange"], "c": 1},
    {"q": "What organ pumps blood through the body?", "a": ["Lungs", "Brain", "Heart", "Liver"], "c": 2},
    {"q": "How many legs does a spider have?", "a": ["6", "8", "10", "4"], "c": 1},
    {"q": "Which season comes after winter?", "a": ["Summer", "Autumn", "Spring", "Monsoon"], "c": 2},
    {"q": "What is the tallest mountain on Earth?", "a": ["K2", "Everest", "Kilimanjaro", "Denali"], "c": 1},
    {"q": "Which shape has three sides?", "a": ["Square", "Circle", "Triangle", "Pentagon"], "c": 2},
]


def load_data():
    try:
        return json.loads(DATA_FILE.read_text())
    except Exception:
        return {"profiles": {}, "leaderboard": []}


def save_data():
    DATA_FILE.write_text(json.dumps(data, indent=2))


data = load_data()
online_names = set()
clients = {}  # ws -> {username, room}
rooms = {}


def ensure_profile(username):
    if username not in data["profiles"]:
        data["profiles"][username] = {
            "friends": [],
            "requestsIn": [],
            "requestsOut": [],
            "totalScore": 0,
            "gamesPlayed": 0,
            "bestScore": 0,
        }
    return data["profiles"][username]


def public_profile(username):
    p = ensure_profile(username)
    return {
        "username": username,
        "totalScore": p["totalScore"],
        "gamesPlayed": p["gamesPlayed"],
        "bestScore": p["bestScore"],
        "friends": list(p["friends"]),
        "requestsIn": list(p["requestsIn"]),
        "requestsOut": list(p["requestsOut"]),
    }


def make_code():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(random.choice(chars) for _ in range(5))
        if code not in rooms:
            return code


def room_public(room):
    return {
        "code": room["code"],
        "host": room["host"],
        "players": [
            {"username": n, "score": room["scores"].get(n, 0), "ready": bool(room["ready"].get(n))}
            for n in room["players"]
        ],
        "state": room["state"],
        "chat": room["chat"][-80:],
        "questionIndex": room["questionIndex"],
        "totalQuestions": len(room["questionOrder"]),
    }


async def send(ws, payload):
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass


async def send_user(username, payload):
    for ws, u in list(clients.items()):
        if u.get("username") == username:
            await send(ws, payload)


async def emit_room(room, payload=None):
    msg = payload or {"type": "room", "room": room_public(room)}
    for ws, u in list(clients.items()):
        if u.get("room") == room["code"]:
            await send(ws, msg)


def update_leaderboard(username):
    p = ensure_profile(username)
    found = None
    for e in data["leaderboard"]:
        if e["username"] == username:
            found = e
            break
    if found:
        found["totalScore"] = p["totalScore"]
        found["bestScore"] = p["bestScore"]
        found["gamesPlayed"] = p["gamesPlayed"]
    else:
        data["leaderboard"].append(
            {
                "username": username,
                "totalScore": p["totalScore"],
                "bestScore": p["bestScore"],
                "gamesPlayed": p["gamesPlayed"],
            }
        )
    data["leaderboard"].sort(key=lambda e: (-e["totalScore"], -e["bestScore"]))
    data["leaderboard"] = data["leaderboard"][:50]
    save_data()


async def leave_room(ws):
    u = clients.get(ws)
    if not u or not u.get("room"):
        return
    code = u["room"]
    room = rooms.get(code)
    u["room"] = None
    if not room:
        return
    if u["username"] in room["players"]:
        room["players"].remove(u["username"])
    room["ready"].pop(u["username"], None)
    room["chat"].append({"from": "System", "text": f"{u['username']} left the room.", "ts": 0})
    if not room["players"]:
        rooms.pop(code, None)
        return
    if room["host"] == u["username"]:
        room["host"] = room["players"][0]
    await emit_room(room)


def accept_friend(a, b):
    pa, pb = ensure_profile(a), ensure_profile(b)
    pa["requestsIn"] = [n for n in pa["requestsIn"] if n != b]
    pa["requestsOut"] = [n for n in pa["requestsOut"] if n != b]
    pb["requestsIn"] = [n for n in pb["requestsIn"] if n != a]
    pb["requestsOut"] = [n for n in pb["requestsOut"] if n != a]
    if b not in pa["friends"]:
        pa["friends"].append(b)
    if a not in pb["friends"]:
        pb["friends"].append(a)
    save_data()


async def next_question(room):
    room["questionIndex"] += 1
    room["answers"] = {}
    room["revealing"] = False
    if room["questionIndex"] >= len(room["questionOrder"]):
        await finish_game(room)
        return
    q = QUESTIONS[room["questionOrder"][room["questionIndex"]]]
    room["questionStarted"] = asyncio.get_event_loop().time()
    await emit_room(
        room,
        {
            "type": "question",
            "question": {
                "index": room["questionIndex"],
                "total": len(room["questionOrder"]),
                "q": q["q"],
                "a": q["a"],
                "seconds": 15,
            },
        },
    )
    await emit_room(room)
    room["task"] = asyncio.create_task(question_timer(room, room["questionIndex"]))


async def question_timer(room, idx):
    try:
        await asyncio.sleep(15)
        if rooms.get(room["code"]) is room and room["state"] == "playing" and room["questionIndex"] == idx:
            await reveal(room)
    except asyncio.CancelledError:
        return


async def reveal(room):
    if room["state"] != "playing" or room.get("revealing"):
        return
    room["revealing"] = True
    task = room.get("task")
    if task and not task.done():
        task.cancel()
    q = QUESTIONS[room["questionOrder"][room["questionIndex"]]]
    await emit_room(
        room,
        {"type": "reveal", "correct": q["c"], "answers": dict(room["answers"]), "scores": dict(room["scores"])},
    )
    await asyncio.sleep(3.5)
    if rooms.get(room["code"]) is room and room["state"] == "playing":
        await next_question(room)


async def finish_game(room):
    room["state"] = "results"
    ranking = sorted(
        [{"username": n, "score": room["scores"].get(n, 0)} for n in room["players"]],
        key=lambda x: -x["score"],
    )
    for n in room["players"]:
        p = ensure_profile(n)
        s = room["scores"].get(n, 0)
        p["totalScore"] += s
        p["gamesPlayed"] += 1
        if s > p["bestScore"]:
            p["bestScore"] = s
        update_leaderboard(n)
    save_data()
    room["chat"].append({"from": "System", "text": "Quest complete! Check the results.", "ts": 0})
    await emit_room(room, {"type": "results", "ranking": ranking, "scores": room["scores"]})
    await emit_room(room)
    await asyncio.sleep(12)
    if rooms.get(room["code"]) is room:
        room["state"] = "lobby"
        room["ready"] = {}
        room["questionIndex"] = -1
        await emit_room(room)


async def handle_msg(ws, msg):
    u = clients.get(ws)
    typ = msg.get("type")

    if typ == "register":
        username = str(msg.get("username") or "").strip()
        import re

        if not re.match(r"^[A-Za-z0-9 _]{3,16}$", username) or len(username.strip()) < 3:
            return await send(ws, {"type": "registered", "ok": False, "error": "Username must be 3–16 letters, numbers, spaces or _"})
        if username.lower() in online_names:
            return await send(ws, {"type": "registered", "ok": False, "error": "That username is already taken. Pick another!"})
        online_names.add(username.lower())
        clients[ws] = {"username": username, "room": None}
        ensure_profile(username)
        save_data()
        return await send(
            ws,
            {"type": "registered", "ok": True, "profile": public_profile(username), "leaderboard": data["leaderboard"]},
        )

    if not u or not u.get("username"):
        return await send(ws, {"type": "error", "error": "Register first"})

    if typ == "createRoom":
        if u["room"]:
            return await send(ws, {"type": "created", "ok": False, "error": "Leave your current room first"})
        code = make_code()
        room = {
            "code": code,
            "host": u["username"],
            "players": [u["username"]],
            "ready": {},
            "scores": {},
            "chat": [{"from": "System", "text": f"{u['username']} created the room. Share code {code}!", "ts": 0}],
            "state": "lobby",
            "questionOrder": [],
            "questionIndex": -1,
            "answers": {},
            "task": None,
        }
        rooms[code] = room
        u["room"] = code
        return await send(ws, {"type": "created", "ok": True, "room": room_public(room)})

    if typ == "joinRoom":
        code = str(msg.get("code") or "").upper().strip()
        room = rooms.get(code)
        if not room:
            return await send(ws, {"type": "joined", "ok": False, "error": "Room not found"})
        if room["state"] != "lobby":
            return await send(ws, {"type": "joined", "ok": False, "error": "Game already in progress"})
        if u["username"] in room["players"]:
            return await send(ws, {"type": "joined", "ok": False, "error": "Already in room"})
        if len(room["players"]) >= 8:
            return await send(ws, {"type": "joined", "ok": False, "error": "Room is full (max 8)"})
        if u["room"]:
            return await send(ws, {"type": "joined", "ok": False, "error": "Leave your current room first"})
        room["players"].append(u["username"])
        room["chat"].append({"from": "System", "text": f"{u['username']} joined the quest!", "ts": 0})
        u["room"] = code
        await emit_room(room)
        return await send(ws, {"type": "joined", "ok": True, "room": room_public(room)})

    if typ == "leaveRoom":
        await leave_room(ws)
        return

    if typ == "chat":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room:
            return
        text = str(msg.get("text") or "").strip()[:200]
        if not text:
            return
        room["chat"].append({"from": u["username"], "text": text, "ts": 0})
        await emit_room(room)
        return

    if typ == "ready":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["state"] != "lobby":
            return
        room["ready"][u["username"]] = bool(msg.get("ready"))
        await emit_room(room)
        return

    if typ == "startGame":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["host"] != u["username"] or room["state"] != "lobby":
            return
        order = list(range(len(QUESTIONS)))
        random.shuffle(order)
        room["questionOrder"] = order[:8]
        room["questionIndex"] = -1
        room["scores"] = {n: 0 for n in room["players"]}
        room["state"] = "playing"
        room["chat"].append({"from": "System", "text": "The quest begins! 8 questions — good luck!", "ts": 0})
        await next_question(room)
        return

    if typ == "answer":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["state"] != "playing":
            return
        if u["username"] in room["answers"]:
            return
        try:
            idx = int(msg.get("choice"))
        except Exception:
            return
        if idx < 0 or idx > 3:
            return
        room["answers"][u["username"]] = idx
        q = QUESTIONS[room["questionOrder"][room["questionIndex"]]]
        if idx == q["c"]:
            elapsed = asyncio.get_event_loop().time() - room["questionStarted"]
            bonus = max(0, 15 - int(elapsed))
            room["scores"][u["username"]] = room["scores"].get(u["username"], 0) + 10 + bonus
        await emit_room(room, {"type": "answerLock", "username": u["username"]})
        if len(room["answers"]) >= len(room["players"]):
            await reveal(room)
        return

    if typ == "friendRequest":
        target = str(msg.get("target") or "").strip()
        if not target or target == u["username"]:
            return
        if target not in data["profiles"]:
            return await send(ws, {"type": "toast", "text": "That player hasn't played AuraQuest yet."})
        me = ensure_profile(u["username"])
        them = ensure_profile(target)
        if target in me["friends"]:
            return await send(ws, {"type": "toast", "text": "You're already friends!"})
        if u["username"] in them["requestsIn"] or target in me["requestsOut"]:
            return await send(ws, {"type": "toast", "text": "Request already sent."})
        if target in me["requestsIn"]:
            accept_friend(u["username"], target)
            await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
            await send_user(target, {"type": "profile", "profile": public_profile(target)})
            await send_user(target, {"type": "toast", "text": f"{u['username']} accepted your friend request!"})
            await send(ws, {"type": "toast", "text": f"You and {target} are now friends!"})
            return
        me["requestsOut"].append(target)
        them["requestsIn"].append(u["username"])
        save_data()
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        await send_user(target, {"type": "toast", "text": f"{u['username']} sent you a friend request!"})
        await send(ws, {"type": "toast", "text": f"Friend request sent to {target}"})
        return

    if typ == "acceptFriend":
        target = str(msg.get("target") or "").strip()
        accept_friend(u["username"], target)
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        await send_user(target, {"type": "toast", "text": f"{u['username']} accepted your friend request!"})
        await send(ws, {"type": "toast", "text": f"You and {target} are now friends!"})
        return

    if typ == "declineFriend":
        target = str(msg.get("target") or "").strip()
        me = ensure_profile(u["username"])
        them = ensure_profile(target)
        me["requestsIn"] = [n for n in me["requestsIn"] if n != target]
        them["requestsOut"] = [n for n in them["requestsOut"] if n != u["username"]]
        save_data()
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        return

    if typ == "getLeaderboard":
        await send(ws, {"type": "leaderboard", "leaderboard": data["leaderboard"]})


async def handler(ws):
    clients[ws] = {}
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            try:
                await handle_msg(ws, msg)
            except Exception as e:
                await send(ws, {"type": "toast", "text": "Something went wrong."})
                print("handler error:", e)
    finally:
        u = clients.get(ws)
        if u:
            await leave_room(ws)
            if u.get("username"):
                online_names.discard(u["username"].lower())
        clients.pop(ws, None)


MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def file_response(path: Path, status=200, reason="OK"):
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    body = path.read_bytes() if path.is_file() else b"Not found"
    ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
    headers = Headers(
        {
            "Content-Type": ctype,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "Connection": "close",
        }
    )
    return Response(status, reason, headers, body)


async def process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path in ("/healthz", "/health"):
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        body = b"ok"
        return Response(200, "OK", Headers({"Content-Type": "text/plain", "Content-Length": str(len(body))}), body)
    if path in ("/ws", "/socket"):
        return None
    if path == "/":
        path = "/index.html"
    rel = path.lstrip("/")
    target = (PUBLIC / rel).resolve()
    try:
        target.relative_to(PUBLIC.resolve())
    except ValueError:
        return file_response(PUBLIC / "index.html", 404, "Not Found")
    if target.is_file():
        return file_response(target)
    return file_response(PUBLIC / "index.html", 404, "Not Found")


async def main():
    print(f"AuraQuest → http://localhost:{HTTP_PORT}")
    async with websockets.serve(
        handler,
        "0.0.0.0",
        HTTP_PORT,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
