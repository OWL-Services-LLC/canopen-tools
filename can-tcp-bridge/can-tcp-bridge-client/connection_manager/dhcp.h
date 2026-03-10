/*
 * Copyright (C) 2025 - OWL Services LLC
 *
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License (version 2) as published by the
 * FSF - Free Software Foundation
 *
 */

#ifndef _DHCP_
#define _DHCP_

#include <zephyr/kernel.h>
#include <zephyr/net/net_if.h>

/**
 * @brief DHCP status.
 */
enum dhcp_status {
    DHCP_OK,
    DHCP_FAILED
};

/**
* @brief Callback type for handling DHCP-related events.
*
* This type is used for callbacks
* that are triggered when specific DHCP related events occur.
*/
typedef void (*dhcp_callback_t) (const enum dhcp_status status);

/**
* @brief Gets IPv4 IP address from DHCP server.
*
* @param iface Network interface on which to start the DHCP client.
* @param callback   Callback function to handle DHCP events.
*/
void dhcp_client_start(struct net_if *iface, dhcp_callback_t callback);

#endif /* _DHCP_ */
