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

  // Update dynamic metric display cards
  const greenDelta = document.querySelector("#green-delta");
  if (greenDelta) {
    greenDelta.textContent = `${report.summary.green_cover_percent.toFixed(1)}%`;
    if (greenDelta.nextElementSibling) {
      greenDelta.nextElementSibling.textContent = "Total Green Cover";
    }
  }

  const waterDelta = document.querySelector("#water-delta");
  if (waterDelta) {
    waterDelta.textContent = `${report.summary.water_bodies_percent.toFixed(1)}%`;
    if (waterDelta.nextElementSibling) {
      waterDelta.nextElementSibling.textContent = "Surface Water Signal";
    }
  }

  const builtDelta = document.querySelector("#built-delta");
  if (builtDelta) {
    builtDelta.textContent = `+${report.summary.built_up_area_ha.toFixed(2)} ha`;
    if (builtDelta.nextElementSibling) {
      builtDelta.nextElementSibling.textContent = "New Built-up Area";
    }
  }

  // Update Built-up bar in the Changes by Category chart
  const bars = document.querySelectorAll(".bar-chart .bar");
  if (bars && bars[2]) {
    const builtUpBar = bars[2];
    const val = Math.min(100, Math.max(10, Math.round(report.summary.built_up_area_ha * 10)));
    builtUpBar.style.setProperty("--v", val.toString());
    const builtUpSpan = builtUpBar.querySelector("span");
    if (builtUpSpan) {
      builtUpSpan.textContent = `+${report.summary.built_up_area_ha.toFixed(2)} ha`;
    }
  }

  const reportList = document.querySelector("#report-list");
  reportList.innerHTML = "";
  [
    `Green cover is estimated at ${report.summary.green_cover_percent.toFixed(1)}%.`,
    `Water body signal is estimated at ${report.summary.water_bodies_percent.toFixed(1)}%.`,
    `New built-up area detected is ${report.summary.built_up_area_ha.toFixed(2)} ha.`,
    `Current NDVI is ${report.indices.ndvi.toFixed(3)} and NDWI is ${report.indices.ndwi.toFixed(3)}.`,
    `Environmental score is ${report.summary.environmental_score}/100.`,
  ].forEach((line) => {
    const item = document.createElement("li");
    item.textContent = line;
    reportList.appendChild(item);
  });

  buildAlerts(report.alerts || []);
}

