/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {ExpressAuthConfig} from "@auth/express";
import FusionAuth from "@auth/express/providers/fusionauth";
import dotenv from "dotenv";

dotenv.config();

export const authConfig: ExpressAuthConfig = {
    providers: [
        FusionAuth({
            // TODO: these props are a workaround, remove them after this gets merged
            // https://github.com/nextauthjs/next-auth/pull/10868
            userinfo: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/userinfo",
            authorization: {
                //url: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/authorize",
                params: {
                    scope: "offline_access openid profile email",
                },
            },
            token: {
                url: process.env.AUTH_FUSIONAUTH_ISSUER + "/oauth2/token",
                conform: async (response: any) => {
                    if (response.status === 401) return response;
                    const newHeaders: Headers = (Array.from(response.headers.entries()) as any[])
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
    ],
    callbacks: {
        jwt({token, user}) {
            //console.log(user);
            if (user) {
                token.name = user.name;
            }
            return token;
        },
        session({session, token}: any) {
            //console.log(token);
            session.user.name = token.name;
            return session;
        },
    },
};
