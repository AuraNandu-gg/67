const proto = location.protocol === "https:" ? "wss:" : "ws:";
const socketUrl = `${proto}//${location.host}/ws`;

const pending = {};

function handleMessage(msg) {
  const t = msg.type;
  if (t === "registered" && pending.register) pending.register(msg);
  if (t === "created" && pending.create) pending.create(msg);
  if (t === "joined" && pending.join) pending.join(msg);
  if (t === "room") {
    state.room = msg.room;
    if (msg.room.state === "lobby" && state.screen !== "lobby") showLobby();
    else if (state.screen === "lobby") showLobby();
    else if (state.screen === "game") refreshChatOnly();
  }
  if (t === "question") {
    state.question = msg.question;
    state.picked = null;
    state.reveal = null;
    state.results = null;
    showGame();
  }
  if (t === "reveal") {
    state.reveal = msg;
    if (state.room) {
      state.room.players.forEach((p) => {
        if (msg.scores[p.username] != null) p.score = msg.scores[p.username];
      });
    }
    showGame();
  }
  if (t === "results") {
    state.results = msg;
    showResults();
  }
  if (t === "profile") {
    state.profile = msg.profile;
    if (state.screen === "home") showHome();
    if (state.screen === "lobby") showLobby();
  }
  if (t === "leaderboard") state.leaderboard = msg.leaderboard || [];
  if (t === "toast") toast(msg.text);
}

function makeSock() {
  const ws = new WebSocket(socketUrl);
  ws.onmessage = (ev) => {
    try {
      handleMessage(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  ws.onopen = () => {
    if (state.username && state.screen !== "gate") {
      socket.send({ type: "register", username: state.username });
    }
  };
  ws.onclose = () => setTimeout(() => socket._reconnect(), 1200);
  return ws;
}

const socket = {
  ws: null,
  send(obj) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj));
  },
  emit(type, a, b) {
    if (type === "register") {
      pending.register = b;
      this.send({ type: "register", username: a });
    } else if (type === "createRoom") {
      pending.create = a;
      this.send({ type: "createRoom" });
    } else if (type === "joinRoom") {
      pending.join = b;
      this.send({ type: "joinRoom", code: a });
    } else if (type === "leaveRoom") this.send({ type: "leaveRoom" });
    else if (type === "chat") this.send({ type: "chat", text: a });
    else if (type === "ready") this.send({ type: "ready", ready: a });
    else if (type === "startGame") this.send({ type: "startGame" });
    else if (type === "answer") this.send({ type: "answer", choice: a });
    else if (type === "friendRequest") this.send({ type: "friendRequest", target: a });
    else if (type === "acceptFriend") this.send({ type: "acceptFriend", target: a });
    else if (type === "declineFriend") this.send({ type: "declineFriend", target: a });
    else if (type === "getLeaderboard") this.send({ type: "getLeaderboard" });
  },
  _reconnect() {
    this.ws = makeSock();
  },
};
socket.ws = makeSock();

const app = document.getElementById("app");
const topUser = document.getElementById("topUser");
const topName = document.getElementById("topName");

const state = {
  username: null,
  profile: null,
  leaderboard: [],
  room: null,
  screen: "gate",
  question: null,
  picked: null,
  reveal: null,
  results: null,
};

document.getElementById("btnHome").onclick = () => {
  if (state.room) socket.emit("leaveRoom");
  state.room = null;
  state.question = null;
  state.results = null;
  showHome();
};

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

showGate();

