"use strict";
const calendar = document.querySelector(".calendar");
const statusBox = document.querySelector("#calendar-status");
const reloadLink = document.querySelector("#calendar-reload");
function showState(button, completed) {
  button.setAttribute("aria-pressed", String(completed));
  button.classList.toggle("completed", completed);
  button.textContent = completed ? "✓" : "·";
  button.setAttribute("aria-label", `${button.dataset.name}, ${button.dataset.displayDate}: ${completed ? "выполнено" : "не выполнено"}`);
}
function showStats(panel, stats) {
  panel.querySelector("dl").hidden = false;
  panel.querySelector(".stats-unknown").hidden = true;
  const percentage = stats.percentage === null ? "Нет данных" : `${stats.percentage}%`;
  const values = {...stats, percentage, current_streak: stats.current_streak === null ? "В архиве" : stats.current_streak,
    summary: `${stats.completed_days} из ${stats.available_days} · ${percentage}`};
  for (const [key, value] of Object.entries(values)) {
    const field = panel.querySelector(`[data-stat="${key}"]`);
    if (field) field.textContent = String(value);
  }
}
async function readResponse(response) {
  if (!response.ok) throw new Error("Request failed");
  const data = await response.json();
  if (typeof data.completed !== "boolean" || typeof data.archived !== "boolean" || !data.stats) throw new Error("Invalid response");
  for (const key of ["completed_days", "available_days", "best_streak"]) {
    if (!Number.isInteger(data.stats[key]) || data.stats[key] < 0) throw new Error("Invalid statistics");
  }
  if (data.stats.percentage !== null && (!Number.isInteger(data.stats.percentage) || data.stats.percentage < 0 || data.stats.percentage > 100)) throw new Error("Invalid percentage");
  if (data.stats.current_streak !== null && (!Number.isInteger(data.stats.current_streak) || data.stats.current_streak < 0)) throw new Error("Invalid streak");
  return data;
}
async function send(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try { return await readResponse(await fetch(url, {...options, signal: controller.signal, credentials: "same-origin", cache: "no-store"})); }
  finally { clearTimeout(timer); }
}
calendar?.addEventListener("click", async (event) => {
  const button = event.target.closest(".day-button");
  if (!button || button.disabled) return;
  const desired = button.getAttribute("aria-pressed") !== "true";
  const panel = document.querySelector(`[data-habit-stats="${button.dataset.habitId}"]`);
  // Serialize changes for one habit so older responses cannot replace newer statistics.
  const cells = [...calendar.querySelectorAll(".day-button")].filter(cell => cell.dataset.habitId === button.dataset.habitId);
  cells.forEach(cell => { cell.disabled = true; });
  button.setAttribute("aria-busy", "true");
  panel.setAttribute("aria-busy", "true");
  panel.classList.add("stats-pending");
  statusBox.textContent = "Сохраняем отметку и пересчитываем показатели…";
  let reliable = false;
  let archived = false;
  function apply(data) {
    showState(button, data.completed);
    showStats(panel, data.stats);
    archived = data.archived;
    reliable = true;
    if (archived) reloadLink.hidden = false;
  }
  try {
    apply(await send(button.dataset.url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": calendar.dataset.csrf}, body: JSON.stringify({date: button.dataset.date, completed: desired})}));
    statusBox.textContent = "Отметка и показатели сохранены.";
  } catch {
    try {
      const url = new URL(button.dataset.url, window.location.origin);
      url.searchParams.set("date", button.dataset.date);
      apply(await send(url, {}));
      statusBox.textContent = archived ? "Привычка уже в архиве. Изменение запрещено; обновите календарь." : "Запрос не подтверждён. Отметка и показатели сверены с сервером. Если ошибка повторяется, обновите страницу.";
    } catch {
      button.textContent = "?";
      button.setAttribute("aria-label", `${button.dataset.name}, ${button.dataset.displayDate}: состояние неизвестно, обновите календарь`);
      button.removeAttribute("aria-pressed");
      panel.querySelector("dl").hidden = true;
      panel.querySelector(".stats-unknown").hidden = false;
      panel.querySelector('[data-stat="summary"]').textContent = "Показатели не подтверждены";
      statusBox.textContent = "Не удалось проверить отметку и показатели. Проверьте соединение и обновите календарь.";
      reloadLink.hidden = false;
    }
  } finally {
    button.removeAttribute("aria-busy");
    panel.removeAttribute("aria-busy");
    panel.classList.remove("stats-pending");
    cells.forEach(cell => { cell.disabled = !reliable || archived; });
  }
});
