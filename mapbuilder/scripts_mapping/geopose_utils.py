# Open AR Cloud GeoPoseProtocol - Python implementation
# Created by Gabor Soros, 2023
#
# Copyright 2023 Nokia
# Licensed under the MIT License
# SPDX-License-Identifier: MIT

# The mathmatical formulas can be found in https://en.wikipedia.org/wiki/Geographic_coordinate_conversion

import math

a = 6378137.0000 # Earth radius in meters
b = 6356752.3142 # Earth semiminor in meters
f = (a - b) / a
e_sq = f * (2.0 - f) # first eccentricity squared = (a2 - b2) / a2
pi = 3.14159265359

# lat, lon in degrees, h in meters
def geodetic_to_ecef(lat, lon, h):
    lamb = math.radians(lat)
    phi = math.radians(lon)

    sin_lambda = math.sin(lamb)
    cos_lambda = math.cos(lamb)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)

    nu = a / math.sqrt(1 - e_sq * sin_lambda * sin_lambda)

    x = (h + nu) * cos_lambda * cos_phi
    y = (h + nu) * cos_lambda * sin_phi
    z = (h + (1 - e_sq) * nu) * sin_lambda

    return x, y, z


def ecef_to_enu(x, y, z, lat0, lon0, h0):
    lamb = math.radians(lat0)
    phi = math.radians(lon0)

    sin_lambda = math.sin(lamb)
    cos_lambda = math.cos(lamb)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)

    nu = a / math.sqrt(1 - e_sq * sin_lambda * sin_lambda)

    x0 = (h0 + nu) * cos_lambda * cos_phi
    y0 = (h0 + nu) * cos_lambda * sin_phi
    z0 = (h0 + (1 - e_sq) * nu) * sin_lambda

    xd = x - x0
    yd = y - y0
    zd = z - z0

    t = -cos_phi * xd - sin_phi * yd

    xEast = -sin_phi * xd + cos_phi * yd
    yNorth = t * sin_lambda + cos_lambda * zd
    zUp = cos_lambda * cos_phi * xd + cos_lambda * sin_phi * yd + sin_lambda * zd

    return xEast, yNorth, zUp


def enu_to_ecef(xEast, yNorth, zUp, lat0, lon0, h0):
    lamb = math.radians(lat0)
    phi = math.radians(lon0)

    sin_lambda = math.sin(lamb)
    cos_lambda = math.cos(lamb)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)

    nu = a / math.sqrt(1 - e_sq * sin_lambda * sin_lambda)

    x0 = (h0 + nu) * cos_lambda * cos_phi
    y0 = (h0 + nu) * cos_lambda * sin_phi
    z0 = (h0 + (1 - e_sq) * nu) * sin_lambda

    t = cos_lambda * zUp - sin_lambda * yNorth

    zd = sin_lambda * zUp + cos_lambda * yNorth
    xd = cos_phi * t - sin_phi * xEast
    yd = sin_phi * t + cos_phi * xEast

    x = xd + x0
    y = yd + y0
    z = zd + z0

    return x, y, z

# Convert from ECEF cartesian coordinates to latitude, longitude and height (WGS84)
def ecef_to_geodetic(x, y, z):
    # formula from http://www.movable-type.co.uk/scripts/latlong-os-gridref.html#cartesian-to-geodetic
    e1_sq = 2 * f - f * f; # 1st eccentricity squared = (a^2-b^2)/a^2
    e2_sq = e1_sq / (1 - e1_sq); # 2nd eccentricity squared = (a^2-b^2)/b^2
    p = math.sqrt(x*x + y*y); # distance from minor axis
    R = math.sqrt(p*p + z*z); # polar radius

    # parametric latitude (Bowring eqn.17)
    tanBeta = (b*z)/(a*p) * (1 + e2_sq * b / R)
    sinBeta = tanBeta / math.sqrt(1 + tanBeta * tanBeta)
    cosBeta = sinBeta / tanBeta

    # geodetic latitude (Bowring eqn.18)
    latRad = 0
    if not math.isnan(cosBeta):
        latRad = math.atan2(z + e2_sq * b* sinBeta * sinBeta * sinBeta, p - e1_sq * a * cosBeta * cosBeta * cosBeta)

    # longitude
    lonRad = math.atan2(y, x)

    # height above ellipsoid (Bowring eqn.7)
    sinLat = math.sin(latRad)
    cosLat = math.cos(latRad)
    nu = a / math.sqrt(1 - e1_sq * sinLat * sinLat) # length of the normal terminated by the minor axis
    height = p * cosLat + z * sinLat - (a * a / nu)

    lat = latRad / (pi / 180)
    lon = lonRad / (pi / 180)
    h = height

    return lat, lon, h


def geodetic_to_enu(lat, lon, h, lat_ref, lon_ref, h_ref):
    x, y, z = geodetic_to_ecef(lat, lon, h)
    return ecef_to_enu(x, y, z, lat_ref, lon_ref, h_ref)


def enu_to_geodetic(xEast, yNorth, zUp, lat_ref, lon_ref, h_ref):
    x, y, z = enu_to_ecef(xEast, yNorth, zUp, lat_ref, lon_ref, h_ref)
    return ecef_to_geodetic(x, y, z)
