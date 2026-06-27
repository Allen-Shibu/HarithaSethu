const API_BASE = "http://127.0.0.1:8000";
const CENTER = [11.615, 75.855];
const BOUNDS = [
  [11.548, 75.792],
  [11.681, 75.907],
];
const MAPS = [];
let isSyncingMaps = false;

async function getJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json();
}

function buildAlerts(alerts) {
  const list = document.querySelector("#alerts-list");
  list.innerHTML = "";

  const rows = alerts.length
    ? alerts
    : [
        {
          title: "High Vegetation Loss",
          message: "Ward 4 - Northern Region. Area: 12.6 ha",
        },
        {
          title: "Water Body Shrinking",
          message: "Pond near Kakkodi. Area: 2.1 ha",
        },
        {
          title: "New Construction Detected",
          message: "Ward 7 - Eastern Region. New Buildings: 3",
        },
      ];

  rows.slice(0, 3).forEach((alert) => {
    const item = document.createElement("article");
    item.innerHTML = `<strong>${alert.title}</strong><p>${alert.message}</p><small>${alert.level || "active"}</small>`;
    list.appendChild(item);
  });
}

function updateReport(report) {
  document.querySelector("#score").textContent = `${report.summary.environmental_score}/100`;
  document.querySelector("#score-meter").value = report.summary.environmental_score;

  const reportList = document.querySelector("#report-list");
  reportList.innerHTML = "";
  [
    `Green cover is estimated at ${report.summary.green_cover_percent.toFixed(1)}%.`,
    `Water body signal is estimated at ${report.summary.water_bodies_percent.toFixed(1)}%.`,
    `Built-up area is estimated at ${report.summary.built_up_percent.toFixed(1)}%.`,
    `Current NDVI is ${report.indices.ndvi.toFixed(3)} and NDWI is ${report.indices.ndwi.toFixed(3)}.`,
    `Environmental score is ${report.summary.environmental_score}/100.`,
  ].forEach((line) => {
    const item = document.createElement("li");
    item.textContent = line;
    reportList.appendChild(item);
  });

  buildAlerts(report.alerts || []);
}

function createMap(id, boundary, tileUrl, options = {}) {
  if (!window.L) return;

  const map = L.map(id, {
    attributionControl: false,
    zoomControl: false,
    dragging: true,
    scrollWheelZoom: false,
    doubleClickZoom: false,
  }).setView(CENTER, 13);

  const base = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 18 }
  );
  base.addTo(map);

  L.control.scale({ metric: true, imperial: false }).addTo(map);

  if (window.L.graticule) {
    L.graticule({ interval: 0.03 }).addTo(map);
  }

  if (tileUrl) {
    L.tileLayer(tileUrl, {
      opacity: options.opacity ?? 0.72,
      minZoom: 1,
      maxZoom: 18,
    }).addTo(map);
  }

  L.geoJSON(boundary, {
    style: {
      color: options.boundaryColor || "#9ccc65",
      weight: 2,
      fillColor: "transparent",
      fillOpacity: 0,
    },
  }).addTo(map);

  map.fitBounds(BOUNDS, { padding: [8, 8] });
  MAPS.push(map);
  return map;
}

function addTileOverlay(map, tileUrl, options = {}) {
  if (!map || !tileUrl || !window.L) return;

  L.tileLayer(tileUrl, {
    opacity: options.opacity ?? 0.72,
    minZoom: 1,
    maxZoom: 18,
  }).addTo(map);
}

function syncMaps() {
  MAPS.forEach((sourceMap) => {
    sourceMap.on("move", () => {
      if (isSyncingMaps) {
        return;
      }

      isSyncingMaps = true;
      const center = sourceMap.getCenter();
      const zoom = sourceMap.getZoom();

      MAPS.forEach((targetMap) => {
        if (targetMap === sourceMap) {
          return;
        }

        targetMap.setView(center, zoom, { animate: false });
      });

      isSyncingMaps = false;
    });
  });
}

async function boot() {
  try {
    const [report, tiles, boundary] = await Promise.all([
      getJson("/api/report"),
      getJson("/api/tiles"),
      getJson("/api/boundary"),
    ]);

    updateReport(report);

    const beforeTile = tiles.tiles?.true_color_before?.url;
    const afterTile = tiles.tiles?.true_color_after?.url;
    const changeTile = tiles.tiles?.ndvi_change?.url;
    const constructionTile = tiles.tiles?.new_construction?.url;
    createMap("map-before", boundary, beforeTile, { opacity: 1 });
    createMap("map-after", boundary, afterTile, { opacity: 1 });
    const changeMap = createMap("map-change", boundary, changeTile, {
      opacity: 0.85,
      boundaryColor: "#243518",
    });
    addTileOverlay(changeMap, constructionTile, { opacity: 0.9 });
    createMap("map-buildup", boundary, constructionTile, {
      opacity: 0.9,
      boundaryColor: "#FF4444",
    });
    syncMaps();
  } catch (error) {
    console.error(error);
    buildAlerts([]);
  }
}

boot();
