/* Historical, read-only view of the approved and checksum-verified score snapshot. */
const $ = (id) => document.getElementById(id);
const state = {
  meta: null,
  view: null,
  bounds: null,
  cells: [],
  features: [],
  selectedFeatures: [],
  selectedSegment: null,
  dragging: null,
  mapRequest: 0,
  updateRequest: 0,
};

const number = (value, digits = 2) =>
  value == null ? "Unavailable" : Number(value).toFixed(digits);
const text = (value) => value == null || value === "" ? "Unavailable" : String(value);

function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error((await response.json()).detail || response.statusText);
  }
  return response.json();
}

function viewParams(view, extra = {}) {
  const params = new URLSearchParams({cutoff: view.cutoff, budget: view.budget, ...extra});
  if (view.region) params.set("region", view.region);
  if (view.roadClass) params.set("road_class", view.roadClass);
  return params;
}

function makeOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

async function facets(cutoff) {
  const data = await api("/api/v1/facets?cutoff=" + encodeURIComponent(cutoff));
  for (const [id, key, defaultLabel] of [
    ["region", "regions", "All regions"],
    ["road-class", "road_classes", "All classes"],
  ]) {
    const select = $(id);
    const previous = select.value;
    select.replaceChildren(makeOption("", defaultLabel), ...data[key].map((x) => makeOption(x, x)));
    if (data[key].includes(previous)) select.value = previous;
  }
}

function project(lon, lat, bounds, canvas) {
  const [west, south, east, north] = bounds;
  return [
    (lon - west) / (east - west) * canvas.width,
    (north - lat) / (north - south) * canvas.height,
  ];
}

function lines(feature) {
  return feature.geometry.type === "LineString"
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates;
}

function strokeFeature(ctx, canvas, feature, colour, width) {
  ctx.beginPath();
  for (const line of lines(feature)) {
    line.forEach(([lon, lat], index) => {
      const [x, y] = project(lon, lat, state.bounds, canvas);
      if (index) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
  }
  ctx.strokeStyle = colour;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke();
}

function draw() {
  if (!state.bounds) return;
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#e9f2f1";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const maximum = Math.max(0.01, ...state.cells.map((cell) => cell.mean_predicted_weight));
  for (const cell of state.cells) {
    const [x1, y1] = project(cell.west, cell.north, state.bounds, canvas);
    const [x2, y2] = project(cell.east, cell.south, state.bounds, canvas);
    const intensity = Math.sqrt(Math.min(1, cell.mean_predicted_weight / maximum));
    ctx.fillStyle = `rgba(${Math.round(246 - 61 * intensity)},${Math.round(195 - 125 * intensity)},${Math.round(136 - 100 * intensity)},.75)`;
    ctx.fillRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));
    if (cell.withheld_count) {
      ctx.strokeStyle = "#506676";
      ctx.lineWidth = 1;
      ctx.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));
    }
  }

  for (const feature of state.features) {
    strokeFeature(ctx, canvas, feature, feature.properties.abstain ? "#506676" : "#9b6758", 1.5);
  }

  // Draw the complete in-view shortlist after the capped road-detail sample.
  for (const feature of state.selectedFeatures) {
    strokeFeature(ctx, canvas, feature, "#ffffff", 6);
    strokeFeature(ctx, canvas, feature, "#006b83", 3.5);
    if (state.bounds[2] - state.bounds[0] > 2) {
      const line = lines(feature).find((part) => part.length) || [];
      const coordinate = line[Math.floor(line.length / 2)];
      if (coordinate) {
        const [x, y] = project(coordinate[0], coordinate[1], state.bounds, canvas);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, 2 * Math.PI);
        ctx.fillStyle = "#006b83";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }

  const focused = [...state.selectedFeatures, ...state.features]
    .find((feature) => feature.id === state.selectedSegment);
  if (focused) {
    strokeFeature(ctx, canvas, focused, "#ffffff", 8);
    strokeFeature(ctx, canvas, focused, "#063549", 4.5);
  }
}

function gridSize() {
  const width = state.bounds[2] - state.bounds[0];
  return width > 8 ? .5 : width > 2 ? .2 : .05;
}

