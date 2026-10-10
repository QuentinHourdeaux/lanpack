"use strict";
let editingGame = null;
let removingGame = null;
let viewingGame = null;
let lastGames = "";
const savingGames = new Set();

function selectTab(name) {
  for (const tabName of ["players", "games"]) {
    const active = tabName === name;
    $(`#${tabName}-tab`).setAttribute("aria-selected", String(active));
    $(`#${tabName}-tab`).tabIndex = active ? 0 : -1;
    $(`#${tabName}-panel`).hidden = !active;
  }
  $(".steam-help").hidden = name !== "players";
}
for (const name of ["players", "games"]) {
  $(`#${name}-tab`).addEventListener("click", () => selectTab(name));
  $(`#${name}-tab`).addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "players" : event.key === "End" ? "games" : name === "games" ? "players" : "games";
    selectTab(next); $(`#${next}-tab`).focus();
  });
}

function gamePlayerCount(game) {
  return game.player_count == null ? "Player limit not listed" : `${game.player_count} players per game`;
}

function renderGames() {
  if (!state) return;
  const games = state.games || [];
  const query = $("#game-search").value.trim().toLocaleLowerCase();
  const visible = games.filter(game => `${game.name} ${game.genre || ""}`.toLocaleLowerCase().includes(query));
  $("#game-count").textContent = games.length;
  $("#add-game").hidden = !state.organizer || state.setup_required;
  $("#games-note").textContent = state.setup_required ? "Waiting for organizer setup."
    : state.me ? "Tick what you own and what you want to play. Open a game to see who’s in."
    : "Join the party with your player details first, then tick the games you own or want to play.";
  const signature = JSON.stringify([visible, state.me?.id, state.organizer]);
  if (!savingGames.size && signature !== lastGames) {
    lastGames = signature;
    const fragment = document.createDocumentFragment();
    for (const game of visible) {
      const card = $("#game-template").content.firstElementChild.cloneNode(true);
      card.dataset.id = game.id;
      card.querySelector(".game-name").textContent = game.name;
      card.querySelector(".game-open").setAttribute("aria-label", `View players for ${game.name}`);
      card.querySelector(".game-open").title = game.name;
      card.querySelector(".game-genre").textContent = game.genre || "—";
      card.querySelector(".game-genre").title = game.genre || "Genre not listed";
      card.querySelector(".game-player-count").textContent = game.player_count ?? "—";
      card.querySelector(".game-price").textContent = game.price || (game.cracked ? "" : "—");
      card.querySelector(".game-price").title = game.price || "Price not listed";
      card.querySelector(".game-cracked").hidden = !game.cracked;
      card.querySelector(".game-totals").textContent = `${game.players.filter(p => p.owns).length} own · ${game.players.filter(p => p.wants_to_play).length} play`;
      const own = game.players.find(p => p.player_id === state.me?.id);
      for (const field of ["owns", "wants_to_play"]) {
        const input = card.querySelector(`[name="${field}"]`);
        input.checked = Boolean(own?.[field]);
        input.disabled = !state.me || state.setup_required;
        input.setAttribute("aria-label", `${field === "owns" ? "I own" : "I want to play"} ${game.name}`);
      }
      card.querySelector(".game-actions").hidden = !state.organizer;
      fragment.append(card);
    }
    $("#games").replaceChildren(fragment);
  }
  $("#game-actions-heading").hidden = !state.organizer;
  $("#game-list").hidden = visible.length === 0;
  $("#games-empty").hidden = visible.length > 0;
  $("#games-empty h3").textContent = query ? "No matching games." : "No games yet.";
  $("#games-empty p").textContent = query ? "Try another game name." : "The organizer can add games to get things started.";
  if ($("#game-details-dialog").open) renderGameDetails();
}

