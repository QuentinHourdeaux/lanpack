"use strict";
const teamSelection = new Set();
let teamPickerInitialized = false;
let teamPickerSignature = "";
let teamDraw = null;
let teamDrawSignature = "";
let teamDrawing = false;

function teamRequest() {
  return {player_ids: [...teamSelection].sort(), mode: $("#team-mode").value, amount: Number($("#team-amount").value)};
}
function clearTeamDraw() {
  teamDraw = null; teamDrawSignature = "";
  $("#team-results").hidden = true;
  $("#shuffle-teams").textContent = "Shuffle teams ↗";
}
function renderTeams() {
  if (!state) return;
  if (!teamPickerInitialized && !$("#teams-panel").hidden && state.players.length) {
    state.players.forEach(player => teamSelection.add(player.id));
    teamPickerInitialized = true;
  }
  const available = new Set(state.players.map(player => player.id));
  for (const id of teamSelection) if (!available.has(id)) teamSelection.delete(id);
  if (teamDraw && teamDrawSignature !== JSON.stringify(teamRequest())) clearTeamDraw();
  const query = $("#team-search").value.trim().toLocaleLowerCase();
  const players = state.players.filter(player => `${player.nickname} ${player.name}`.toLocaleLowerCase().includes(query));
  const signature = JSON.stringify(players);
  if (signature !== teamPickerSignature) {
    teamPickerSignature = signature;
    const fragment = document.createDocumentFragment();
    for (const player of players) {
      const label = document.createElement("label"); label.className = "team-player-option";
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = player.id;
      checkbox.setAttribute("aria-label", `Select ${player.nickname} (${player.name})`);
      const text = document.createElement("span");
      const nick = document.createElement("strong"); nick.textContent = player.nickname;
      const name = document.createElement("small"); name.textContent = player.name;
      text.append(nick, name); label.append(checkbox, text); fragment.append(label);
    }
    $("#team-player-picker").replaceChildren(fragment);
  }
  $("#team-player-picker").querySelectorAll("input").forEach(input => {
    input.checked = teamSelection.has(input.value); input.disabled = teamDrawing || state.setup_required;
  });
  $("#team-picker-empty").hidden = players.length > 0;
  $("#team-picker-empty").textContent = state.setup_required ? "Waiting for organizer setup."
    : query ? "No matching players." : "Players appear here after joining the party.";
  $("#team-selected-count").textContent = `${teamSelection.size} selected / ${state.players.length}`;
  $("#team-select-all").textContent = query ? "Select shown" : "Select all";
  for (const id of ["team-select-all", "team-clear", "team-mode", "team-amount"]) $("#" + id).disabled = teamDrawing || state.setup_required;
  const {mode, amount} = teamRequest();
  $("#team-amount-label").textContent = mode === "team_count" ? "Number of teams" : "Maximum players per team";
  const count = mode === "team_count" ? amount : Math.ceil(teamSelection.size / amount);
  let issue = "";
  if (state.setup_required) issue = "The organizer must finish setup first.";
  else if (teamSelection.size < 2) issue = "Select at least two players.";
  else if (teamSelection.size > 100) issue = "Select up to 100 players per draw.";
  else if (!Number.isInteger(amount) || amount < 1 || amount > 100) issue = "Enter a whole number from 1 to 100.";
  else if (count < 2 || count > teamSelection.size) issue = "Choose at least two teams, with at least one player per team.";
  const base = Math.floor(teamSelection.size / count), extra = teamSelection.size % count;
  $("#team-plan").textContent = issue || `${teamSelection.size} players → ${count} teams of ${extra ? `${base}–${base + 1}` : base}. Everyone plays.`;
  $("#shuffle-teams").disabled = teamDrawing || Boolean(issue);
}

$("#team-search").addEventListener("input", renderTeams);
$("#team-select-all").addEventListener("click", () => {
  $("#team-player-picker").querySelectorAll("input").forEach(input => teamSelection.add(input.value));
  renderTeams();
});
$("#team-clear").addEventListener("click", () => { teamSelection.clear(); renderTeams(); });
$("#team-player-picker").addEventListener("change", event => {
  if (!event.target.matches('input[type="checkbox"]')) return;
  event.target.checked ? teamSelection.add(event.target.value) : teamSelection.delete(event.target.value);
  renderTeams();
});
for (const id of ["team-mode", "team-amount"]) $("#" + id).addEventListener("input", renderTeams);
$("#team-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (teamDrawing || $("#shuffle-teams").disabled) return;
  const request = teamRequest();
  teamDrawing = true; $("#team-error").hidden = true; renderTeams();
  try {
    const result = await api("/api/teams/shuffle", "POST", request);
    if (JSON.stringify(request) !== JSON.stringify(teamRequest())) throw new Error("The player list changed. Shuffle again.");
    teamDraw = result.teams; teamDrawSignature = JSON.stringify(request);
    const fragment = document.createDocumentFragment();
    for (const team of teamDraw) {
      const section = document.createElement("section"); section.className = "team-result-card";
      const heading = document.createElement("h4"); heading.textContent = `${team.name} · ${team.players.length}`;
      const list = document.createElement("ul");
      for (const player of team.players) {
        const item = document.createElement("li");
        const nick = document.createElement("strong"); nick.textContent = player.nickname;
        const name = document.createElement("span"); name.textContent = player.name;
        item.append(nick, name); list.append(item);
      }
      section.append(heading, list); fragment.append(section);
    }
    $("#team-result-grid").replaceChildren(fragment);
    $("#team-result-summary").textContent = `${request.player_ids.length} players split into ${teamDraw.length} teams. Ready to play.`;
    $("#team-results").hidden = false;
    $("#shuffle-teams").textContent = "Shuffle again ↻";
    $("#team-results").scrollIntoView({block:"nearest", behavior:"instant"});
  } catch (error) {
    $("#team-error").textContent = error.message; $("#team-error").hidden = false;
    await refresh();
  } finally { teamDrawing = false; renderTeams(); }
});
$("#copy-teams").addEventListener("click", () => {
  if (!teamDraw) return;
  const text = teamDraw.map(team => `${team.name}\n${team.players.map(player => `• ${player.nickname} (${player.name})`).join("\n")}`).join("\n\n");
  copy(text, "Teams");
});
