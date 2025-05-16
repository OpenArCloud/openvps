/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import NextAuth from "next-auth";
import FusionAuth from "next-auth/providers/fusionauth";

const providers = [
  FusionAuth({
    // TODO these props are a workaround, remove them after this gets merged
    // https://github.com/nextauthjs/next-auth/pull/10868
    userinfo: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/userinfo",
    /*authorization: {
      url: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/authorize",
      params: {
        scope: "offline_access",
      },
    },*/
    token: {
      url: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/token",
      conform: async (response) => {
        if (response.status === 401) return response;
        console.log(response.headers);
        const newHeaders = Array.from(response.headers.entries())
          .filter(([key]) => key.toLowerCase() !== "www-authenticate")
          .reduce((headers, [key, value]) => (headers.append(key, value), headers), new Headers());

        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers: newHeaders,
        });
      },
    },
  }),
];

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
});
