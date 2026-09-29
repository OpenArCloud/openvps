/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {startRestService} from "./service";
import {parseStatusFiles} from "./readstatus";
import dotenv from "dotenv";
import {parseEnv} from "znv";
import {z} from "zod";
import path from "node:path";

const environmentalConfigSchemaRaw = {
    uploadsDir: z.string(),
    scriptsDir: z.string(),
    hlocDir: z.string(),
    shell: z.string(),
    settingsDir: z.string().optional(),
};

const environmentalConfigSchema = z.object(environmentalConfigSchemaRaw);

export type EnvironmentalConfig = z.infer<typeof environmentalConfigSchema>;

dotenv.config();

const environmentalConfig: EnvironmentalConfig = parseEnv(process.env, environmentalConfigSchemaRaw);
environmentalConfig.settingsDir = environmentalConfig.settingsDir ?? path.join(environmentalConfig.uploadsDir, "settings");
environmentalConfigSchema.parse(environmentalConfig);

console.log(` [index] config: ${JSON.stringify(environmentalConfig)}`);
const statuses = parseStatusFiles(environmentalConfig.uploadsDir);

startRestService(statuses, environmentalConfig);
