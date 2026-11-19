/**
 * Copyright 2026 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

/**
 * Build MapLibre GeoJSON from MapBuilder ``coverage.json`` geodetic block.
 *
 * @param {Record<string, unknown> | null | undefined} coverage
 * @returns {{ type: 'FeatureCollection', features: object[] } | null}
 */
export function coverageArtifactToGeoJson(coverage) {
  if (!coverage || typeof coverage !== "object") {
    return null;
  }
  const block = coverage.geodetic_coverage;
  if (!block || typeof block !== "object") {
    return null;
  }

  /** @type {object[]} */
  const features = [];

  const footprint = /** @type {Record<string, unknown>} */ (block).geo_footprint;
  if (footprint && typeof footprint === "object" && footprint.type && footprint.coordinates) {
    features.push({
      type: "Feature",
      properties: { kind: "footprint" },
      geometry: footprint,
    });
  }

  const aabb = /** @type {Record<string, unknown>} */ (block).geo_aabb;
  if (aabb && typeof aabb === "object") {
    const lonMin = Number(aabb.lon_min);
    const latMin = Number(aabb.lat_min);
    const lonMax = Number(aabb.lon_max);
    const latMax = Number(aabb.lat_max);
    if ([lonMin, latMin, lonMax, latMax].every((n) => Number.isFinite(n))) {
      features.push({
        type: "Feature",
        properties: { kind: "aabb" },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [lonMin, latMin],
              [lonMax, latMin],
              [lonMax, latMax],
              [lonMin, latMax],
              [lonMin, latMin],
            ],
          ],
        },
      });
    }
  }

  if (features.length === 0) {
    return null;
  }

  return { type: "FeatureCollection", features };
}