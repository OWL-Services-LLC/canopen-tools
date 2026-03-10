/*
* Copyright (C) 2025 - OWL Services LLC
*
* This program is free software; you can redistribute it and/or modify it under
* the terms of the GNU General Public License (version 2) as published by the
* FSF - Free Software Foundation
*
*/

#ifndef _WIFI_
#define _WIFI_

#include <zephyr/kernel.h>
#include <zephyr/net/net_if.h>

/**
 * @brief Wifi connection status.
 */
enum cm_wifi_conn_status {
    WIFI_CONNECTED,
    WIFI_NOT_CONNECTED
};

/**
* @brief Callback type for handling Wi-Fi-related events.
*
* This type is used to define callbacks that are
* triggered when Wi-Fi events occur.
*
* @param status The Wi-Fi connection status.
*/
typedef void (*wifi_callback_t) (const enum cm_wifi_conn_status status);

/**
* @brief Performs the wifi connection.
*
* @param iface     The network interface used for the connection.
* @param callback  Callback function to handle Wi-Fi connection events.
* @param ssid      SSID of the Wi-Fi network to connect to.
* @param password  Password for the Wi-Fi network.
*/
void cm_wifi_connect(struct net_if *iface, wifi_callback_t callback, const char *ssid, const char *password);

#endif /*_WIFI_*/
