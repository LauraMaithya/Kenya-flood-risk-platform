"use strict";

const KENYA_BOUNDS = [
  [-4.9, 33.8],
  [5.3, 41.9],
];

const RISK_STYLE = {
  High: {
    colour: "#dc2626",
    intensity: 1.0,
    className: "high",
  },
  Medium: {
    colour: "#d97706",
    intensity: 0.72,
    className: "medium",
  },
  Low: {
    colour: "#15803d",
    intensity: 0.48,
    className: "low",
  },
};

const NO_DATA_STYLE = {
  colour: "#94a3b8",
  className: "unavailable",
};


function createPopupContent(county) {
  const container = document.createElement("div");
  container.className = "county-popup";

  const title = document.createElement("strong");
  title.textContent = `${county.county_name} County`;
  container.appendChild(title);

  const risk = document.createElement("p");

  if (county.data_status === "AVAILABLE") {
    risk.textContent = `Flood risk: ${county.risk_level}`;
    risk.className = `popup-risk risk-${county.risk_level.toLowerCase()}`;
  } else {
    risk.textContent = "Flood risk: No current data";
    risk.className = "popup-risk risk-unavailable";
  }

  container.appendChild(risk);

  if (county.observation_date) {
    const date = document.createElement("p");
    date.textContent = `Observation date: ${county.observation_date}`;
    container.appendChild(date);
  }

  return container;
}


function createMarkerIcon(county) {
  const style =
    RISK_STYLE[county.risk_level] || NO_DATA_STYLE;

  return L.divIcon({
    className: "risk-marker-wrapper",
    html: `
      <span
        class="risk-marker ${style.className}"
        aria-hidden="true"
      ></span>
    `,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -13],
  });
}


function createHeatLayer(points, riskLevel) {
  const colour = RISK_STYLE[riskLevel].colour;

  return L.heatLayer(points, {
    radius: 42,
    blur: 34,
    maxZoom: 9,
    minOpacity: 0.28,
    gradient: {
      0.2: colour,
      0.65: colour,
      1.0: colour,
    },
  });
}


async function loadMapData(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(
      "County flood-risk data could not be loaded."
    );
  }

  return response.json();
}


function setMapStatus(element, message, state) {
  element.textContent = message;
  element.dataset.state = state;
  element.hidden = false;
}

function normaliseCountyName(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\bcounty\b/g, "")
    .replace(/[^a-z0-9]/g, "");
}

