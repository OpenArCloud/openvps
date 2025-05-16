/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  if (!req.auth) {
    if (req.nextUrl.pathname.startsWith("/api")) {
      return new Response("Unauthorized", { status: 401 });
    } else {
      const newUrl = new URL("/api/auth/signin", req.nextUrl.origin);
      return Response.redirect(newUrl);
    }
  }
  return NextResponse.next();
});






export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
