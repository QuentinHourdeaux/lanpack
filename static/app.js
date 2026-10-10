"use strict";
const $ = (selector) => document.querySelector(selector);
let state = null;
let editing = null;
let removing = null;
let lastCards = "";
let toastTimer;
let refreshing = null;

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 3500);
}

async function api(path, method = "GET", data) {
  const options = { method, credentials: "same-origin", cache: "no-store" };
  if (method !== "GET") {
    options.headers = { "Content-Type": "application/json", "X-CSRF-Token": state?.csrf || "" };
    options.body = JSON.stringify(data ?? {});
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error("Can't reach LANpack. Check your connection and try again."); }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The host returned an unexpected response. Try again shortly."); }
  if (!response.ok) throw new Error(result.error || "Something went wrong. Try again.");
  return result;
}

function render() {
  if (!state) return;
  const count = state.players.length;
  $("#player-count").textContent = count;
  $("#attendance").textContent = `${count} / ${state.expected}`;
  $("#progress").max = Math.max(state.expected, count, 1);
  $("#progress").value = count;
  $("#join-button").textContent = state.me ? "Edit my details ↗" : "Join the party ↗";
  $("#join-button").disabled = state.setup_required;
  $("#empty-join").disabled = state.setup_required;
  $("#join-note").textContent = state.me ? `You're in, ${state.me.nickname}.` : "No account. Just your player details.";
  $("#join-url").textContent = state.join_url;
  $("#copy-url").disabled = false;
  const hostname = new URL(state.join_url).hostname;
  $("#local-warning").hidden = !["localhost", "127.0.0.1"].includes(hostname);
  $("#admin-toolbar").hidden = !state.organizer || state.setup_required;
  $("#setup-banner").hidden = !state.setup_required;
  $(".join-panel").hidden = state.setup_required;
  $("#setup-button").textContent = state.organizer ? "Choose your password ↗" : "Set up organizer ↗";
  $("#organizer-button").textContent = state.organizer ? "Organizer controls active" : "Organizer access ↗";

  const query = $("#search").value.trim().toLocaleLowerCase();
  const players = state.players.filter(p => `${p.name} ${p.nickname} ${p.steam_code}`.toLocaleLowerCase().includes(query));
  const signature = JSON.stringify([players, state.me?.id, state.organizer]);
  if (signature !== lastCards) {
    lastCards = signature;
    const fragment = document.createDocumentFragment();
    players.forEach((player) => {
      const card = $("#player-template").content.firstElementChild.cloneNode(true);
      const isMe = player.id === state.me?.id;
      const number = state.players.indexOf(player) + 1;
      card.dataset.id = player.id;
      card.classList.toggle("is-me", isMe);
      card.querySelector(".avatar").textContent = [...player.nickname].slice(0, 2).join("").toLocaleUpperCase();
      card.querySelector(".avatar").classList.add(`color-${number % 5}`);
      card.querySelector(".you-tag").hidden = !isMe;
      card.querySelector(".player-number").textContent = `#${String(number).padStart(2, "0")}`;
      card.querySelector(".nickname").textContent = player.nickname;
      card.querySelector(".real-name").textContent = player.name;
      card.querySelector(".code-value").textContent = player.steam_code;
      card.querySelector(".copy-code").setAttribute("aria-label", `Copy ${player.nickname}'s Steam friend code`);
      card.querySelector(".player-actions").hidden = !(isMe || state.organizer);
      fragment.append(card);
    });
    $("#players").replaceChildren(fragment);
  }
  $("#empty-state").hidden = players.length > 0;
  $("#empty-title").textContent = query ? "No players found." : "First one here?";
  $("#empty-text").textContent = query ? "Try another nickname, name or friend code." : "Add your details and get the party started.";
  $("#empty-join").hidden = Boolean(query || state.me || state.setup_required);
  if (state.setup_required) {
    $("#join-note").textContent = "Waiting for organizer setup.";
    $("#empty-title").textContent = "The party opens soon.";
    $("#empty-text").textContent = "Players can join after the organizer chooses a password.";
  }
}

async function refresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      state = await api("/api/state");
      $("#connection").classList.remove("offline");
      $("#connection-text").textContent = "Host connected";
      $("#load-error").hidden = true;
      $("#refresh-note").textContent = "Updates every 5 seconds";
      render();
      return true;
    } catch (error) {
      $("#connection").classList.add("offline");
      $("#connection-text").textContent = "Reconnecting";
      $("#refresh-note").textContent = "Waiting for host…";
      $("#load-error").textContent = `${error.message} ${state ? "Showing the last received directory." : "Retrying automatically."}`;
      $("#load-error").hidden = false;
      return false;
    } finally { refreshing = null; }
  })();
  return refreshing;
}