function showGate() {
  state.screen = "gate";
  topUser.hidden = true;
  app.innerHTML = `
    <section class="hero">
      <h1>Play trivia with friends.<br/><span>No login. Just a name.</span></h1>
      <p class="lead">Create a room, share the code, chat, add friends, and climb the leaderboard.</p>
    </section>
    <div class="card gate">
      <h2>Choose your username</h2>
      <p class="hint mb">3–16 characters. Must be unique while you're online.</p>
      <input id="nameIn" maxlength="16" placeholder="e.g. NovaKid" autocomplete="nickname" />
      <div class="error" id="gateErr"></div>
      <button class="primary mt" id="enterBtn" style="width:100%">Enter AuraQuest</button>
    </div>
  `;
  const input = document.getElementById("nameIn");
  input.focus();
  const go = () => {
    const name = input.value.trim();
    document.getElementById("gateErr").textContent = "";
    if (!socket.ws || socket.ws.readyState !== 1) {
      document.getElementById("gateErr").textContent = "Connecting to server… try again in a second.";
      return;
    }
    socket.emit("register", name, (res) => {
      if (!res.ok) {
        document.getElementById("gateErr").textContent = res.error;
        return;
      }
      state.username = name;
      state.profile = res.profile;
      state.leaderboard = res.leaderboard || [];
      topName.textContent = name;
      topUser.hidden = false;
      showHome();
    });
  };
  document.getElementById("enterBtn").onclick = go;
  input.addEventListener("keydown", (e) => e.key === "Enter" && go());
}

function showHome() {
  state.screen = "home";
  const p = state.profile || { totalScore: 0, gamesPlayed: 0, bestScore: 0, friends: [], requestsIn: [] };
  const lb = state.leaderboard || [];
  app.innerHTML = `
    <section class="hero" style="padding-top:12px">
      <h1>Welcome, <span>${esc(state.username)}</span></h1>
      <p class="lead">Invite friends with a room code. First time? Create a room and send the code.</p>
    </section>
    <div class="stat-row">
      <div class="stat"><b>${p.totalScore}</b><span>Total points</span></div>
      <div class="stat"><b>${p.bestScore}</b><span>Best game</span></div>
      <div class="stat"><b>${p.gamesPlayed}</b><span>Games played</span></div>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <h2>Play together</h2>
        <div class="row">
          <button class="primary" id="createBtn">Create room</button>
        </div>
        <p class="hint mt">Or join a friend's room</p>
        <div class="row mt">
          <input id="codeIn" maxlength="5" placeholder="ROOM CODE" style="text-transform:uppercase;flex:1" />
          <button class="teal" id="joinBtn">Join</button>
        </div>
        <div class="error" id="homeErr"></div>
      </div>
      <div class="card">
        <h2>Friends</h2>
        ${p.requestsIn && p.requestsIn.length ? `<p class="hint mb">${p.requestsIn.length} pending request(s)</p>` : ""}
        <div class="list" id="friendList">
          ${
            p.friends && p.friends.length
              ? p.friends.map((f) => `<div class="item"><span class="who">${esc(f)}</span><span class="badge">Friend</span></div>`).join("")
              : `<p class="hint">No friends yet. Add players from a room.</p>`
          }
        </div>
        ${(p.requestsIn || [])
          .map(
            (n) => `
          <div class="item mt">
            <span class="who">${esc(n)}</span>
            <div class="row">
              <button class="teal" data-accept="${esc(n)}">Accept</button>
              <button class="ghost" data-decline="${esc(n)}">No</button>
            </div>
          </div>`
          )
          .join("")}
        <div class="row mt">
          <input id="friendIn" placeholder="Add by username" />
          <button class="ghost" id="addFriendBtn">Add</button>
        </div>
      </div>
    </div>
    <div class="card mt">
      <h2>Leaderboard</h2>
      <div class="list">
        ${
          lb.length
            ? lb
                .slice(0, 10)
                .map(
                  (e, i) => `
                  <div class="item rank ${i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : ""}">
                    <div style="display:flex;align-items:center;gap:12px">
                      <span class="pos">${i + 1}</span>
                      <span class="who">${esc(e.username)}</span>
                    </div>
                    <span>${e.totalScore} pts · best ${e.bestScore}</span>
                  </div>`
                )
                .join("")
            : `<p class="hint">Play a game to appear here.</p>`
        }
      </div>
    </div>
  `;
  document.getElementById("createBtn").onclick = () => {
    socket.emit("createRoom", (res) => {
      if (!res.ok) return (document.getElementById("homeErr").textContent = res.error);
      state.room = res.room;
      showLobby();
    });
  };
  document.getElementById("joinBtn").onclick = joinCode;
  document.getElementById("codeIn").addEventListener("keydown", (e) => e.key === "Enter" && joinCode());
  document.getElementById("addFriendBtn").onclick = () => {
    const n = document.getElementById("friendIn").value.trim();
    if (n) socket.emit("friendRequest", n);
  };
  app.querySelectorAll("[data-accept]").forEach((b) => (b.onclick = () => socket.emit("acceptFriend", b.dataset.accept)));
  app.querySelectorAll("[data-decline]").forEach((b) => (b.onclick = () => socket.emit("declineFriend", b.dataset.decline)));
}

