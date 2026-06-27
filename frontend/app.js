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
    const data = await getJson(`/api/compare?monthA=${beforeMonth}&monthB=${afterMonth}`);
    
    // Update header labels
    updateLabels(beforeMonth, afterMonth);
    
    // Update maps tile URLs
    if (mapBefore) updateMapTile(mapBefore, data.tiles.before);
    if (mapAfter) updateMapTile(mapAfter, data.tiles.after);
    
    if (mapChange) {
      updateMapTile(mapChange, data.tiles.ndvi_change);
      updateMapOverlay(mapChange, data.tiles.new_construction);
    }
    
    if (mapBuildup) {
      updateMapTile(mapBuildup, data.tiles.new_construction);
    }
    
    // Update UI panels
    updateDashboardUI(data, beforeMonth, afterMonth);
    
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

function updateLabels(beforeMonth, afterMonth) {
  const labelBefore = document.querySelector("#label-before");
  const labelAfter = document.querySelector("#label-after");
  const labelBeforeChange = document.querySelector("#label-before-change");
  const labelAfterChange = document.querySelector("#label-after-change");
  const labelBeforeBuildup = document.querySelector("#label-before-buildup");
  const labelAfterBuildup = document.querySelector("#label-after-buildup");

  const labelBeforeVal = getMonthLabel(beforeMonth);
  const labelAfterVal = getMonthLabel(afterMonth);

  if (labelBefore) labelBefore.textContent = labelBeforeVal;
  if (labelAfter) labelAfter.textContent = labelAfterVal;
  if (labelBeforeChange) labelBeforeChange.textContent = labelBeforeVal;
  if (labelAfterChange) labelAfterChange.textContent = labelAfterVal;
  if (labelBeforeBuildup) labelBeforeBuildup.textContent = labelBeforeVal;
  if (labelAfterBuildup) labelAfterBuildup.textContent = labelAfterVal;
}