function openPlayer(player = state?.me) {
  if (!state || state.setup_required) return;
  editing = player || null;
  const form = $("#player-form");
  form.reset();
  for (const key of ["name", "nickname", "steam_code"]) form.elements[key].value = player?.[key] || "";
  $("#player-dialog-title").textContent = player ? "Update player details." : "Join the party.";
  $("#save-player").textContent = player ? "Save changes ↗" : "I'm in ↗";
  $("#player-error").hidden = true;
  $("#player-dialog").showModal();
}

async function copy(value, description) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Manual copy required");
    await navigator.clipboard.writeText(value);
    toast(`${description} copied`);
  } catch {
    $("#copy-title").textContent = `Copy ${description.toLocaleLowerCase()}.`;
    $("#manual-copy").value = value;
    $("#copy-dialog").showModal();
    $("#manual-copy").focus();
    $("#manual-copy").select();
    $("#manual-copy").setSelectionRange(0, value.length);
  }
}

async function submit(form, errorElement, action) {
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  errorElement.hidden = true;
  try { await action(); }
  catch (error) { errorElement.textContent = error.message; errorElement.hidden = false; }
  finally { button.disabled = false; }
}

$("#join-button").addEventListener("click", () => openPlayer());
$("#empty-join").addEventListener("click", () => openPlayer());
$("#search").addEventListener("input", render);
$("#copy-url").addEventListener("click", () => { if (state) copy(state.join_url, "Join address"); });
document.querySelectorAll(".close-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
document.addEventListener("keydown", event => {
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !document.querySelector("dialog[open]") && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault(); $("#search").focus();
  }
});

$("#player-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, $("#player-error"), async () => {
    const data = Object.fromEntries(new FormData(form));
    const path = !editing ? "/api/players" : (editing.id === state.me?.id ? "/api/players/me" : `/api/admin/players/${editing.id}`);
    await api(path, editing ? "PATCH" : "POST", data);
    $("#player-dialog").close();
    toast(editing ? "Details updated" : "You're in. Welcome to the party!");
    await refresh();
  });
});

$("#players").addEventListener("click", event => {
  const card = event.target.closest(".player-card");
  if (!card || !state) return;
  const player = state.players.find(p => p.id === card.dataset.id);
  if (!player) return;
  if (event.target.closest(".copy-code")) copy(player.steam_code, "Friend code");
  if (event.target.closest(".edit-player")) openPlayer(player);
  if (event.target.closest(".remove-player")) {
    removing = player;
    $("#remove-description").textContent = `${player.nickname} will be removed from the directory. They can register again later.`;
    $("#remove-error").hidden = true;
    $("#remove-dialog").showModal();
  }
});

$("#remove-form").addEventListener("submit", event => {
  event.preventDefault();
  submit(event.currentTarget, $("#remove-error"), async () => {
    if (!removing) return;
    const path = removing.id === state.me?.id ? "/api/players/me" : `/api/admin/players/${removing.id}`;
    await api(path, "DELETE");
    $("#remove-dialog").close();
    removing = null;
    toast("Player removed");
    await refresh();
  });
});

function openPassword() {
  $("#password-form").reset();
  $("#password-error").hidden = true;
  $("#password-title").textContent = state?.setup_required ? "Make it your party." : "Change password.";
  $("#password-intro").textContent = state?.setup_required
    ? "Replace the default admin password before players can join."
    : "Other organizer sessions will be signed out. Player entries stay unchanged.";
  $("#password-dialog").showModal();
}

function openOrganizer() {
  if (!state) return;
  if (state.organizer && state.setup_required) { openPassword(); return; }
  if (state?.organizer) { $("#admin-toolbar").scrollIntoView({ block: "center" }); return; }
  $("#admin-form").reset();
  $("#admin-error").hidden = true;
  $("#admin-dialog").showModal();
}
$("#organizer-button").addEventListener("click", openOrganizer);
$("#setup-button").addEventListener("click", openOrganizer);
$("#change-password").addEventListener("click", openPassword);

$("#password-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, $("#password-error"), async () => {
    const result = await api("/api/admin/password", "POST", Object.fromEntries(new FormData(form)));
    state.csrf = result.csrf;
    form.reset();
    $("#password-dialog").close();
    toast(state.setup_required ? "Password saved. The party is open!" : "Organizer password changed");
    await refresh();
  });
});

$("#admin-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, $("#admin-error"), async () => {
    const result = await api("/api/admin/login", "POST", Object.fromEntries(new FormData(form)));
    if (state) state.csrf = result.csrf;
    form.reset();
    $("#admin-dialog").close();
    await refresh();
    if (state?.setup_required) openPassword();
    else toast("Organizer controls unlocked");
  });
});

$("#logout").addEventListener("click", async () => {
  $("#logout").disabled = true;
  try { await api("/api/admin/logout", "POST"); await refresh(); toast("Signed out"); }
  catch (error) { toast(error.message); }
  finally { $("#logout").disabled = false; }
});

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
