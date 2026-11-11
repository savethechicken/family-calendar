/* Settings UI — plain JS, talks to /api/settings. */

const TOKEN_KEY = "skylight-admin-token";
const PALETTE = [
  "#039be5",
  "#33b679",
  "#8e63ce",
  "#e67c73",
  "#f6bf26",
  "#f4511e",
  "#7986cb",
  "#616161",
];

const $ = (selector) => document.querySelector(selector);
const form = $("#settings-form");

let settings = null;
let token = sessionStorage.getItem(TOKEN_KEY) || "";
let dirty = false;

class AuthError extends Error {}

/* ------------------------------------------------------------------ */
/* Plumbing                                                            */
/* ------------------------------------------------------------------ */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["X-Admin-Token"] = token;

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401) {
    showAuth();
    throw new AuthError("Settings password required");
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function setStatus(text, isError = false) {
  const status = $("#save-status");
  status.textContent = text;
  status.classList.toggle("error", isError);
}

function toast(text) {
  const element = $("#toast");
  element.textContent = text;
  element.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.add("hidden"), 3200);
}

function markDirty() {
  dirty = true;
  if (!settings) return;
  setStatus("Unsaved changes");
}

function showAuth() {
  $("#auth").classList.remove("hidden");
  setTimeout(() => $("#auth-token").focus(), 50);
}

function hideAuth() {
  $("#auth").classList.add("hidden");
}

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */

function fillTimezones(zones) {
  const list = $("#timezone-list");
  if (list.childElementCount) return;
  list.innerHTML = zones.map((zone) => `<option value="${zone}"></option>`).join("");
}

function render() {
  const { display, weather } = settings;

  fillTimezones(settings.timezones);
  $("#display-title").value = display.title;
  $("#display-timezone").value = display.timezone;
  $("#display-week-start").value = display.week_starts_on;
  $("#display-time-format").value = display.time_format;
  $("#display-theme").value = display.theme;
  $("#display-accent").value = display.accent_color;
  $("#display-accent-text").value = display.accent_color;
  $("#display-clock").checked = display.show_clock;
  $("#display-refresh").value = display.refresh_seconds;
  $("#display-day-start").value = display.day_start_hour;
  $("#display-day-end").value = display.day_end_hour;

  $("#weather-enabled").checked = weather.enabled;
  $("#weather-location").value = weather.location_name || "";
  $("#weather-units").value = weather.units;
  $("#weather-latitude").value = weather.latitude ?? "";
  $("#weather-longitude").value = weather.longitude ?? "";

  $("#config-path").textContent = settings.config_path;
  $("#access-note").innerHTML = settings.server.admin_token_set
    ? "This page is password protected via <code>server.admin_token</code>."
    : "No password is set — anyone on your home network can change these settings. " +
      "Add <code>admin_token</code> under <code>server</code> in config.yaml, or set " +
      "<code>SKYLIGHT_ADMIN_TOKEN</code>, to require one.";

  renderCalendars();
  applyThemePreview(display.theme);
  dirty = false;
  setStatus("");
}

function renderCalendars() {
  const container = $("#calendars");
  container.innerHTML = "";
  for (const calendar of settings.calendars) {
    container.append(calendarCard(calendar));
  }
  if (!settings.calendars.length) {
    container.innerHTML =
      '<p class="hint">No calendars yet. Use “Add calendar” to paste an iCal address.</p>';
  }
}

function calendarCard(calendar) {
  const card = document.createElement("div");
  card.className = "cal-card";
  card.dataset.id = calendar.id || "";
  card.dataset.editable = calendar.editable === false ? "false" : "true";

  if (calendar.editable === false) {
    card.classList.add("readonly");
    card.innerHTML = `
      <span class="dot" style="background:${escapeHtml(calendar.color)}"></span>
      <div>
        <strong>${escapeHtml(calendar.name)}</strong>
        <div class="muted">Google Calendar API — configured in config.yaml</div>
      </div>`;
    return card;
  }

  const source = calendar.source || {};
  const type = source.type || "ics";
  const color = calendar.color || "#5b8cff";

  card.innerHTML = `
    <div class="row">
      <input class="swatch" type="color" value="${escapeHtml(color)}" aria-label="Calendar color" />
      <input class="color-text" type="text" maxlength="7" value="${escapeHtml(color)}" aria-label="Color hex value" spellcheck="false" />
      <input class="name grow" type="text" maxlength="80" value="${escapeHtml(
        calendar.name || ""
      )}" placeholder="Calendar name" aria-label="Calendar name" />
      <select class="type" aria-label="Calendar type">
        <option value="ics">ICS / iCal feed</option>
        <option value="demo">Demo data</option>
      </select>
      <button class="icon-btn remove" type="button">Remove</button>
    </div>
    <div class="row source-row">
      <input class="url grow" type="url" value="${escapeHtml(
        source.url || ""
      )}" placeholder="https://calendar.google.com/calendar/ical/…/basic.ics" aria-label="Calendar feed URL" />
      <button class="btn small test" type="button">Test feed</button>
    </div>
    <div class="meta-row source-row">
      <label>Refresh feed every
        <input class="ttl" type="number" min="30" max="86400" step="30" value="${
          source.cache_ttl_seconds || 300
        }" aria-label="Cache seconds" />
        seconds</label>
      <span class="test-result"></span>
    </div>`;

  const typeSelect = card.querySelector(".type");
  typeSelect.value = type;

  const swatch = card.querySelector(".swatch");
  const colorText = card.querySelector(".color-text");
  swatch.addEventListener("input", () => {
    colorText.value = swatch.value;
    markDirty();
  });
  colorText.addEventListener("input", () => {
    const value = colorText.value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(value)) swatch.value = value.toLowerCase();
    markDirty();
  });

  const syncType = () => {
    const isIcs = typeSelect.value === "ics";
    card
      .querySelectorAll(".source-row")
      .forEach((row) => row.classList.toggle("hidden", !isIcs));
  };
  typeSelect.addEventListener("change", () => {
    syncType();
    markDirty();
  });
  syncType();

  card.querySelector(".remove").addEventListener("click", () => {
    if (!confirm(`Remove “${calendar.name || "this calendar"}”?`)) return;
    card.remove();
    markDirty();
  });

  card.querySelector(".test").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const url = card.querySelector(".url").value.trim();
    const result = card.querySelector(".test-result");

    if (!url) {
      result.className = "test-result bad";
      result.textContent = "Paste the .ics URL first.";
      return;
    }
    if (!/^(https?|webcal):\/\//i.test(url)) {
      result.className = "test-result bad";
      result.textContent = "The URL must start with https:// or webcal://.";
      return;
    }

    button.disabled = true;
    result.className = "test-result";
    result.textContent = "Contacting the feed…";
    try {
      const report = await api("/api/settings/test-feed", {
        method: "POST",
        body: { url },
      });
      if (report.count === 0) {
        result.className = "test-result ok";
        result.textContent =
          "Feed loaded, but it has no events in the next 14 days.";
      } else {
        const next = report.samples[0];
        result.className = "test-result ok";
        result.textContent = `${report.count} event${
          report.count === 1 ? "" : "s"
        } in the next 14 days · next: “${next.title}”`;
      }
    } catch (error) {
      if (!(error instanceof AuthError)) {
        result.className = "test-result bad";
        result.textContent = error.message;
      }
    } finally {
      button.disabled = false;
    }
  });

  return card;
}

