/*
 * Copyright (C) 2025 - OWL Services LLC
 *
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License (version 2) as published by the
 * FSF - Free Software Foundation
 *
 */

#ifndef _CONNECTION_MANAGER_H_
#define _CONNECTION_MANAGER_H_

/**
 * @brief Initialization context for the connection manager.
 *
 * This structure holds the parameters required to initialize a network
 * connection.
 *
 * @note The active fields depend on the selected connection type.
 */
struct connection_manager_init_ctx {
#ifdef CONFIG_CONN_MGR_WIFI
    const char *ssid;
    const char *password;
#elif CONFIG_CONN_MGR_BLE
    /* ... Any parameter required for BLE ... */
#elif CONFIG_CONN_MGR_ZETH
    /* ... Any parameter required for ZETH ... */
#endif
};

/**
 * @brief Initializes the connection manager and establishes a network connection.
 *
 * This function performs the initialization steps needed to establish a network
 * connection.
 */
int connection_manager_init(struct connection_manager_init_ctx *ctx);

#endif /*_CONNECTION_MANAGER_H_*/