function joinCode() {
  const code = document.getElementById("codeIn").value;
  socket.emit("joinRoom", code, (res) => {
    if (!res.ok) return (document.getElementById("homeErr").textContent = res.error);
    state.room = res.room;
    showLobby();
  });
}

function showLobby() {
  state.screen = "lobby";
  const r = state.room;
  if (!r) return showHome();
  const p = state.profile || { friends: [], requestsOut: [] };
  const isHost = r.host === state.username;
  app.innerHTML = `
    <div class="grid grid-2">
      <div class="card">
        <h2>Room ${esc(r.code)}</h2>
        <p class="hint mb">Share this code so friends can join.</p>
        <div class="row mb">
          <button class="teal" id="copyBtn">Copy invite code</button>
          <button class="ghost" id="leaveBtn">Leave</button>
        </div>
        <div class="list">
          ${r.players
            .map((pl) => {
              const mine = pl.username === state.username;
              const friend = (p.friends || []).includes(pl.username);
              return `<div class="item">
                <div>
                  <span class="who">${esc(pl.username)}</span>
                  ${pl.username === r.host ? `<span class="badge host">Host</span>` : ""}
                  ${pl.ready ? `<span class="badge ready">Ready</span>` : ""}
                </div>
                <div class="row">
                  ${
                    mine
                      ? ""
                      : friend
                      ? `<span class="badge">Friend</span>`
                      : `<button class="ghost" data-add="${esc(pl.username)}">Add friend</button>`
                  }
                </div>
              </div>`;
            })
            .join("")}
        </div>
        <div class="row mt">
          <button class="ghost" id="readyBtn">${r.players.find((x) => x.username === state.username)?.ready ? "Unready" : "I'm ready"}</button>
          ${isHost ? `<button class="primary" id="startBtn">Start quest</button>` : `<span class="hint">Waiting for host…</span>`}
        </div>
      </div>
      ${chatBox(r)}
    </div>
  `;
  bindChat(r);
  document.getElementById("copyBtn").onclick = async () => {
    try {
      await navigator.clipboard.writeText(r.code);
      toast("Code copied: " + r.code);
    } catch {
      toast("Code: " + r.code);
    }
  };
  document.getElementById("leaveBtn").onclick = () => {
    socket.emit("leaveRoom");
    state.room = null;
    socket.emit("getLeaderboard");
    setTimeout(showHome, 150);
  };
  document.getElementById("readyBtn").onclick = () => {
    const me = r.players.find((x) => x.username === state.username);
    socket.emit("ready", !(me && me.ready));
  };
  const start = document.getElementById("startBtn");
  if (start) start.onclick = () => socket.emit("startGame");
  app.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => socket.emit("friendRequest", b.dataset.add)));
}

function chatBox(r) {
  return `
    <div class="card">
      <h2>Chat</h2>
      <div class="chat">
        <div class="chat-log" id="chatLog">
          ${(r.chat || [])
            .map((m) =>
              m.from === "System"
                ? `<div class="msg system">${esc(m.text)}</div>`
                : `<div class="msg"><span class="from">${esc(m.from)}</span>${esc(m.text)}</div>`
            )
            .join("")}
        </div>
        <form class="chat-form" id="chatForm">
          <input id="chatIn" maxlength="200" placeholder="Say something…" autocomplete="off" />
          <button class="primary" type="submit">Send</button>
        </form>
      </div>
    </div>`;
}

