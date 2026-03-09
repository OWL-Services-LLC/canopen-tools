/*
 * Copyright (C) 2025 - OWL Services LLC
 *
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License (version 2) as published by the
 * FSF - Free Software Foundation
 *
 */

#include <sys/types.h>
#include <unistd.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/net_context.h>
#include <zephyr/net/net_core.h>
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_ip.h>
#include <zephyr/net/net_mgmt.h>
#include <zephyr/net/wifi_mgmt.h>

#include "connection_manager.h"
#include "wifi.h"
#include "dhcp.h"

LOG_MODULE_REGISTER(connection_manager, CONFIG_CONNECTION_MANAGER_LOG_LEVEL);

/**
* @brief Semaphore that signals a successful Wi-Fi connection.
*
* This semaphore is released by the Wi-Fi event callback function when a
* Wi-Fi connection result is received
*/
K_SEM_DEFINE(wifi_connected_sem, 0, 1);

/**
 * @brief Semaphore that signals DHCP address assignment.
 *
 * This semaphore is released by the DHCP event callback function when an IPv4
 * address is successfully assigned
 */
K_SEM_DEFINE(dhcp_completed_sem, 0, 1);

/** @brief Indicates whether the wifi connection was successful or not. */
static enum cm_wifi_conn_status wifi_status;

/** @brief Indicates whether the DHCP was successful or not. */
static enum dhcp_status dhcp_status;

/**
* @brief Callback for handling Wi-Fi related network events.
*
* @param status The status indicating whether the connection was successful or not.
*/
static void wifi_events_cb(const enum cm_wifi_conn_status status)
{
    wifi_status = status;
    k_sem_give(&wifi_connected_sem);
}

/**
* @brief Callback for handling DHCP-related network events.
*
* @param status The status indicating whether the DHCP was successful or not.
*/
static void dhcp_events_cb(const enum dhcp_status status)
{
    dhcp_status = status;
    k_sem_give(&dhcp_completed_sem);
}

int connection_manager_init(struct connection_manager_init_ctx *ctx)
{
    int rc = 0;
    struct net_if *iface = net_if_get_default();

    if (iface != NULL)
    {
        cm_wifi_connect(iface, wifi_events_cb, ctx->ssid, ctx->password);
        LOG_INF("Waiting for connection to be established...");
        k_sem_take(&wifi_connected_sem, K_FOREVER);
        if (wifi_status == WIFI_CONNECTED)
        {
            LOG_INF("DHCP started on %s: index=%d", net_if_get_device(iface)->name, net_if_get_by_iface(iface));
            dhcp_client_start(iface, dhcp_events_cb);
            LOG_INF("Waiting for DHCP process to be completed...");
            k_sem_take(&dhcp_completed_sem, K_FOREVER);
            if (dhcp_status != DHCP_OK)
            {
                rc = -ECONNREFUSED;
            }
        }
        else /* wifi connection failed */
        {
            LOG_ERR("Wifi connection failed.");
            rc = -ECONNREFUSED;
        }
    }
    else
    {
        LOG_ERR("Default interface not found");
        rc = -ENXIO;
    }

    return rc;
};