function renderGameDetails() {
  const game = state.games.find(game => game.id === viewingGame);
  if (!game) { $("#game-details-dialog").close(); toast("That game was removed"); return; }
  $("#game-details-title").textContent = game.name;
  $("#game-details-meta").textContent = `${game.genre ? `${game.genre} · ` : ""}${gamePlayerCount(game)} · ${game.price || "Price not listed"}${game.cracked ? " · Cracked" : ""}`;
  const link = $("#game-details-link");
  link.hidden = !game.url;
  if (game.url) link.href = game.url; else link.removeAttribute("href");
  const fragment = document.createDocumentFragment();
  let count = 0;
  for (const player of state.players) {
    const selection = game.players.find(p => p.player_id === player.id);
    if (!selection) continue;
    const row = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = `${player.nickname} · ${player.name}${player.id === state.me?.id ? " (you)" : ""}`;
    const tags = document.createElement("span");
    tags.textContent = [selection.owns ? "Owns it" : "", selection.wants_to_play ? "Wants to play" : ""].filter(Boolean).join(" · ");
    row.append(name, tags); fragment.append(row); count++;
  }
  $("#game-player-list").replaceChildren(fragment);
  $("#game-details-empty").hidden = count > 0;
}

function openGameForm(game = null) {
  editingGame = game;
  const form = $("#game-form"); form.reset();
  for (const key of ["name", "genre", "player_count", "url", "price"]) form.elements[key].value = game?.[key] ?? "";
  form.elements.cracked.checked = Boolean(game?.cracked);
  $("#game-title").textContent = game ? "Edit game." : "Add a game.";
  $("#game-error").hidden = true;
  $("#game-dialog").showModal();
}
$("#add-game").addEventListener("click", () => openGameForm());
$("#game-search").addEventListener("input", renderGames);
$("#games").addEventListener("click", event => {
  const card = event.target.closest(".game-card");
  const game = state?.games.find(game => game.id === card?.dataset.id);
  if (!game) return;
  if (event.target.closest(".game-open")) {
    viewingGame = game.id; renderGameDetails(); $("#game-details-dialog").showModal();
  }
  if (event.target.closest(".game-edit")) openGameForm(game);
  if (event.target.closest(".game-remove")) {
    removingGame = game.id;
    $("#remove-game-description").textContent = `${game.name} and all its player selections will be removed.`;
    $("#remove-game-error").hidden = true; $("#remove-game-dialog").showModal();
  }
});
$("#games").addEventListener("change", async event => {
  if (!event.target.matches('input[type="checkbox"]')) return;
  const card = event.target.closest(".game-card");
  const id = card.dataset.id;
  const data = {owns:card.querySelector('[name="owns"]').checked, wants_to_play:card.querySelector('[name="wants_to_play"]').checked};
  savingGames.add(id);
  card.querySelectorAll("input").forEach(input => { input.disabled = true; });
  try { await api(`/api/games/${id}/interest`, "POST", data); }
  catch (error) { toast(error.message); }
  finally {
    // Finish any older poll before fetching the just-saved selections.
    if (refreshing) await refreshing;
    savingGames.delete(id); lastGames = "";
    await refresh(); renderGames();
  }
});
$("#game-form").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget;
  submit(form, $("#game-error"), async () => {
    const data = Object.fromEntries(new FormData(form));
    data.player_count = data.player_count.trim() === "" ? null : Number(data.player_count); data.cracked = form.elements.cracked.checked;
    await api(editingGame ? `/api/admin/games/${editingGame.id}` : "/api/admin/games", editingGame ? "PATCH" : "POST", data);
    $("#game-dialog").close(); toast(editingGame ? "Game updated" : "Game added");
    if (refreshing) await refreshing;
    await refresh();
  });
});
$("#remove-game-form").addEventListener("submit", event => {
  event.preventDefault();
  submit(event.currentTarget, $("#remove-game-error"), async () => {
    await api(`/api/admin/games/${removingGame}`, "DELETE");
    $("#remove-game-dialog").close(); toast("Game removed");
    if (refreshing) await refreshing;
    await refresh();
  });
});