// Convert a lat/lon centroid to the ESRI World Imagery tile URL that contains it.
// Zoom 18 gives ~75m × 75m per tile — ideal for a single building or small cluster.
function centroidToTileUrl(lat, lon, zoom = 18) {
  const n = Math.pow(2, zoom);
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n
  );
  return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${y}/${x}`;
}

function buildChipGrid(buildup) {
  const grid = document.querySelector("#chips-grid");
  const countEl = document.querySelector("#chip-count");
  if (!grid) return;

  const clusters = buildup?.clusters ?? [];

  if (clusters.length === 0) {
    grid.innerHTML = `<p class="chips-empty">No clusters detected. Run <code>gee/fetch_change.py</code> to populate.</p>`;
    return;
  }

  countEl.textContent = `${clusters.length} site${clusters.length !== 1 ? "s" : ""}`;
  grid.innerHTML = "";

  clusters.forEach((cluster, i) => {
    const imgUrl = centroidToTileUrl(cluster.lat, cluster.lon, 18);
    const areaLabel =
      cluster.area_m2 >= 10_000
        ? `${(cluster.area_m2 / 10_000).toFixed(2)} ha`
        : `${Math.round(cluster.area_m2)} m²`;

    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = `
      <img src="${imgUrl}" alt="Construction site ${i + 1}" loading="lazy" />
      <div class="chip-info">
        <span class="chip-label">Site ${i + 1}</span>
        <span class="chip-area">${areaLabel}</span>
      </div>
    `;
    grid.appendChild(chip);
  });
}


// Everything OUTSIDE the boundary gets a dark overlay; the interior stays clear.
function addBoundaryMask(map, boundary) {
  if (!window.L) return;

  // Large outer ring that covers the entire world
  const worldRing = [
    [-90, -180], [90, -180], [90, 180], [-90, 180], [-90, -180],
  ];

  // Collect every polygon ring from the boundary GeoJSON as holes
  const innerRings = [];
  (boundary.features || []).forEach((feature) => {
    const { type, coordinates } = feature.geometry;
    if (type === "Polygon") {
      innerRings.push(coordinates[0]); // exterior ring of the polygon
    } else if (type === "MultiPolygon") {
      coordinates.forEach((poly) => innerRings.push(poly[0]));
    }
  });

  const maskFeature = {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [worldRing, ...innerRings],
    },
    properties: {},
  };

  L.geoJSON(maskFeature, {
    style: {
      color: "transparent",
      weight: 0,
      fillColor: "#0d1117",
      fillOpacity: 0.9,
    },
    interactive: false,
  }).addTo(map);
}

let mapBefore, mapAfter, mapChange, mapBuildup;

function createMap(id, boundary, tileUrl, options = {}) {
  if (!window.L) return;

  const map = L.map(id, {
    attributionControl: false,
    zoomControl: true,          // every map gets +/- buttons
    dragging: true,
    scrollWheelZoom: false,     // button-only zoom as requested
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
    const layer = L.tileLayer(tileUrl, {
      opacity: options.opacity ?? 0.72,
      minZoom: 1,
      maxZoom: 18,
    });
    layer.addTo(map);
    map.dynamicLayer = layer;
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

  // Apply extra zoom-in after fitBounds when caller requests a specific level
  if (options.zoom != null) {
    map.setZoom(options.zoom);
  }

  MAPS.push(map);
  return map;
}

function addTileOverlay(map, tileUrl, options = {}) {
  if (!map || !tileUrl || !window.L) return;

  const layer = L.tileLayer(tileUrl, {
    opacity: options.opacity ?? 0.72,
    minZoom: 1,
    maxZoom: 18,
  });
  layer.addTo(map);
  map.overlayLayer = layer;
}

function updateMapTile(map, newUrl) {
  if (!map || !window.L) return;
  if (map.dynamicLayer) {
    if (newUrl) {
      map.dynamicLayer.setUrl(newUrl);
    } else {
      map.removeLayer(map.dynamicLayer);
      map.dynamicLayer = null;
    }
  } else if (newUrl) {
    const layer = L.tileLayer(newUrl, {
      opacity: 0.72,
      minZoom: 1,
      maxZoom: 18,
    });
    layer.addTo(map);
    map.dynamicLayer = layer;
  }
}

function updateMapOverlay(map, newUrl) {
  if (!map || !window.L) return;
  if (map.overlayLayer) {
    if (newUrl) {
      map.overlayLayer.setUrl(newUrl);
    } else {
      map.removeLayer(map.overlayLayer);
      map.overlayLayer = null;
    }
  } else if (newUrl) {
    const layer = L.tileLayer(newUrl, {
      opacity: 0.9,
      minZoom: 1,
      maxZoom: 18,
    });
    layer.addTo(map);
    map.overlayLayer = layer;
  }
}

function getMonthLabel(monthStr) {
  if (!monthStr) return "";
  const parts = monthStr.split("-");
  if (parts.length < 2) return monthStr;
  const year = parts[0];
  const month = parseInt(parts[1], 10);
  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];
  return `${monthNames[month - 1]} ${year}`;
}

async function updateDashboard(beforeMonth, afterMonth) {
  const btn = document.querySelector("#btn-generate");
  const selectBefore = document.querySelector("#select-before");
  const selectAfter = document.querySelector("#select-after");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Computing...";
  }
  if (selectBefore) selectBefore.disabled = true;
  if (selectAfter) selectAfter.disabled = true;

  try {
    const query = `?before=${beforeMonth}&after=${afterMonth}`;
    const [report, tiles, buildupData] = await Promise.all([
      getJson(`/api/report${query}`),
      getJson(`/api/tiles${query}`),
      getJson(`/api/buildup${query}`),
    ]);

    // Update dynamic text in dashboard panels
    const labelBefore = document.querySelector("#label-before");
    const labelAfter = document.querySelector("#label-after");
    if (labelBefore) labelBefore.textContent = getMonthLabel(beforeMonth);
    if (labelAfter) labelAfter.textContent = getMonthLabel(afterMonth);

    updateReport(report);
    buildChipGrid(buildupData?.buildup);

    const beforeTile = tiles.tiles?.true_color_before?.url;
    const afterTile = tiles.tiles?.true_color_after?.url;
    const changeTile = tiles.tiles?.ndvi_change?.url;
    const constructionTile = tiles.tiles?.new_construction?.url;

    if (mapBefore) updateMapTile(mapBefore, beforeTile);
    if (mapAfter) updateMapTile(mapAfter, afterTile);
    
    if (mapChange) {
      updateMapTile(mapChange, changeTile);
      updateMapOverlay(mapChange, constructionTile);
    }
    
    if (mapBuildup) {
      updateMapTile(mapBuildup, constructionTile);
    }
  } catch (err) {
    console.error("Dashboard update failed:", err);
    alert(`Earth Engine comparison failed to load: ${err.message || err}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Generate Report";
    }
    if (selectBefore) selectBefore.disabled = false;
    if (selectAfter) selectAfter.disabled = false;
  }
}

