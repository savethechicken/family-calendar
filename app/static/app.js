/* Family calendar — vanilla JS, no build step. */

const $ = (selector) => document.querySelector(selector);

const state = {
  config: null,
  events: [],
  weather: null,
  errors: {},
  failed: false,
  lastUpdated: null,
  week: null,
  dayKey: null,
  loading: true,
};

const DAY_MS = 86_400_000;

/* ------------------------------------------------------------------ */
/* Timezone helpers                                                    */
/*                                                                     */
/* All layout math happens in the configured display timezone, not the  */
/* browser's, so a Pi left on UTC still renders correctly.             */
/* ------------------------------------------------------------------ */

const formatterCache = new Map();

function formatterFor(timeZone, options) {
  const key = timeZone + JSON.stringify(options);
  let formatter = formatterCache.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", { timeZone, ...options });
    formatterCache.set(key, formatter);
  }
  return formatter;
}

function zonedParts(date, timeZone) {
  const parts = formatterFor(timeZone, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const map = {};
  for (const part of parts) {
    if (part.type !== "literal") map[part.type] = part.value;
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    hour: Number(map.hour) % 24,
    minute: Number(map.minute),
    second: Number(map.second),
  };
}

function tzOffsetMs(date, timeZone) {
  const parts = zonedParts(date, timeZone);
  const asUtc = Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second
  );
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** Convert a wall-clock time in `timeZone` to a UTC epoch (ms). */
function zonedToUtc(civil, hour, minute, timeZone) {
  const guess = Date.UTC(civil.year, civil.month - 1, civil.day, hour, minute);
  const firstOffset = tzOffsetMs(new Date(guess), timeZone);
  let timestamp = guess - firstOffset;
  const secondOffset = tzOffsetMs(new Date(timestamp), timeZone);
  if (secondOffset !== firstOffset) timestamp = guess - secondOffset;
  return timestamp;
}

const pad2 = (value) => String(value).padStart(2, "0");

const civil = {
  fromParts(parts) {
    return { year: parts.year, month: parts.month, day: parts.day };
  },
  key({ year, month, day }) {
    return `${year}-${pad2(month)}-${pad2(day)}`;
  },
  addDays({ year, month, day }, amount) {
    const date = new Date(Date.UTC(year, month - 1, day));
    date.setUTCDate(date.getUTCDate() + amount);
    return {
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      day: date.getUTCDate(),
    };
  },
  weekday({ year, month, day }) {
    return new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  },
};

function formatCivil(civilDate, options) {
  return formatterFor("UTC", options).format(
    new Date(Date.UTC(civilDate.year, civilDate.month - 1, civilDate.day, 12))
  );
}

/* ------------------------------------------------------------------ */
/* Week model                                                          */
/* ------------------------------------------------------------------ */

function computeWeek(now = new Date()) {
  const display = state.config.display;
  const tz = display.timezone;
  const todayCivil = civil.fromParts(zonedParts(now, tz));
  const firstDay = display.weekStartsOn === "sunday" ? 0 : 1;
  const offset = (civil.weekday(todayCivil) - firstDay + 7) % 7;
  const start = civil.addDays(todayCivil, -offset);
  const todayKey = civil.key(todayCivil);
  const days = [];

  for (let index = 0; index < 7; index += 1) {
    const day = civil.addDays(start, index);
    const dayStart = zonedToUtc(day, 0, 0, tz);
    const nextDay = civil.addDays(day, 1);
    days.push({
      civil: day,
      key: civil.key(day),
      startTs: dayStart,
      endTs: zonedToUtc(nextDay, 0, 0, tz),
      isToday: civil.key(day) === todayKey,
      weekday: formatCivil(day, { weekday: "short" }),
      dayNumber: day.day,
    });
  }

  return {
    start,
    end: civil.addDays(start, 7),
    days,
    todayKey,
  };
}

/* ------------------------------------------------------------------ */
/* Small utilities                                                     */
/* ------------------------------------------------------------------ */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function textColor(hex) {
  const value = (hex || "#5b8cff").replace("#", "");
  if (value.length !== 6) return "#ffffff";
  const channel = (index) => {
    const v = Number.parseInt(value.slice(index, index + 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
  return luminance > 0.5 ? "#16181d" : "#ffffff";
}

function formatTime(date, { seconds = false } = {}) {
  return formatterFor(state.config.display.timezone, {
    hour: "numeric",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: state.config.display.timeFormat === "12h",
  }).format(date);
}

function formatHourLabel(hour) {
  const date = new Date(Date.UTC(2024, 0, 1, hour, 0));
  return formatterFor("UTC", {
    hour: "numeric",
    hour12: state.config.display.timeFormat === "12h",
  }).format(date);
}

function shortDay(civilDate) {
  // Build the label explicitly: Intl's weekday+day order varies by build.
  return `${formatCivil(civilDate, { weekday: "short" })} ${civilDate.day}`;
}

function dayRangeText(event) {
  const tz = state.config.display.timezone;
  const start = civil.fromParts(zonedParts(new Date(event.start), tz));
  let endCivil = civil.fromParts(zonedParts(new Date(event.end), tz));

  // ICS and Google both use an exclusive end date for all-day events.
  if (event.allDay) endCivil = civil.addDays(endCivil, -1);

  if (civil.key(start) === civil.key(endCivil)) return shortDay(start);
  return `${shortDay(start)} – ${shortDay(endCivil)}`;
}

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */

function applyConfig() {
  const { display } = state.config;
  document.title = display.title;
  $("#title").textContent = display.title;
  document.documentElement.style.setProperty("--accent", display.accentColor);
  $("#clock").classList.toggle("hidden", !display.showClock);

  const param = new URLSearchParams(location.search).get("theme");
  const forced = param === "light" || param === "dark" ? param : null;
  if (forced) {
    document.documentElement.dataset.theme = forced;
  } else if (display.theme === "light" || display.theme === "dark") {
    document.documentElement.dataset.theme = display.theme;
  }
}

function renderWeekHeader(week) {
  const cells = week.days
    .map(
      (day) => `
      <div class="day-head${day.isToday ? " today" : ""}">
        <div class="dow">${escapeHtml(day.weekday)}</div>
        <div class="dom">${day.dayNumber}</div>
      </div>`
    )
    .join("");
  $("#week-header").innerHTML = `<div class="gutter-spacer"></div>${cells}`;
}

function renderTimeGutter() {
  const { dayStartHour, dayEndHour } = state.config.display;
  const total = dayEndHour - dayStartHour;
  const labels = [];
  for (let hour = dayStartHour; hour <= dayEndHour; hour += 1) {
    const top = ((hour - dayStartHour) / total) * 100;
    const edge =
      hour === dayStartHour ? " first" : hour === dayEndHour ? " last" : "";
    labels.push(
      `<div class="hour-label${edge}" style="top:${top}%">${escapeHtml(
        formatHourLabel(hour)
      )}</div>`
    );
  }
  $("#time-gutter").innerHTML = labels.join("");
}

function renderAllDay(events, week) {
  const container = $("#week-allday");
  const tz = state.config.display.timezone;
  const byDay = new Map(week.days.map((day) => [day.key, []]));

  for (const event of events) {
    if (!event.allDay) continue;
    const startCivil = civil.fromParts(zonedParts(new Date(event.start), tz));
    const startKey = civil.key(startCivil);
    let targetKey = startKey;
    if (!byDay.has(targetKey)) {
      const endCivil = civil.fromParts(zonedParts(new Date(event.end), tz));
      const firstWeek = week.days[0].key;
      const lastWeek = week.days[6].key;
      if (startKey < firstWeek && civil.key(endCivil) >= firstWeek) {
        targetKey = firstWeek;
      } else if (startKey > lastWeek) {
        continue;
      } else {
        continue;
      }
    }
    byDay.get(targetKey).push(event);
  }

  const hasAny = [...byDay.values()].some((list) => list.length);
  if (!hasAny) {
    container.innerHTML = "";
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");

  const cells = week.days
    .map((day) => {
      const chips = (byDay.get(day.key) || [])
        .sort((a, b) => a.start.localeCompare(b.start))
        .map((event) => {
          const color = event.color || "#5b8cff";
          return `<span class="allday-chip" style="background:${color};color:${textColor(
            color
          )}" title="${escapeHtml(event.calendarName)}">
            <span>${escapeHtml(event.title)}</span>
            <span class="d">${escapeHtml(dayRangeText(event))}</span>
          </span>`;
        })
        .join("");
      return `<div class="allday-day">${chips}</div>`;
    })
    .join("");

  container.innerHTML = `<div class="gutter-spacer"></div>${cells}`;
}

function packOverlaps(events) {
  const groups = [];
  let group = [];
  let groupEnd = -Infinity;

  for (const event of events) {
    if (group.length && event.startMin >= groupEnd) {
      groups.push(group);
      group = [];
      groupEnd = -Infinity;
    }
    group.push(event);
    groupEnd = Math.max(groupEnd, event.endMin);
  }
  if (group.length) groups.push(group);

  for (const cluster of groups) {
    const columnEnds = [];
    for (const event of cluster) {
      let column = columnEnds.findIndex((end) => end <= event.startMin);
      if (column === -1) {
        column = columnEnds.length;
        columnEnds.push(event.endMin);
      } else {
        columnEnds[column] = event.endMin;
      }
      event.column = column;
    }
    for (const event of cluster) event.columns = columnEnds.length;
  }
}

function eventsForDay(events, day) {
  const { dayStartHour, dayEndHour, timezone } = state.config.display;
  const rangeStart = dayStartHour * 60;
  const rangeEnd = dayEndHour * 60;
  const segments = [];

  for (const event of events) {
    if (event.allDay) continue;
    const start = new Date(event.start).getTime();
    const end = new Date(event.end).getTime();
    if (end <= day.startTs || start >= day.endTs) continue;

    const visibleStart = Math.max(start, day.startTs);
    const visibleEnd = Math.min(end, day.endTs);
    let startMin = (visibleStart - day.startTs) / 60_000;
    let endMin = (visibleEnd - day.startTs) / 60_000;

    startMin = Math.max(0, Math.min(startMin, 24 * 60));
    endMin = Math.max(0, Math.min(endMin, 24 * 60));
    if (endMin - startMin < 4) continue;

    const clippedStart = Math.max(startMin, rangeStart);
    const clippedEnd = Math.min(endMin, rangeEnd);
    if (clippedEnd <= clippedStart) continue;

    segments.push({
      event,
      startMin: clippedStart,
      endMin: clippedEnd,
      continuesBefore: startMin < rangeStart,
      continuesAfter: endMin > rangeEnd,
      timeLabel:
        start < day.startTs
          ? "All day"
          : formatTime(new Date(start), { seconds: false }),
    });
  }

  segments.sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin);
  packOverlaps(segments);
  return segments;
}

function renderWeekGrid(events, week) {
  const { dayStartHour, dayEndHour } = state.config.display;
  const total = (dayEndHour - dayStartHour) * 60;

  $("#week-grid").innerHTML = week.days
    .map((day) => {
      const blocks = eventsForDay(events, day)
        .map((segment) => {
          const color = segment.event.color || "#5b8cff";
          const top = ((segment.startMin - dayStartHour * 60) / total) * 100;
          const height = ((segment.endMin - segment.startMin) / total) * 100;
          const width = 100 / (segment.columns || 1);
          const left = width * (segment.column || 0);
          const compact = segment.endMin - segment.startMin < 34;

          const time = segment.continuesBefore
            ? ""
            : `<div class="s">${escapeHtml(segment.timeLabel)}${
                segment.continuesAfter ? " →" : ""
              }</div>`;

          return `<div class="event${compact ? " compact" : ""}"
            style="top:${top.toFixed(3)}%;height:${Math.max(height, 1.7).toFixed(
            3
          )}%;left:calc(${left.toFixed(3)}% + 3px);width:calc(${width.toFixed(
            3
          )}% - 6px);background:${color};color:${textColor(color)}"
            title="${escapeHtml(`${segment.event.title} · ${segment.event.calendarName}`)}">
            <div class="t">${escapeHtml(segment.event.title)}</div>
            ${time}
          </div>`;
        })
        .join("");

      return `<div class="day-col${day.isToday ? " today-col" : ""}" data-day="${day.key}">
        ${blocks}
        ${day.isToday ? '<div class="now-line hidden"></div>' : ""}
      </div>`;
    })
    .join("");

  updateNowLine();
  fitGrid();
}

function renderToday(events, week) {
  const { timezone } = state.config.display;
  const today = week.days.find((day) => day.isToday) || week.days[0];
  const now = Date.now();

  const items = [];
  for (const event of events) {
    const start = new Date(event.start).getTime();
    const end = new Date(event.end).getTime();
    if (end <= today.startTs || start >= today.endTs) continue;
    items.push({ event, start, end });
  }

  items.sort((a, b) => {
    if (a.event.allDay !== b.event.allDay) return a.event.allDay ? -1 : 1;
    return a.start - b.start;
  });

  $("#today-heading").textContent = "Today";
  $("#today-date").textContent = formatCivil(today.civil, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  if (!items.length) {
    $("#today-list").innerHTML = `<div class="empty">Nothing scheduled today.</div>`;
    return;
  }

  $("#today-list").innerHTML = items
    .map(({ event, start, end }) => {
      const color = event.color || "#5b8cff";
      let when = "All day";
      if (!event.allDay) {
        const timeText = `${formatTime(new Date(start))} – ${formatTime(new Date(end))}`;
        when = start < now && end > now ? `Now · ${timeText}` : timeText;
      }
      const statusClass =
        !event.allDay && start <= now && end > now
          ? " now"
          : !event.allDay && start > now
          ? " next"
          : "";
      return `<div class="today-item${statusClass}" role="listitem">
        <span class="dot" style="background:${color}"></span>
        <div>
          <div class="when">${escapeHtml(when)}</div>
          <div class="what">${escapeHtml(event.title)}</div>
          ${
            event.location
              ? `<div class="where">${escapeHtml(event.location)}</div>`
              : ""
          }
        </div>
      </div>`;
    })
    .join("");
}

const WEATHER_ICONS = {
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.4 4.4l1.6 1.6M18 18l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.4 19.6L6 18M18 6l1.6-1.6"/></svg>',
  "cloud-sun":
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="8" cy="8" r="3"/><path d="M8 2.5v1.6M2.5 8h1.6M4.1 4.1l1.1 1.1M11.9 4.1l-1.1 1.1"/><path d="M7.5 18h9.8a3.2 3.2 0 0 0 .3-6.4 4.4 4.4 0 0 0-8.4-1A3.7 3.7 0 0 0 7.5 18Z"/></svg>',
  cloud:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6.5 18h11a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6-1.2A4 4 0 0 0 6.5 18Z"/></svg>',
  rain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6.5 15h11a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6-1.2A4 4 0 0 0 6.5 15Z"/><path d="M8 18.5l-.7 2M12 18.5l-.7 2M16 18.5l-.7 2"/></svg>',
  snow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6.5 14h11a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6-1.2A4 4 0 0 0 6.5 14Z"/><path d="M8 18h.01M12 20h.01M16 18h.01"/></svg>',
  storm:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 14h11a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6-1.2A4 4 0 0 0 6.5 14Z"/><path d="M12.5 16l-2 3h2l-1.5 3"/></svg>',
  fog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 9h10M7 12.5h12M4 16h9M7 19.5h10"/></svg>',
};

function renderWeather() {
  const container = $("#weather");
  const config = state.config.weather;
  if (!config.enabled) {
    container.innerHTML = "";
    return;
  }

  const weather = state.weather;
  if (!weather || weather.error) {
    container.innerHTML = `<span class="label">${escapeHtml(
      weather?.error || "Weather unavailable"
    )}</span>`;
    return;
  }

  const icon = WEATHER_ICONS[weather.icon] || WEATHER_ICONS.cloud;
  const today = (weather.days || [])[0];
  container.innerHTML = `
    <div class="row">
      <span class="w-icon">${icon}</span>
      <span class="temp">${weather.temperature}°${weather.units}</span>
    </div>
    <span class="label">${escapeHtml(weather.label)} · ${escapeHtml(
      weather.location
    )}</span>
    ${
      today
        ? `<span class="hi-lo">H ${today.high}° · L ${today.low}°</span>`
        : ""
    }`;
}

function renderBanner() {
  const banner = $("#banner");
  const messages = [];

  if (state.failed) {
    messages.push("Can't reach the calendar server — retrying…");
  }
  const failedNames = Object.keys(state.errors).map(
    (id) => state.config.calendars.find((calendar) => calendar.id === id)?.name || id
  );
  if (failedNames.length) {
    messages.push(
      `${failedNames.join(", ")} couldn't refresh — showing the last saved copy.`
    );
  }

  if (!messages.length) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = messages.join(" ");
  banner.classList.remove("hidden");
}

function renderStatus() {
  const status = $("#status");
  if (state.failed) {
    status.textContent = "Offline";
    return;
  }
  if (!state.lastUpdated) {
    status.textContent = state.loading ? "Loading…" : "";
    return;
  }
  status.textContent = `Updated ${formatTime(state.lastUpdated)}`;
}

function tickClock() {
  if (!state.config) return;
  const display = state.config.display;
  if (display.showClock) {
    $("#clock").textContent = formatTime(new Date());
  }
  updateNowLine();
}

function updateNowLine() {
  if (!state.week) return;
  const { dayStartHour, dayEndHour, timezone } = state.config.display;
  const now = new Date();
  const nowParts = zonedParts(now, timezone);
  const nowMinutes = nowParts.hour * 60 + nowParts.minute;
  const inRange = nowMinutes >= dayStartHour * 60 && nowMinutes <= dayEndHour * 60;
  const top = ((nowMinutes - dayStartHour * 60) / ((dayEndHour - dayStartHour) * 60)) * 100;

  document.querySelectorAll(".now-line").forEach((line) => {
    if (!inRange) {
      line.classList.add("hidden");
      return;
    }
    line.style.top = `${top}%`;
    line.classList.remove("hidden");
  });
}

function fitGrid() {
  const { dayStartHour, dayEndHour } = state.config.display;
  const hours = dayEndHour - dayStartHour;
  const body = $("#week-body");
  const available = Math.max(body.clientHeight, 240);
  const perHour = Math.max(24, available / hours);
  const height = Math.max(available, perHour * hours);

  $("#week-grid").style.height = `${height}px`;
  $("#time-gutter").style.height = `${height}px`;
}

/* ------------------------------------------------------------------ */
/* Data fetching                                                       */
/* ------------------------------------------------------------------ */

async function fetchJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function refresh() {
  if (!state.config) return;
  const week = computeWeek();
  state.week = week;
  const timezone = state.config.display.timezone;
  const start = new Date(zonedToUtc(week.start, 0, 0, timezone)).toISOString();
  const end = new Date(zonedToUtc(week.end, 0, 0, timezone)).toISOString();
  const theme = new URLSearchParams({ start, end });

  const tasks = [fetchJson(`/api/events?${theme.toString()}`)];
  if (state.config.weather.enabled) tasks.push(fetchJson("/api/weather"));

  try {
    const [eventsPayload, weatherPayload] = await Promise.all(tasks);
    state.events = Array.isArray(eventsPayload.events) ? eventsPayload.events : [];
    state.errors = eventsPayload.errors || {};
    state.failed = false;
    state.lastUpdated = new Date();
    if (weatherPayload) state.weather = weatherPayload;
    state.loading = false;
    render();
  } catch (error) {
    console.warn("Calendar refresh failed", error);
    state.failed = true;
    state.loading = false;
    // Keep whatever is on screen; the backend also serves cached feeds.
    renderBanner();
    renderStatus();
  }
}

function render() {
  const week = state.week;
  if (!week) return;

  const rangeText = `${formatCivil(week.start, {
    month: "short",
    day: "numeric",
  })} – ${formatCivil(week.days[6].civil, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;

  $("#subtitle").textContent = rangeText;
  renderWeekHeader(week);
  renderTimeGutter();
  renderAllDay(state.events, week);
  renderWeekGrid(state.events, week);
  renderToday(state.events, week);
  renderWeather();
  renderStatus();
  renderBanner();
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */

function dayKeyNow() {
  return civil.key(civil.fromParts(zonedParts(new Date(), state.config.display.timezone)));
}

async function boot() {
  try {
    state.config = await fetchJson("/api/config");
  } catch (error) {
    console.error("Could not load config", error);
    $("#subtitle").textContent = "Calendar server unreachable";
    $("#banner").textContent = "Can't reach the calendar server — retrying…";
    $("#banner").classList.remove("hidden");
    setTimeout(boot, 5000);
    return;
  }

  applyConfig();
  state.dayKey = dayKeyNow();
  await refresh();

  const refreshMs = Math.max(15, state.config.display.refreshSeconds) * 1000;
  setInterval(refresh, refreshMs);
  setInterval(tickClock, 1000);
  setInterval(() => {
    if (state.config && dayKeyNow() !== state.dayKey) {
      state.dayKey = dayKeyNow();
      refresh();
    }
  }, 30_000);

  window.addEventListener("resize", fitGrid);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      tickClock();
      refresh();
    }
  });

  tickClock();
  renderStatus();

  // Keep the kiosk fresh across long uptimes and midnight rollovers.
  setTimeout(() => window.location.reload(), 24 * 60 * 60 * 1000);
}

boot();
