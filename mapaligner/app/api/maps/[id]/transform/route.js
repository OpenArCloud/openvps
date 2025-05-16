/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { headers } from "next/headers";

export async function GET(request, { params }) {
  const id = (await params).id;
  const searchParams = request.nextUrl.searchParams;
  const type = searchParams.get("type");
  let mapUrl;
  switch (type) {
    case "hloc":
      const dataSetId = searchParams.get("dataSetId");
      mapUrl = `${process.env.MAPBUILDER_URL}/maps/${dataSetId}/hloc/${id}/transform`;
      break;
    default:
      return new Response("No type specified", { status: 400 });
  }

  const headersList = headers();
  const response = await fetch(mapUrl, { headers: { Cookie: headersList.get("cookie") } });
  const map = await response.blob();
  return new Response(map, { status: response.status });
}

/**
 *
 * @param {Request} request
 * @param {*} param1
 */
export async function POST(request, { params }) {
  const id = (await params).id;
  const searchParams = request.nextUrl.searchParams;
  const type = searchParams.get("type");
  let mapUrl;
  switch (type) {
    case "hloc":
      const dataSetId = searchParams.get("dataSetId");
      mapUrl = `${process.env.MAPBUILDER_URL}/maps/${dataSetId}/hloc/${id}/transform`;
      break;
    default:
      return new Response("No type specified", { status: 400 });
  }
  console.log(mapUrl);
  const headersList = headers();
  const response = await fetch(mapUrl, {
    method: "POST",
    headers: { Cookie: headersList.get("cookie"), "Content-Type": headersList.get("content-type") },
    body: request.body,
    duplex: "half",
  });
  const map = await response.blob();
  return new Response(map, { status: response.status });
}
