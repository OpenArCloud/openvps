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

const environmentalConfigSchemaRaw = {
    uploadsDir: z.string(),
    scriptsDir: z.string(),
    hlocDir: z.string(),
    shell: z.string(),
};

const environmentalConfigSchema = z.object(environmentalConfigSchemaRaw);

export type EnvironmentalConfig = z.infer<typeof environmentalConfigSchema>;

dotenv.config();

const environmentalConfig: EnvironmentalConfig = parseEnv(process.env, environmentalConfigSchemaRaw);

console.log(` [index] config: ${JSON.stringify(environmentalConfig)}`);
const statuses = parseStatusFiles(environmentalConfig.uploadsDir);

startRestService(statuses, environmentalConfig);