function updateDashboardUI(data, monthA, monthB) {
  // 1. Environmental Score
  const scoreEl = document.querySelector("#score");
  if (scoreEl) scoreEl.textContent = `${data.stats.environmental_score}/100`;
  const scoreMeter = document.querySelector("#score-meter");
  if (scoreMeter) scoreMeter.value = data.stats.environmental_score;

  // 2. Summary cards
  const greenDelta = document.querySelector("#green-delta");
  if (greenDelta) {
    greenDelta.textContent = `${data.stats.green_cover.change >= 0 ? "+" : ""}${data.stats.green_cover.change.toFixed(1)}%`;
    const greenSmall = greenDelta.nextElementSibling;
    if (greenSmall) {
      greenSmall.textContent = `Area Change -${data.stats.vegetation_loss_area_ha.toFixed(1)} ha`;
    }
  }

  const waterDelta = document.querySelector("#water-delta");
  if (waterDelta) {
    waterDelta.textContent = `${data.stats.water.change >= 0 ? "+" : ""}${data.stats.water.change.toFixed(1)}%`;
    const waterSmall = waterDelta.nextElementSibling;
    if (waterSmall) {
      const val = data.stats.water_change_area_ha;
      waterSmall.textContent = `Area Change ${val >= 0 ? "+" : ""}${val.toFixed(1)} ha`;
    }
  }

  const builtDelta = document.querySelector("#built-delta");
  if (builtDelta) {
    builtDelta.textContent = `${data.stats.built_up.change >= 0 ? "+" : ""}${data.stats.built_up.change.toFixed(1)}%`;
    const builtSmall = builtDelta.nextElementSibling;
    if (builtSmall) {
      builtSmall.textContent = `Area Change +${data.stats.built_up_expansion_area_ha.toFixed(1)} ha`;
    }
  }

  // 3. Alerts
  buildAlerts(data.alerts || []);

  // 4. Monthly Report
  const reportTitle = document.querySelector(".panel.report h2");
  if (reportTitle) {
    reportTitle.innerHTML = `Monthly Report <span>- ${getMonthLabel(monthB)}</span>`;
  }
  const reportList = document.querySelector("#report-list");
  if (reportList) {
    reportList.innerHTML = "";
    const lines = [
      `Green cover change: ${data.stats.green_cover.change >= 0 ? "+" : ""}${data.stats.green_cover.change.toFixed(1)}% (Area Loss: -${data.stats.vegetation_loss_area_ha.toFixed(1)} ha).`,
      `Water bodies footprint change: ${data.stats.water.change >= 0 ? "+" : ""}${data.stats.water.change.toFixed(1)}% (Net change: ${data.stats.water_change_area_ha >= 0 ? "+" : ""}${data.stats.water_change_area_ha.toFixed(1)} ha).`,
      `Built-up expansion area: ${data.stats.built_up_expansion_area_ha.toFixed(1)} ha (${data.stats.built_up.change >= 0 ? "+" : ""}${data.stats.built_up.change.toFixed(1)}%).`,
      `Average NDVI: ${data.stats.green_cover.avg_after.toFixed(3)}, Average NDWI: ${data.stats.water.avg_after.toFixed(3)}, Average NDBI: ${data.stats.built_up.avg_after.toFixed(3)}.`,
      `Environmental Score: ${data.stats.environmental_score}/100.`,
      `Recommendation: ${data.report.recommendation}`
    ];
    lines.forEach((line) => {
      const item = document.createElement("li");
      item.textContent = line;
      reportList.appendChild(item);
    });
  }

  // 5. Statistics / Comparison Statistics panel (.yearly)
  const yearlyPanel = document.querySelector(".panel.yearly");
  if (yearlyPanel) {
    const h2 = yearlyPanel.querySelector("h2");
    if (h2) {
      h2.innerHTML = `Comparison Statistics <span>(${getMonthLabel(monthA)} vs ${getMonthLabel(monthB)})</span>`;
    }
    const divs = yearlyPanel.querySelectorAll("div");
    if (divs[0]) {
      const gChange = data.stats.green_cover.change;
      const gLoss = data.stats.vegetation_loss_area_ha;
      divs[0].innerHTML = `<span>Green Cover</span><strong class="${gChange < 0 ? "danger-text" : "success-text"}">${gChange >= 0 ? "+" : ""}${gChange.toFixed(1)}%</strong><em>-${gLoss.toFixed(1)} ha (Loss)</em>`;
    }
    if (divs[1]) {
      const wChange = data.stats.water.change;
      const wLoss = data.stats.water_change_area_ha;
      divs[1].innerHTML = `<span>Water Bodies</span><strong class="${wChange < 0 ? "danger-text" : "success-text"}">${wChange >= 0 ? "+" : ""}${wChange.toFixed(1)}%</strong><em>${wLoss >= 0 ? "+" : ""}${wLoss.toFixed(1)} ha</em>`;
    }
    if (divs[2]) {
      const bChange = data.stats.built_up.change;
      const bGain = data.stats.built_up_expansion_area_ha;
      divs[2].innerHTML = `<span>Built-up Area</span><strong class="${bChange >= 0 ? "success-text" : "danger-text"}">${bChange >= 0 ? "+" : ""}${bChange.toFixed(1)}%</strong><em>+${bGain.toFixed(1)} ha (Gain)</em>`;
    }
  }

  // 6. Changes by Category (Monthly) bar chart
  const bars = document.querySelectorAll(".bar-chart .bar");
  if (bars && bars.length >= 4) {
    const vegLoss = data.stats.vegetation_loss_area_ha;
    const waterChg = data.stats.water_change_area_ha;
    const builtGain = data.stats.built_up_expansion_area_ha;

    const greenVal = Math.min(100, Math.max(10, Math.round(vegLoss * 2)));
    bars[0].style.setProperty("--v", greenVal.toString());
    const span0 = bars[0].querySelector("span");
    if (span0) span0.textContent = `-${vegLoss.toFixed(1)} ha`;

    const waterVal = Math.min(100, Math.max(10, Math.round(Math.abs(waterChg) * 4)));
    bars[1].style.setProperty("--v", waterVal.toString());
    const span1 = bars[1].querySelector("span");
    if (span1) span1.textContent = `${waterChg >= 0 ? "+" : ""}${waterChg.toFixed(1)} ha`;

    const builtVal = Math.min(100, Math.max(10, Math.round(builtGain * 5)));
    bars[2].style.setProperty("--v", builtVal.toString());
    const span2 = bars[2].querySelector("span");
    if (span2) span2.textContent = `+${builtGain.toFixed(1)} ha`;

    bars[3].style.setProperty("--v", "10");
    const span3 = bars[3].querySelector("span");
    if (span3) span3.textContent = "0.0 ha";
  }

  // 7. Donut Chart (NDVI Change)
  const donutPct = data.stats.donut_ndvi_change;
  const pHighInc = donutPct.high_inc ?? 0.0;
  const pModInc = donutPct.mod_inc ?? 0.0;
  const pNoChg = donutPct.no_chg ?? 0.0;
  const pModDec = donutPct.mod_dec ?? 0.0;
  const pHighDec = donutPct.high_dec ?? 0.0;

  const legendSpans = document.querySelectorAll(".donut-legend li span");
  if (legendSpans && legendSpans.length >= 5) {
    legendSpans[0].textContent = `${pHighInc.toFixed(1)}%`;
    legendSpans[1].textContent = `${pModInc.toFixed(1)}%`;
    legendSpans[2].textContent = `${pNoChg.toFixed(1)}%`;
    legendSpans[3].textContent = `${pModDec.toFixed(1)}%`;
    legendSpans[4].textContent = `${pHighDec.toFixed(1)}%`;
  }

  const donut = document.querySelector(".donut");
  if (donut) {
    const limit1 = pHighInc;
    const limit2 = limit1 + pModInc;
    const limit3 = limit2 + pNoChg;
    const limit4 = limit3 + pModDec;
    donut.style.background = `conic-gradient(
      #1a9850 0% ${limit1.toFixed(1)}%,
      #91cf60 ${limit1.toFixed(1)}% ${limit2.toFixed(1)}%,
      #fee08b ${limit2.toFixed(1)}% ${limit3.toFixed(1)}%,
      #fc8d59 ${limit2.toFixed(1)}% ${limit3.toFixed(1) + pModDec}%,
      #d73027 ${limit3.toFixed(1) + pModDec}% 100%
    )`;
  }

  // 8. Dynamic Popups and Polygons layer
  if (mapChange) {
    if (mapChange.geojsonLayer) {
      mapChange.removeLayer(mapChange.geojsonLayer);
    }
    mapChange.geojsonLayer = L.geoJSON(data.polygons, {
      style: function(feature) {
        const type = feature.properties.change_type;
        if (type === "Built-up Expansion") {
          return { color: "#FF3333", weight: 3, fillOpacity: 0.25 };
        } else if (type === "Vegetation Loss") {
          return { color: "#FF9900", weight: 3, fillOpacity: 0.25 };
        }
        return { color: "#0099FF", weight: 3, fillOpacity: 0.25 };
      },
      onEachFeature: function(feature, layer) {
        const props = feature.properties;
        const popupContent = `
          <div style="font-family: inherit; color: #fff; padding: 4px;">
            <strong style="font-size: 14px; color: #ff9800; display: block; margin-bottom: 6px;">${props.change_type} Detected</strong>
            <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 4px;">
              <tr><td style="color: #888; padding: 2px 0;">Location:</td><td style="text-align: right; font-weight: bold; color: #fff;">${props.location}</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Estimated Area:</td><td style="text-align: right; font-weight: bold; color: #ff9800;">${props.estimated_area_ha} ha</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Confidence:</td><td style="text-align: right; font-weight: bold; color: #4caf50;">${(props.confidence * 100).toFixed(0)}%</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Before State:</td><td style="text-align: right; color: #fff;">${props.before_val}</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">After State:</td><td style="text-align: right; color: #fff;">${props.after_val}</td></tr>
            </table>
          </div>
        `;
        layer.bindPopup(popupContent, { minWidth: 220 });
      }
    }).addTo(mapChange);
  }

  if (mapBuildup) {
    if (mapBuildup.geojsonLayer) {
      mapBuildup.removeLayer(mapBuildup.geojsonLayer);
    }
    const buildupPolygons = {
      type: "FeatureCollection",
      features: data.polygons.features.filter(f => f.properties.change_type === "Built-up Expansion")
    };
    mapBuildup.geojsonLayer = L.geoJSON(buildupPolygons, {
      style: { color: "#FF3333", weight: 3, fillOpacity: 0.3 },
      onEachFeature: function(feature, layer) {
        const props = feature.properties;
        const popupContent = `
          <div style="font-family: inherit; color: #fff; padding: 4px;">
            <strong style="font-size: 14px; color: #ff3333; display: block; margin-bottom: 6px;">Built-up Expansion Detected</strong>
            <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 4px;">
              <tr><td style="color: #888; padding: 2px 0;">Location:</td><td style="text-align: right; font-weight: bold; color: #fff;">${props.location}</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Estimated Area:</td><td style="text-align: right; font-weight: bold; color: #ff3333;">${props.estimated_area_ha} ha</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Confidence:</td><td style="text-align: right; font-weight: bold; color: #4caf50;">${(props.confidence * 100).toFixed(0)}%</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">Before State:</td><td style="text-align: right; color: #fff;">${props.before_val}</td></tr>
              <tr><td style="color: #888; padding: 2px 0;">After State:</td><td style="text-align: right; color: #fff;">${props.after_val}</td></tr>
            </table>
          </div>
        `;
        layer.bindPopup(popupContent, { minWidth: 200 });
      }
    }).addTo(mapBuildup);
  }

  // 9. Built-up expansion chips grid
  buildCompareChipGrid(data.polygons.features.filter(f => f.properties.change_type === "Built-up Expansion"));
}

