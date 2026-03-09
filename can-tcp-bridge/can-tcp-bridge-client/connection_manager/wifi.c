/*
 * Copyright (C) 2025 - OWL Services LLC
 *
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License (version 2) as published by the
 * FSF - Free Software Foundation
 *
 */

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

LOG_MODULE_DECLARE(connection_manager, CONFIG_CONNECTION_MANAGER_LOG_LEVEL);

static wifi_callback_t wifi_event_cb;

/** Network Management event callback structure */
static struct net_mgmt_event_callback wifi_net_mgmt;

/**
 * @brief Handles wifi events.
 */
static void wifi_mgmt_event_handler_cb(struct net_mgmt_event_callback *cb,
                                       uint64_t mgmt_event,
                                       struct net_if *iface)
{
    enum cm_wifi_conn_status wifi_status = WIFI_NOT_CONNECTED;

    switch (mgmt_event)
    {
        case NET_EVENT_WIFI_CONNECT_RESULT:
            const struct wifi_status *wifi_sts = (const struct wifi_status *)cb->info;
            if (wifi_sts->conn_status == WIFI_STATUS_CONN_SUCCESS)
            {
                wifi_status = WIFI_CONNECTED;
            }
            break;
        default:
            /* No other events need to be captured. */
    }

    if (wifi_event_cb != NULL)
    {
    	wifi_event_cb(wifi_status);
    }
}

void cm_wifi_connect(struct net_if *iface, wifi_callback_t callback, const char *ssid, const char *password)
{
    int nr_tries = CONFIG_WIFI_NUM_TRIES;
    int status = 0;

    wifi_event_cb = callback;

    net_mgmt_init_event_callback(
        &wifi_net_mgmt,
        wifi_mgmt_event_handler_cb,
        NET_EVENT_WIFI_CONNECT_RESULT
    );

    net_mgmt_add_event_callback(&wifi_net_mgmt);

    static struct wifi_connect_req_params cnx_params;

    cnx_params.ssid = ssid;
    cnx_params.ssid_length = strlen(ssid);
    cnx_params.psk = password;
    cnx_params.psk_length = strlen(password);
    cnx_params.channel = WIFI_CHANNEL_ANY;
    cnx_params.security = WIFI_SECURITY_TYPE_PSK;

    LOG_INF("WIFI try connecting to %s...", ssid);

    /* Let's wait few seconds to allow wifi device be on-line */
    do
    {
        k_msleep(CONFIG_WIFI_CONN_DELAY);
        status = net_mgmt(NET_REQUEST_WIFI_CONNECT, iface, &cnx_params, sizeof(struct wifi_connect_req_params));
    }
    while ((status != 0) && (nr_tries-- > 0));

    if (status == 0)
    {
        LOG_INF("Connection successful");
    }
    else
    {
        LOG_ERR("Connection request failed: error %d", status);
    }
}