async function mapLoad() {
  if (!state.view) return;
  const request = ++state.mapRequest;
  const view = state.view;
  const bbox = state.bounds.join(",");
  const common = viewParams(view, {bbox});
  const [cells, segments, selected] = await Promise.all([
    api("/api/v1/map/cells?" + new URLSearchParams({cutoff: view.cutoff, grid_size: gridSize(), bbox})),
    api("/api/v1/map/segments?" + viewParams(view, {
      bbox, limit: state.meta.maximum_map_features,
    })),
    api("/api/v1/map/selected?" + common),
  ]);
  if (request !== state.mapRequest || view !== state.view) return;
  state.cells = cells.cells;
  state.features = segments.features;
  state.selectedFeatures = selected.features;
  draw();
  $("map-budget-note").textContent =
    `${selected.visible_rows} of ${selected.selected_rows} budget-selected segments highlighted in this view.`;
  $("map-status").textContent =
    `${cells.total_cells} fixed risk-overview cells; ${segments.features.length} of ${segments.total} other intersecting segments shown` +
    (segments.truncated ? " (detail sample capped—zoom in)." : ".");
}

function rankRow(item) {
  const row = document.createElement("tr");
  const values = [
    text(item.statewide_rank),
    null,
    number(item.predicted_weight, 3),
    `${number(item.prediction_lower, 2)}–${number(item.prediction_upper, 2)}`,
    text(item.exposure_quality_tier),
  ];
  for (const value of values) {
    const cell = document.createElement("td");
    if (value === null) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${text(item.road_name)} · ${item.segment_id}`;
      button.addEventListener("click", () => detail(item.segment_id));
      cell.append(button);
    } else {
      cell.textContent = value;
    }
    row.append(cell);
  }
  return row;
}

async function update() {
  const request = ++state.updateRequest;
  try {
    const next = {
      cutoff: $("cutoff").value,
      budget: Number($("budget").value),
      region: $("region").value,
      roadClass: $("road-class").value,
    };
    if (!Number.isInteger(next.budget) || next.budget < 1 || next.budget > state.meta.maximum_budget) {
      throw new Error(`Budget must be 1–${state.meta.maximum_budget}`);
    }
    status("Loading historical rankings and map…");
    const result = await api("/api/v1/rankings?" + viewParams(next));
    if (request !== state.updateRequest) return;
    state.view = next;
    state.selectedSegment = null;
    $("rankings").replaceChildren(...result.items.map(rankRow));
    $("ranking-summary").textContent =
      `${result.selected_rows} shortlisted from ${result.eligible_rows} eligible segments. ` +
      `${result.withheld_rows} withheld by the uncertainty rule within ${result.population_rows} segments in scope. ` +
      "The same shortlist is highlighted on the map.";
    for (const [id, format] of [["geojson", "geojson"], ["geoparquet", "geoparquet"]]) {
      $(id).href = "/api/v1/export?" + viewParams(next, {format});
    }
    $("period-note").textContent =
      `Cutoff ${result.cutoff_date}; forecast period ${result.forecast_start} to ${result.forecast_end}.`;
    await mapLoad();
    if (request === state.updateRequest) {
      status("Historical decision view ready. Scores are not current forecasts.");
    }
  } catch (error) {
    if (request === state.updateRequest) status(error.message, true);
  }
}

async function detail(segmentId) {
  try {
    const data = await api(
      `/api/v1/segments/${encodeURIComponent(segmentId)}?cutoff=${encodeURIComponent(state.view.cutoff)}`
    );
    const segment = data.segment;
    const quality = data.data_quality;
    state.selectedSegment = segmentId;
    draw();
    const list = document.createElement("dl");
    const fields = [
      ["Road", segment.road_name],
      ["Segment ID", segment.segment_id],
      ["Expected serious-crash weight", number(segment.predicted_weight, 3)],
      ["Prediction interval", `${number(segment.prediction_lower)}–${number(segment.prediction_upper)}`],
      ["Occurrence probability", number(100 * segment.predicted_occurrence_probability, 1) + "%"],
      ["Ranking status", segment.abstain
        ? `Withheld: ${text(segment.abstention_reason)}`
        : `Eligible; statewide rank ${text(segment.statewide_rank)}`],
      ["Traffic exposure tier", quality.exposure_tier],
      ["AADT / reference year", `${text(segment.aadt)} / ${text(quality.aadt_reference_year)}`],
      ["Forecast exposure (vehicle-km)", number(segment.forecast_exposure_vkt, 0)],
      ["Geometry quality", quality.geometry_quality],
      ["Historical geometry status", quality.geometry_history_status],
      ["Interval group supported", text(quality.interval_group_supported)],
      ["Previous 4-quarter weighted count", number(segment.serious_crash_weight_lag_4q)],
      ["Out-of-distribution diagnostic", text(quality.diagnostic_ood)],
      ["Disagreement diagnostic", text(quality.diagnostic_disagreement)],
      ["Wide-interval diagnostic", text(quality.diagnostic_wide_interval)],
    ];
    for (const [label, value] of fields) {
      const box = document.createElement("div");
      box.className = "detail-item";
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = text(value);
      box.append(term, description);
      list.append(box);
    }
    $("detail").replaceChildren(list);
    const note = document.createElement("p");
    note.textContent = data.interpretation;
    $("detail").append(note);
    $("detail-title").focus();
  } catch (error) {
    status(error.message, true);
  }
}

function zoom(factor) {
  const [west, south, east, north] = state.bounds;
  const centerX = (west + east) / 2;
  const centerY = (south + north) / 2;
  const halfWidth = (east - west) * factor / 2;
  const halfHeight = (north - south) * factor / 2;
  state.bounds = [centerX - halfWidth, centerY - halfHeight, centerX + halfWidth, centerY + halfHeight];
  mapLoad().catch((error) => status(error.message, true));
}

function pan(horizontal, vertical) {
  const [west, south, east, north] = state.bounds;
  const dx = (east - west) * horizontal;
  const dy = (north - south) * vertical;
  state.bounds = [west + dx, south + dy, east + dx, north + dy];
  mapLoad().catch((error) => status(error.message, true));
}

function mapInteractions() {
  const canvas = $("map");
  $("zoom-in").onclick = () => zoom(.65);
  $("zoom-out").onclick = () => zoom(1.55);
  $("reset-map").onclick = () => {
    state.bounds = [...state.meta.bounds_wgs84];
    mapLoad().catch((error) => status(error.message, true));
  };
  canvas.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "-"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "+") zoom(.65);
    else if (event.key === "-") zoom(1.55);
    else pan(
      event.key === "ArrowLeft" ? -.15 : event.key === "ArrowRight" ? .15 : 0,
      event.key === "ArrowUp" ? .15 : event.key === "ArrowDown" ? -.15 : 0
    );
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY < 0 ? .8 : 1.25);
  }, {passive: false});
  canvas.addEventListener("pointerdown", (event) => {
    state.dragging = [event.clientX, event.clientY];
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointerup", (event) => {
    if (!state.dragging) return;
    const dx = event.clientX - state.dragging[0];
    const dy = event.clientY - state.dragging[1];
    state.dragging = null;
    if (Math.abs(dx) + Math.abs(dy) > 5) {
      pan(-dx / canvas.clientWidth, dy / canvas.clientHeight);
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * canvas.width;
    const y = (event.clientY - rect.top) / rect.height * canvas.height;
    const [west, south, east, north] = state.bounds;
    const lon = west + x / canvas.width * (east - west);
    const lat = north - y / canvas.height * (north - south);
    let closest = null;
    let distance = Infinity;
    for (const feature of [...state.selectedFeatures, ...state.features]) {
      for (const line of lines(feature)) {
        for (const [a, b] of line) {
          const candidate = (a - lon) ** 2 + ((b - lat) * 1.5) ** 2;
          if (candidate < distance) {
            distance = candidate;
            closest = feature.id;
          }
        }
      }
    }
    if (closest && distance < ((east - west) / 30) ** 2) detail(closest);
  });
}

async function start() {
  try {
    state.meta = await api("/api/v1/meta");
    state.bounds = [...state.meta.bounds_wgs84];
    $("budget").max = state.meta.maximum_budget;
    $("budget").value = state.meta.default_budget;
    for (const period of state.meta.periods) {
      $("cutoff").append(makeOption(
        period.cutoff_date, `${period.forecast_start}–${period.forecast_end}`
      ));
    }
    $("cutoff").value = state.meta.periods.at(-1).cutoff_date;
    $("provenance").textContent =
      `Model: ${state.meta.model_name} (${state.meta.model_run_version}); ` +
      `network: ${state.meta.network_version}; serving snapshot: ${state.meta.run_version}. ` +
      `Source fold: ${state.meta.source_fold}.`;
    for (const item of state.meta.limitations) {
      const entry = document.createElement("li");
      entry.textContent = item;
      $("limitations").append(entry);
    }
    $("cutoff").addEventListener("change", async () => {
      try {
        await facets($("cutoff").value);
        await update();
      } catch (error) {
        status(error.message, true);
      }
    });
    $("apply").onclick = update;
    mapInteractions();
    await facets($("cutoff").value);
    await update();
  } catch (error) {
    status(error.message, true);
  }
}

start();