function addCalendar() {
  const container = $("#calendars");
  const color = PALETTE[container.querySelectorAll(".cal-card").length % PALETTE.length];
  const card = calendarCard({
    id: "",
    name: "",
    color,
    editable: true,
    source: { type: "ics", url: "", cache_ttl_seconds: 300 },
  });
  container.append(card);
  card.querySelector(".name").focus();
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  markDirty();
}

function applyThemePreview(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
    return;
  }
  document.documentElement.dataset.theme = matchMedia("(prefers-color-scheme: dark)")
    .matches
    ? "dark"
    : "light";
}

/* ------------------------------------------------------------------ */
/* Collect + save                                                      */
/* ------------------------------------------------------------------ */

function numberValue(id, fallback) {
  const value = Number($(id).value);
  return Number.isFinite(value) ? value : fallback;
}

function collect() {
  const calendars = [...document.querySelectorAll(".cal-card")]
    .filter((card) => card.dataset.editable !== "false")
    .map((card) => {
      const id = card.dataset.id;
      return {
        ...(id ? { id } : {}),
        name: card.querySelector(".name").value.trim(),
        color: card.querySelector(".color-text").value.trim(),
        source: {
          type: card.querySelector(".type").value,
          url: card.querySelector(".url")?.value.trim() || "",
          cache_ttl_seconds: Number(card.querySelector(".ttl")?.value || 300),
        },
      };
    });

  return {
    display: {
      title: $("#display-title").value.trim(),
      timezone: $("#display-timezone").value.trim(),
      week_starts_on: $("#display-week-start").value,
      time_format: $("#display-time-format").value,
      theme: $("#display-theme").value,
      accent_color: $("#display-accent-text").value.trim(),
      show_clock: $("#display-clock").checked,
      refresh_seconds: numberValue("#display-refresh", 60),
      day_start_hour: numberValue("#display-day-start", 6),
      day_end_hour: numberValue("#display-day-end", 22),
    },
    weather: {
      enabled: $("#weather-enabled").checked,
      location_name: $("#weather-location").value.trim(),
      units: $("#weather-units").value,
      latitude: $("#weather-latitude").value === "" ? null : Number($("#weather-latitude").value),
      longitude:
        $("#weather-longitude").value === "" ? null : Number($("#weather-longitude").value),
    },
    calendars,
  };
}

async function save(event) {
  event.preventDefault();
  const button = $("#save-button");
  button.disabled = true;
  setStatus("Saving…");

  try {
    settings = await api("/api/settings", { method: "PUT", body: collect() });
    render();
    setStatus("Saved. The calendar is already using these settings.");
    toast("Saved — the TV updated instantly.");
  } catch (error) {
    if (error instanceof AuthError) {
      setStatus("Enter the settings password to save.", true);
    } else {
      setStatus(error.message, true);
    }
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */

$("#display-accent").addEventListener("input", () => {
  $("#display-accent-text").value = $("#display-accent").value;
  markDirty();
});
$("#display-accent-text").addEventListener("input", () => {
  const value = $("#display-accent-text").value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(value)) $("#display-accent").value = value.toLowerCase();
  markDirty();
});
$("#display-theme").addEventListener("change", () => {
  applyThemePreview($("#display-theme").value);
  markDirty();
});

$("#add-calendar").addEventListener("click", addCalendar);
form.addEventListener("submit", save);
form.addEventListener("input", markDirty);
form.addEventListener("change", markDirty);

$("#auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  token = $("#auth-token").value.trim();
  sessionStorage.setItem(TOKEN_KEY, token);
  hideAuth();
  load();
});

window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

async function load() {
  setStatus("Loading…");
  try {
    settings = await api("/api/settings");
  } catch (error) {
    if (error instanceof AuthError) {
      setStatus("");
      return;
    }
    setStatus(error.message, true);
    return;
  }
  hideAuth();
  render();
}

load();
