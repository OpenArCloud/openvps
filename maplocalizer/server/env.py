# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


# Code adapted from https://fastapi.tiangolo.com/advanced/settings/#read-settings-from-env
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    appName:str = "MapLocalizer"
    uploadsDir:str = ""
    debug:bool = False

    # this line loads the env_file and overwrites the values in this class (case-insensitive)
    model_config = SettingsConfigDict(env_file="server/.env")