function bindChat() {
  const log = document.getElementById("chatLog");
  if (log) log.scrollTop = log.scrollHeight;
  const form = document.getElementById("chatForm");
  if (form) {
    form.onsubmit = (e) => {
      e.preventDefault();
      const input = document.getElementById("chatIn");
      const t = input.value.trim();
      if (t) socket.emit("chat", t);
      input.value = "";
    };
  }
}

function refreshChatOnly() {
  const log = document.getElementById("chatLog");
  if (!log || !state.room) return;
  log.innerHTML = (state.room.chat || [])
    .map((m) =>
      m.from === "System"
        ? `<div class="msg system">${esc(m.text)}</div>`
        : `<div class="msg"><span class="from">${esc(m.from)}</span>${esc(m.text)}</div>`
    )
    .join("");
  log.scrollTop = log.scrollHeight;
}

function showGame() {
  state.screen = "game";
  const q = state.question;
  const r = state.room;
  if (!q) return;
  const letters = ["A", "B", "C", "D"];
  const revealed = !!state.reveal;
  app.innerHTML = `
    <div class="grid grid-2">
      <div class="card question-card">
        <div class="q-meta">Question ${q.index + 1} / ${q.total}</div>
        <h2>${esc(q.q)}</h2>
        <div class="timer">${revealed ? "" : "<i></i>"}</div>
        <div class="choices" id="choices">
          ${q.a
            .map((ans, i) => {
              let cls = "";
              if (state.picked === i) cls += " picked";
              if (revealed && state.reveal.correct === i) cls += " correct";
              if (revealed && state.picked === i && state.reveal.correct !== i) cls += " wrong";
              return `<button data-i="${i}" class="${cls}" ${revealed || state.picked != null ? "disabled" : ""}>${letters[i]}. ${esc(ans)}</button>`;
            })
            .join("")}
        </div>
        ${
          revealed
            ? `<p class="hint mt">Correct answer highlighted. Next question coming up…</p>`
            : state.picked != null
            ? `<p class="hint mt">Locked in. Waiting for others…</p>`
            : ""
        }
      </div>
      <div>
        <div class="card mb">
          <h2>Scores</h2>
          <div class="list">
            ${(r ? r.players : [])
              .slice()
              .sort((a, b) => (b.score || 0) - (a.score || 0))
              .map((pl) => `<div class="item"><span class="who">${esc(pl.username)}</span><b>${pl.score || 0}</b></div>`)
              .join("")}
          </div>
        </div>
        ${r ? chatBox(r) : ""}
      </div>
    </div>
  `;
  bindChat();
  if (!revealed && state.picked == null) {
    app.querySelectorAll("#choices button").forEach((b) => {
      b.onclick = () => {
        state.picked = Number(b.dataset.i);
        socket.emit("answer", state.picked);
        showGame();
      };
    });
  }
}

function showResults() {
  state.screen = "results";
  const ranking = state.results?.ranking || [];
  app.innerHTML = `
    <section class="hero">
      <h1>Quest <span>complete</span></h1>
      <p class="lead">Nice work. Returning to the lobby shortly so you can play again.</p>
    </section>
    <div class="card">
      <h2>Final standings</h2>
      <div class="list">
        ${ranking
          .map(
            (e, i) => `
          <div class="item rank ${i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : ""}">
            <div style="display:flex;align-items:center;gap:12px">
              <span class="pos">${i + 1}</span>
              <span class="who">${esc(e.username)}${e.username === state.username ? " (you)" : ""}</span>
            </div>
            <b>${e.score} pts</b>
          </div>`
          )
          .join("")}
      </div>
    </div>
  `;
}