function getPolygonCentroid(coordinates, type) {
  let coords = [];
  if (type === "Polygon") {
    coords = coordinates[0];
  } else if (type === "MultiPolygon") {
    coords = coordinates[0][0];
  } else {
    return CENTER;
  }
  let latSum = 0, lonSum = 0;
  coords.forEach(c => {
    lonSum += c[0];
    latSum += c[1];
  });
  return [latSum / coords.length, lonSum / coords.length];
}

function buildCompareChipGrid(buildupFeatures) {
  const grid = document.querySelector("#chips-grid");
  const countEl = document.querySelector("#chip-count");
  if (!grid) return;

  if (buildupFeatures.length === 0) {
    grid.innerHTML = `<p class="chips-empty">No built-up expansion clusters detected for this period.</p>`;
    if (countEl) countEl.textContent = "";
    return;
  }

  if (countEl) countEl.textContent = `${buildupFeatures.length} region${buildupFeatures.length !== 1 ? "s" : ""}`;
  grid.innerHTML = "";

  buildupFeatures.forEach((feat, i) => {
    const centroid = getPolygonCentroid(feat.geometry.coordinates, feat.geometry.type);
    const imgUrl = centroidToTileUrl(centroid[0], centroid[1], 18);
    const areaVal = feat.properties.estimated_area_ha;
    const areaLabel = `${areaVal.toFixed(2)} ha`;

    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = `
      <img src="${imgUrl}" alt="Built-up region ${i + 1}" loading="lazy" />
      <div class="chip-info">
        <span class="chip-label">Region ${i + 1}</span>
        <span class="chip-area">${areaLabel}</span>
      </div>
    `;
    chip.style.cursor = "pointer";
    chip.addEventListener("click", () => {
      if (mapBuildup) {
        mapBuildup.setView(centroid, 16);
      }
    });
    grid.appendChild(chip);
  });
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
    const boundary = await getJson("/api/boundary");

    // Set default select values if not set
    const selectBefore = document.querySelector("#select-before");
    const selectAfter = document.querySelector("#select-after");

    if (selectBefore && !selectBefore.value) selectBefore.value = "2024-05";
    if (selectAfter && !selectAfter.value) selectAfter.value = "2024-06";

    const beforeMonth = selectBefore ? selectBefore.value : "2024-05";
    const afterMonth = selectAfter ? selectAfter.value : "2024-06";

    // Call compare endpoint to get all data
    const data = await getJson(`/api/compare?monthA=${beforeMonth}&monthB=${afterMonth}`);

    // Initialize maps
    mapBefore = createMap("map-before", boundary, data.tiles.before, { opacity: 1 });
    mapAfter = createMap("map-after", boundary, data.tiles.after, { opacity: 1 });

    mapChange = createMap("map-change", boundary, data.tiles.ndvi_change, {
      opacity: 0.85,
      boundaryColor: "#243518",
    });
    addTileOverlay(mapChange, data.tiles.new_construction, { opacity: 0.9 });

    mapBuildup = createMap("map-buildup", boundary, data.tiles.new_construction, {
      opacity: 0.9,
      boundaryColor: "#FF4444",
      zoom: 15,
    });

    addBoundaryMask(mapBuildup, boundary);
    syncMaps();

    // Update labels and UI content
    updateLabels(beforeMonth, afterMonth);
    updateDashboardUI(data, beforeMonth, afterMonth);

    // Register period selection listener and change listeners
    function triggerUpdate() {
      const bVal = selectBefore ? selectBefore.value : "2024-05";
      const aVal = selectAfter ? selectAfter.value : "2024-06";
      if (bVal === aVal) {
        alert("Please select two different months for comparison.");
        return;
      }
      updateDashboard(bVal, aVal);
    }

    const btn = document.querySelector("#btn-generate");
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
    console.error("Boot error:", error);
    buildAlerts([]);
  }
}

boot();
