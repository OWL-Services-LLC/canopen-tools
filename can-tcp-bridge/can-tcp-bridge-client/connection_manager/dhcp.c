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
#include "dhcp.h"

LOG_MODULE_DECLARE(connection_manager, CONFIG_CONNECTION_MANAGER_LOG_LEVEL);

/**
* @brief DHCP option code for NTP servers.
*/
#define DHCP_OPTION_NTP (42)

/**
* @brief Function pointer to the DHCP event callback handler.
*/
static dhcp_callback_t dhcp_events_cb;

/**
* @brief Network Management event callback structure
*/
static struct net_mgmt_event_callback dhcp_net_mgmt;

/**
* @brief DHCP option callback structure
*/
static struct net_dhcpv4_option_callback dhcp_options;

/**
* @brief Buffer to store the received NTP server IPv4 address.
*/
static uint8_t ntp_server[CONFIG_NTP_IPV4_BUFFER_SIZE];

/**
* @brief Callback handler for received DHCP options.
*
* This function is triggered when a DHCPv4 option is received.
*/
static void dhcp_option_handler_cb(struct net_dhcpv4_option_callback *cb,
                                   size_t length,
                                   enum net_dhcpv4_msg_type msg_type,
                                   struct net_if *iface)
{
    char buf[NET_IPV4_ADDR_LEN];
    LOG_INF("DHCP Option %d: %s", cb->option, net_addr_ntop(AF_INET, cb->data, buf, sizeof(buf)));
}

/**
* @brief Network management event callback for DHCP-related events.
*
* This function is invoked when a network management event occurs
*/
static void dhcp_mgmt_events_cb(struct net_mgmt_event_callback *cb,
                           uint64_t mgmt_event,
                           struct net_if *iface)
{
    enum dhcp_status dhcp_status = DHCP_FAILED;

    switch (mgmt_event)
    {
        case NET_EVENT_IPV4_ADDR_ADD:
            dhcp_status = DHCP_OK;
            for (unsigned int i = 0u; i < NET_IF_MAX_IPV4_ADDR; i++)
            {
                char buf[NET_IPV4_ADDR_LEN];

                if (iface->config.ip.ipv4->unicast[i].ipv4.addr_type != NET_ADDR_DHCP)
                {
                    continue;
                }

                LOG_INF("   Address[%d]: %s", net_if_get_by_iface(iface),
                    net_addr_ntop(
                        AF_INET,
                        &iface->config.ip.ipv4->unicast[i].ipv4.address.in_addr,
                        buf,
                        sizeof(buf)
                    )
                );

                LOG_INF("    Subnet[%d]: %s", net_if_get_by_iface(iface),
                    net_addr_ntop(
                        AF_INET,
                        &iface->config.ip.ipv4->unicast[i].netmask,
                        buf,
                        sizeof(buf)
                    )
                );

                LOG_INF("    Router[%d]: %s", net_if_get_by_iface(iface),
                    net_addr_ntop(
                        AF_INET,
                        &iface->config.ip.ipv4->gw,
                        buf,
                        sizeof(buf))
                );

                LOG_INF("Lease time[%d]: %u seconds", net_if_get_by_iface(iface), iface->config.dhcpv4.lease_time);
            }
            break;

        default:
            /* No other events need to be captured. */
    }

    if (dhcp_events_cb != NULL)
    {
    	dhcp_events_cb(dhcp_status);
    }
}

void dhcp_client_start(struct net_if *iface, dhcp_callback_t callback)
{
    dhcp_events_cb = callback;

    net_mgmt_init_event_callback(
        &dhcp_net_mgmt,
        dhcp_mgmt_events_cb,
        NET_EVENT_IPV4_ADDR_ADD
    );

    net_mgmt_add_event_callback(&dhcp_net_mgmt);

    net_dhcpv4_init_option_callback(
        &dhcp_options,
        dhcp_option_handler_cb,
        DHCP_OPTION_NTP,
        ntp_server,
        sizeof(ntp_server)
    );

    net_dhcpv4_add_option_callback(&dhcp_options);

    net_dhcpv4_start(iface);
}
