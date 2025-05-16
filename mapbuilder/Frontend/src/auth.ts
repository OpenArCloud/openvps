/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { API_URLS, AUTH_CLIENT_ID, AUTH_CLIENT_SECRET } from "./config";

let tokenRefreshTimerInterval: NodeJS.Timeout | undefined;

enum SESSION_KEYS {
    USERNAME = "username",
    IS_AUTHENTICATED = "isAuthenticated",
    ACCESS_TOKEN = "accessToken",
    REFRESH_TOKEN = "refreshToken",
    TOKEN_EXPIRATION = "tokenExpiration",
}

export type AuthenticationResult = {
    success: boolean;
    message: string;
};

export function isAuthenticated(): boolean {
    const expiration: number = getNumberValue(SESSION_KEYS.TOKEN_EXPIRATION);
    if (expiration < Date.now()) {
        return false;
    }
    return getBooleanValue(SESSION_KEYS.IS_AUTHENTICATED);
}

export function getUserName(): string {
    return getStringValue(SESSION_KEYS.USERNAME);
}

export function getAuthenticationToken(): string {
    return getStringValue(SESSION_KEYS.ACCESS_TOKEN);
}

export function authenticate(username: string, password: string): Promise<AuthenticationResult> {
    setStringValue(SESSION_KEYS.USERNAME, username);
    if (tokenRefreshTimerInterval) {
        clearInterval(tokenRefreshTimerInterval);
        tokenRefreshTimerInterval = undefined;
    }

    // hard coded user for simple no authentication server testing
    // return new Promise((resolve, reject) => {
    // 	setTimeout(() => {
    // 		if (btoa(username) === 'anVwaXRlcg==' && btoa(password) === 'ZXVyb3BhNDk1') {
    // 			setBooleanValue(SESSION_KEYS.IS_AUTHENTICATED, true);
    // 			resolve({ success: true, message: "Successfully authenticated" });
    // 		}
    // 		reject({ success: false, message: "Invalid username or password" });
    // 	}, 1000);
    // });

    return new Promise((resolve, reject) => {
        const formData = new URLSearchParams();
        formData.append("username", username);
        formData.append("password", password);
        formData.append("grant_type", "password");
        formData.append("client_id", AUTH_CLIENT_ID);
        formData.append("client_secret", AUTH_CLIENT_SECRET);

        fetch(API_URLS.LOGIN, {
            method: "POST",
            body: formData,
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
            },
        })
            .then(async (response) => {
                const result = await response.json();
                if (response.status === 200) {
                    const accessToken: string = result.access_token;
                    const expiresIn: number = result.expires_in;
                    const refreshToken: string = result.refresh_token;
                    setStringValue(SESSION_KEYS.ACCESS_TOKEN, accessToken);
                    setStringValue(SESSION_KEYS.REFRESH_TOKEN, refreshToken);
                    setBooleanValue(SESSION_KEYS.IS_AUTHENTICATED, true);
                    setNumberValue(SESSION_KEYS.TOKEN_EXPIRATION, Date.now() + (expiresIn - 10) * 1000);

                    tokenRefreshTimerInterval = setInterval(
                        refreshTokenFromServer,
                        Math.max(290, expiresIn - 10) * 1000,
                    );
                    resolve({ success: true, message: "Successfully authenticated" });
                    return;
                }
                const errorMsg = result.error_description || "Authentication failed";
                resolve({ success: false, message: errorMsg });
            })
            .catch((error) => {
                reject({ success: false, message: error });
            });
    });
}

export function logout(): void {
    if (tokenRefreshTimerInterval) {
        clearInterval(tokenRefreshTimerInterval);
        tokenRefreshTimerInterval = undefined;
    }

    const formData = new URLSearchParams();
    formData.append("client_id", AUTH_CLIENT_ID);
    formData.append("client_secret", AUTH_CLIENT_SECRET);
    formData.append("refresh_token", getStringValue(SESSION_KEYS.REFRESH_TOKEN));

    fetch(API_URLS.LOGOUT, {
        method: "POST",
        body: formData,
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
        },
    }).then();

    setBooleanValue(SESSION_KEYS.IS_AUTHENTICATED, false);
    setStringValue(SESSION_KEYS.USERNAME, "");
    setStringValue(SESSION_KEYS.ACCESS_TOKEN, "");
    setStringValue(SESSION_KEYS.REFRESH_TOKEN, "");
}

function refreshTokenFromServer(): void {
    const formData = new URLSearchParams();
    formData.append("client_id", AUTH_CLIENT_ID);
    formData.append("client_secret", AUTH_CLIENT_SECRET);
    formData.append("grant_type", "refresh_token");
    formData.append("refresh_token", getStringValue(SESSION_KEYS.REFRESH_TOKEN));

    fetch(API_URLS.LOGIN, {
        method: "POST",
        body: formData,
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
        },
    }).then(async (response) => {
        const result = await response.json();
        if (response.status === 200) {
            const accessToken: string = result.access_token;
            const expiresIn: number = result.expires_in;
            const refreshToken: string = result.refresh_token;
            setStringValue(SESSION_KEYS.ACCESS_TOKEN, accessToken);
            setStringValue(SESSION_KEYS.REFRESH_TOKEN, refreshToken);
            setNumberValue(SESSION_KEYS.TOKEN_EXPIRATION, Date.now() + (expiresIn - 10) * 1000);
        }
    });
}

function getBooleanValue(key: SESSION_KEYS): boolean {
    return sessionStorage.getItem(key) === "true";
}

function setBooleanValue(key: SESSION_KEYS, value: boolean): void {
    sessionStorage.setItem(key, value ? "true" : "false");
}

function getStringValue(key: SESSION_KEYS): string {
    return sessionStorage.getItem(key) || "";
}

function setStringValue(key: SESSION_KEYS, value: string): void {
    sessionStorage.setItem(key, value);
}

function getNumberValue(key: SESSION_KEYS): number {
    return parseInt(sessionStorage.getItem(key) || "0");
}

function setNumberValue(key: SESSION_KEYS, value: number): void {
    sessionStorage.setItem(key, value.toString());
}