function syncMaps() {
  MAPS.forEach((sourceMap) => {
    sourceMap.on("move", () => {
      if (isSyncingMaps) {
        return;
      }

      isSyncingMaps = true;
      const center = sourceMap.getCenter();

      MAPS.forEach((targetMap) => {
        if (targetMap === sourceMap) {
          return;
        }

        // Pan to the same center but keep each map's own zoom level
        targetMap.setView(center, targetMap.getZoom(), { animate: false });
      });

      isSyncingMaps = false;
    });
  });
}

async function boot() {
  try {
    const [report, tiles, boundary, buildupData] = await Promise.all([
      getJson("/api/report"),
      getJson("/api/tiles"),
      getJson("/api/boundary"),
      getJson("/api/buildup"),
    ]);

    // Parse defaults from metadata
    let beforeMonth = "2024-05";
    let afterMonth = "2024-06";
    if (report.metadata?.before_month) {
      beforeMonth = report.metadata.before_month;
    } else if (report.metadata?.before_composite?.start) {
      beforeMonth = report.metadata.before_composite.start.substring(0, 7);
    }
    if (report.metadata?.after_month) {
      afterMonth = report.metadata.after_month;
    } else if (report.metadata?.after_composite?.start) {
      afterMonth = report.metadata.after_composite.start.substring(0, 7);
    }

    const selectBefore = document.querySelector("#select-before");
    const selectAfter = document.querySelector("#select-after");
    if (selectBefore) selectBefore.value = beforeMonth;
    if (selectAfter) selectAfter.value = afterMonth;

    const labelBefore = document.querySelector("#label-before");
    const labelAfter = document.querySelector("#label-after");
    if (labelBefore) labelBefore.textContent = getMonthLabel(beforeMonth);
    if (labelAfter) labelAfter.textContent = getMonthLabel(afterMonth);

    updateReport(report);
    buildChipGrid(buildupData?.buildup);

    const beforeTile = tiles.tiles?.true_color_before?.url;
    const afterTile = tiles.tiles?.true_color_after?.url;
    const changeTile = tiles.tiles?.ndvi_change?.url;
    const constructionTile = tiles.tiles?.new_construction?.url;

    mapBefore = createMap("map-before", boundary, beforeTile, { opacity: 1 });
    mapAfter = createMap("map-after", boundary, afterTile, { opacity: 1 });
    mapChange = createMap("map-change", boundary, changeTile, {
      opacity: 0.85,
      boundaryColor: "#243518",
    });
    addTileOverlay(mapChange, constructionTile, { opacity: 0.9 });
    mapBuildup = createMap("map-buildup", boundary, constructionTile, {
      opacity: 0.9,
      boundaryColor: "#FF4444",
      zoom: 15,
    });
    addBoundaryMask(mapBuildup, boundary);
    syncMaps();

    // Register period selection listener and change listeners
    const btn = document.querySelector("#btn-generate");

    function triggerUpdate() {
      const beforeVal = selectBefore ? selectBefore.value : "2024-05";
      const afterVal = selectAfter ? selectAfter.value : "2024-06";
      if (beforeVal === afterVal) {
        alert("Please select two different months for comparison.");
        return;
      }
      updateDashboard(beforeVal, afterVal);
    }

    if (btn) {
      btn.addEventListener("click", triggerUpdate);
    }
    if (selectBefore) {
      selectBefore.addEventListener("change", triggerUpdate);
    }
    if (selectAfter) {
      selectAfter.addEventListener("change", triggerUpdate);
    }
  } catch (error) {
    console.error(error);
    buildAlerts([]);
  }
}

boot();
