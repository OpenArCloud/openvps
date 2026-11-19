/**
 * Copyright 2026 Nokia
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
    case "hloc": {
      const dataSetId = searchParams.get("dataSetId");
      mapUrl = `${process.env.MAPBUILDER_URL}/maps/${dataSetId}/hloc/${id}/coverage`;
      break;
    }
    default:
      return new Response("No type specified", { status: 400 });
  }

  const headersList = headers();
  const response = await fetch(mapUrl, {
    headers: { Cookie: headersList.get("cookie") || "" },
  });
  const body = await response.text();
  return new Response(body, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") || "application/json" },
  });
}