function initialiseRiskMap() {
  const mapElement = document.querySelector(
    "#kenya-risk-map"
  );
  const statusElement = document.querySelector(
    "[data-map-status]"
  );
  const countySelector = document.querySelector(
  "[data-county-selector]"
  );
  const resetButton = document.querySelector(
    "[data-county-reset]"
  );
  const riskCard = document.querySelector(
    "[data-county-risk-card]"
  );
  const countyNameElement = document.querySelector(
    "[data-county-name]"
  );
  const riskBadgeElement = document.querySelector(
    "[data-county-risk-badge]"
  );
  const observationDateElement = document.querySelector(
    "[data-county-observation-date]"
  );
  const riskLevelElement = document.querySelector(
    "[data-county-risk-level]"
  );

  if (
  !mapElement ||
  !statusElement ||
  !countySelector ||
  !resetButton ||
  !riskCard ||
  !countyNameElement ||
  !riskBadgeElement ||
  !observationDateElement ||
  !riskLevelElement
  ) {
      return;
  }

  if (typeof L === "undefined") {
    setMapStatus(
      statusElement,
      "The map library could not be loaded.",
      "error"
    );
    return;
  }

  const map = L.map(mapElement, {
    zoomControl: false,
    minZoom: 5,
    maxZoom: 12,
    maxBounds: KENYA_BOUNDS,
    maxBoundsViscosity: 0.75,
  });

  map.fitBounds(KENYA_BOUNDS);

  L.control.zoom({
    position: "bottomleft",
  }).addTo(map);

  map.attributionControl.addAttribution(
  '<a href="https://www.geoboundaries.org/">' +
    "geoBoundaries</a> (CC BY 4.0)"
);


  Promise.all([
  loadMapData(mapElement.dataset.mapUrl),
  loadBoundaryData(mapElement.dataset.boundaryUrl),
])
  .then(([payload, boundaryData]) => {
    const counties = Array.isArray(payload.results)
  ? payload.results
  : [];

const predictionsByCounty = new Map(
  counties.map((county) => [
    normaliseCountyName(county.county_name),
    county,
  ])
);

const boundaryStyle = {
  color: "#63859a",
  weight: 1.25,
  opacity: 0.9,
  fillColor: "#dfeeed",
  fillOpacity: 0.72,
};


function getBoundaryStyle(countyKey, selected = false) {
  const county = predictionsByCounty.get(countyKey);

  const riskStyle =
    county?.data_status === "AVAILABLE"
      ? RISK_STYLE[county.risk_level]
      : null;

  return {
    ...boundaryStyle,
    fillColor: riskStyle
      ? riskStyle.colour
      : NO_DATA_STYLE.colour,
    fillOpacity: riskStyle ? 0.78 : 0.32,
    ...(selected
      ? {
          color: "#0f4c5c",
          weight: 3,
          opacity: 1,
          fillOpacity: riskStyle ? 0.92 : 0.55,
        }
      : {}),
  };
}

const boundaryLayersByCounty = new Map();
let selectedCountyKey = "";

const boundaryFeatures = Array.isArray(boundaryData.features)
  ? [...boundaryData.features]
  : [];

boundaryFeatures.sort((first, second) => {
  const firstName = first.properties?.shapeName || "";
  const secondName = second.properties?.shapeName || "";

  return firstName.localeCompare(secondName);
});

countySelector.replaceChildren();

const allCountiesOption = document.createElement("option");
allCountiesOption.value = "";
allCountiesOption.textContent = "All counties";
countySelector.appendChild(allCountiesOption);

boundaryFeatures.forEach((feature) => {
  const countyName = feature.properties?.shapeName;

  if (!countyName) {
    return;
  }

  const option = document.createElement("option");
  option.value = normaliseCountyName(countyName);
  option.textContent = countyName;
  countySelector.appendChild(option);
});

const showCountyRisk = (countyName, countyKey) => {
  const county = predictionsByCounty.get(countyKey);

  countyNameElement.textContent = `${countyName} County`;
  riskCard.hidden = false;

  if (
    !county ||
    county.data_status !== "AVAILABLE" ||
    !county.risk_level
  ) {
    riskBadgeElement.textContent = "No data";
    riskBadgeElement.dataset.risk = "";
    observationDateElement.textContent = "Not available";
    riskLevelElement.textContent = "No current prediction";
    return;
  }

  riskBadgeElement.textContent = county.risk_level;
  riskBadgeElement.dataset.risk = county.risk_level;
  observationDateElement.textContent =
    county.observation_date || "Not available";
  riskLevelElement.textContent = county.risk_level;
};

const restoreMapStatus = () => {
  if (!counties.length) {
    setMapStatus(
      statusElement,
      "No county prediction data is currently available.",
      "empty"
    );
    return;
  }

  statusElement.hidden = true;
};

const selectCounty = (countyKey) => {
  boundaryLayersByCounty.forEach((entry, key) => {
    entry.layer.setStyle(
      getBoundaryStyle(
        key,
        key === countyKey
      )
    );
  });

  const selectedEntry =
    boundaryLayersByCounty.get(countyKey);

  if (!selectedEntry) {
    return;
  }

  selectedCountyKey = countyKey;
  countySelector.value = countyKey;
  resetButton.disabled = false;

  map.fitBounds(selectedEntry.layer.getBounds(), {
  padding: [35, 35],
  });

  if (map.getZoom() > 9) {
    map.setZoom(9);
  }

  showCountyRisk(
    selectedEntry.countyName,
    countyKey
  );

  setMapStatus(
    statusElement,
    `${selectedEntry.countyName} County selected`,
    "selected"
  );
};

const boundaryLayer = L.geoJSON(
  boundaryFeatures,
  {
    style(feature) {
      const countyName =
        feature.properties?.shapeName || "";

      return getBoundaryStyle(
        normaliseCountyName(countyName)
      );
    },

    onEachFeature(feature, layer) {
      const countyName =
        feature.properties?.shapeName;

      if (!countyName) {
        return;
      }

      const countyKey =
        normaliseCountyName(countyName);

      boundaryLayersByCounty.set(countyKey, {
        countyName,
        layer,
      });

      layer.on("mouseover", function () {
        this.setStyle({
          color: "#184e5a",
          weight: 2.5,
          fillOpacity: 0.9,
        });

        this.bringToFront();
        statusElement.textContent =
          `${countyName} County`;
        statusElement.hidden = false;
      });

      layer.on("mouseout", function () {
        this.setStyle(
          getBoundaryStyle(
            countyKey,
            countyKey === selectedCountyKey
          )
        );

        if (selectedCountyKey) {
          const selectedEntry =
            boundaryLayersByCounty.get(
              selectedCountyKey
            );

          statusElement.textContent =
            `${selectedEntry.countyName} County selected`;
          statusElement.hidden = false;
        } else {
          restoreMapStatus();
        }
      });

      layer.on("click", function () {
        selectCounty(countyKey);
      });
    },
  }
).addTo(map);

const boundaryBounds = boundaryLayer.getBounds();

if (boundaryBounds.isValid()) {
  map.fitBounds(boundaryBounds, {
    padding: [18, 18],
  });
}

countySelector.disabled = false;
resetButton.disabled = true;

countySelector.addEventListener("change", () => {
  const countyKey = countySelector.value;

  if (!countyKey) {
    selectedCountyKey = "";

    boundaryLayersByCounty.forEach(
      ({ layer }, countyKey) => {
        layer.setStyle(
          getBoundaryStyle(countyKey)
        );
      }
    );

    if (boundaryBounds.isValid()) {
      map.fitBounds(boundaryBounds, {
        padding: [18, 18],
      });
    }

    riskCard.hidden = true;
    resetButton.disabled = true;
    restoreMapStatus();
    return;
  }

  selectCounty(countyKey);
});

resetButton.addEventListener("click", () => {
  countySelector.value = "";
  countySelector.dispatchEvent(
    new Event("change")
  );
});

      if (!counties.length) {
        setMapStatus(
          statusElement,
          "No county prediction data is currently available.",
          "empty"
        );
        return;
      }

      const heatPoints = {
        Low: [],
        Medium: [],
        High: [],
      };

      let plottedCount = 0;
      let missingCoordinateCount = 0;

      counties.forEach((county) => {
        if (
          !county.has_coordinates ||
          typeof county.latitude !== "number" ||
          typeof county.longitude !== "number"
        ) {
          missingCoordinateCount += 1;
          return;
        }

        plottedCount += 1;

        if (
          county.data_status === "AVAILABLE" &&
          RISK_STYLE[county.risk_level]
        ) {
          heatPoints[county.risk_level].push([
            county.latitude,
            county.longitude,
            RISK_STYLE[county.risk_level].intensity,
          ]);
        }

        const marker = L.marker(
          [county.latitude, county.longitude],
          {
            icon: createMarkerIcon(county),
            keyboard: true,
            title: `${county.county_name} County`,
            alt: `${county.county_name} County flood-risk marker`,
          }
        );

        marker.bindPopup(createPopupContent(county));
        marker.addTo(map);
      });

      ["Low", "Medium", "High"].forEach(
        (riskLevel) => {
          if (heatPoints[riskLevel].length) {
            createHeatLayer(
              heatPoints[riskLevel],
              riskLevel
            ).addTo(map);
          }
        }
      );

      if (!plottedCount) {
        setMapStatus(
          statusElement,
          "Stored counties do not currently have map coordinates.",
          "empty"
        );
        return;
      }

      if (missingCoordinateCount) {
        setMapStatus(
          statusElement,
          `${plottedCount} counties displayed. ` +
            `${missingCoordinateCount} counties lack coordinates.`,
          "warning"
        );
        return;
      }

      statusElement.hidden = true;
    })
    .catch((error) => {
      setMapStatus(
        statusElement,
        error.message,
        "error"
      );
    });

  window.addEventListener("resize", () => {
    map.invalidateSize();
  });
}

async function loadBoundaryData(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Accept: "application/geo+json, application/json",
    },
  });

  if (!response.ok) {
    throw new Error(
      "Kenya county boundaries could not be loaded."
    );
  }

  return response.json();
}

document.addEventListener(
  "DOMContentLoaded",
  initialiseRiskMap
);