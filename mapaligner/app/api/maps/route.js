/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { headers } from "next/headers";

/** @typedef {{id: string, zip: string, name: string, size: number}} ProcessMetadata */

/** @typedef {"Not started" | "Active" | "Completed" | "Failed"} TaskStatus */

/** @typedef {{metadata: ProcessMetadata, upload: any, extract: any, hloc?: any[]}} DataSetStatus */

export async function GET() {
  const mapListUrl = `${process.env.MAPBUILDER_URL}/maps`;
  const headersList = headers();
  /** @type {DataSetStatus[]} */
  let mapList;
  try {
    const dataQuery = await fetch(mapListUrl, { headers: { Cookie: headersList.get("cookie") } });
    if (dataQuery.ok) {
      const data = await dataQuery.json();
      mapList = data.statuses;
    } else {
      const error = await dataQuery.text();
      console.error("Error downloading map list:", error);
      return new Response("Error downloading map list: " + error, { status: dataQuery.status });
    }
  } catch (error) {
    console.error("Error downloading map list:", error);
    return new Response("Error downloading map list", { status: 500 });
  }
  const completedMaps = mapList
    .filter((map) => map.hloc)
    .flatMap((map) => map.hloc.map((hlocMap) => ({ ...hlocMap, dataSetId: map.metadata.id })))
    .filter((hlocMap) => hlocMap.status === "Completed")
    .map((hlocMap) => ({
      id: hlocMap.mapId,
      name: hlocMap.mapId.substring(0, 8),
      size: 0,
      type: "hloc",
      dataSetId: hlocMap.dataSetId,
    }));
  return Response.json(completedMaps);
}
