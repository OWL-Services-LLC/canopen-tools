/**
 * Copyright (C) 2025 - OWL Services LLC
 *
 *  This program is free software; you can redistribute it and/or modify it under
 *  the terms of the GNU General Public License (version 2) as published by the
 *  FSF - Free Software Foundation
 */

#include <errno.h>
#include <string.h>

#include <zephyr/drivers/can.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_ip.h>
#include <zephyr/net/net_mgmt.h>
#include <zephyr/net/socket.h>
#include <zephyr/net/wifi_mgmt.h>
#include <zephyr/sys/byteorder.h>

#include "connection_manager.h"


LOG_MODULE_REGISTER(app, CONFIG_CANOPEN_TCP_BRIDGE_LOG_LEVEL);


struct __packed tcp_hdr {
    uint32_t can_id_be;
    uint8_t  flags;
    uint8_t  dlc;
};

#define FLAG_EXT (1u << 0)
#define FLAG_RTR (1u << 1)
#define FLAG_FD  (1u << 2)
#define FLAG_BRS (1u << 3)

#define RX_MSGQ_LEN 32

K_MSGQ_DEFINE(can_rx_q, sizeof(struct can_frame), RX_MSGQ_LEN, 4);

static int recv_all(int sock, uint8_t *buf, size_t n)
{
    size_t got = 0;

    while (got < n)
    {
        int r = zsock_recv(sock, buf + got, n - got, 0);
        if (r == 0)
        {
            return -ECONNRESET; /* peer closed */
        }

        if (r < 0)
        {
            if (errno == EAGAIN || errno == EWOULDBLOCK)
            {
                continue;
            }

            return -errno;
        }

        got += (size_t)r;
    }

    return 0;
}

static int tcp_connect(void)
{
    int sock = -1;

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_APP_SERVER_PORT),
    };

    if (net_addr_pton(AF_INET, CONFIG_APP_SERVER_HOST, &addr.sin_addr) != 0)
    {
        LOG_ERR("Invalid server host: %s", CONFIG_APP_SERVER_HOST);
        return -EINVAL;
    }

    sock = zsock_socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock < 0)
    {
        LOG_ERR("zsock_socket() failed: %d", errno);
        return -errno;
    }

    LOG_INF("Connecting to %s:%d ...", CONFIG_APP_SERVER_HOST, CONFIG_APP_SERVER_PORT);
    if (zsock_connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0)
    {
        const int error = errno;
        LOG_ERR("zsock_connect() failed: %d", error);
        zsock_close(sock);
        return -error;
    }

    LOG_INF("TCP connected");

    return sock;
}

static void can_rx_cb(const struct device *dev, struct can_frame *frame, void *user_data)
{
    ARG_UNUSED(dev);
    ARG_UNUSED(user_data);
    (void)k_msgq_put(&can_rx_q, frame, K_NO_WAIT);
}

static int tcp_send_can_frame(int sock, const struct can_frame *cf)
{
    uint8_t flags = 0;

    if (cf->flags & CAN_FRAME_IDE)
    {
        flags |= FLAG_EXT;
    }

    if (cf->flags & CAN_FRAME_RTR)
    {
        flags |= FLAG_RTR;
    }

    struct tcp_hdr tcp_header = {
        .can_id_be = sys_cpu_to_be32(cf->id & 0x1FFFFFFF),
        .flags     = flags,
        .dlc       = cf->dlc,
    };

    uint16_t pay_len = (uint16_t)(sizeof(tcp_header) + cf->dlc);
    uint16_t len_be  = sys_cpu_to_be16(pay_len);

    if (zsock_send(sock, &len_be, sizeof(len_be), 0) != sizeof(len_be))
    {
        return -EIO;
    }

    if (zsock_send(sock, &tcp_header, sizeof(tcp_header), 0) != sizeof(tcp_header))
    {
        return -EIO;
    }

    if (cf->dlc > 0 && zsock_send(sock, cf->data, cf->dlc, 0) != cf->dlc)
    {
        return -EIO;
    }

    return 0;
}

static int can_from_tcp_parts(const struct tcp_hdr *tcp_header,
                              const uint8_t *data, size_t data_len,
                              struct can_frame *out)
{
    if (!tcp_header)
    {
        return -EINVAL;
    }

    if (tcp_header->dlc > 8)
    {
        return -EINVAL;
    }

    if (data_len != tcp_header->dlc)
    {
        return -EINVAL;
    }

    uint32_t can_id = sys_be32_to_cpu(tcp_header->can_id_be);

    out->id    = can_id & 0x1FFFFFFF;
    out->dlc   = tcp_header->dlc;
    out->flags = 0;

    if (tcp_header->flags & FLAG_EXT)
    {
        out->flags |= CAN_FRAME_IDE;
    }

    if (tcp_header->flags & FLAG_RTR)
    {
        out->flags |= CAN_FRAME_RTR;
    }

    if (out->dlc)
    {
        memcpy(out->data, data, out->dlc);
    }

    return 0;
}

int main(void)
{
    int ret;

    struct connection_manager_init_ctx ctx = {
        .ssid = CONFIG_APP_WIFI_SSID,
        .password = CONFIG_APP_WIFI_PASSWORD
    };

    ret = connection_manager_init(&ctx);
    if (ret)
    {
        LOG_WRN("Connection Manager initialization failed: %d", ret);
        return 0;
    }

    int sock = -1;
    while (sock < 0)
    {
        sock = tcp_connect();
        if (sock < 0)
        {
            k_sleep(K_SECONDS(2));
        }
    }

    const struct device *can_dev = DEVICE_DT_GET(DT_NODELABEL(twai));
    if (!device_is_ready(can_dev))
    {
        LOG_ERR("CAN device not ready");
        zsock_close(sock);
        return 0;
    }

    ret = can_start(can_dev);
    if (ret)
    {
        LOG_ERR("can_start() failed: %d", ret);
        zsock_close(sock);
        return 0;
    }

    struct can_filter filter = {
        .flags = 0,
        .id    = 0,
        .mask  = 0, /* mask 0 => no filtering */
    };

    int filter_id = can_add_rx_filter(can_dev, can_rx_cb, NULL, &filter);
    if (filter_id < 0)
    {
        LOG_ERR("can_add_rx_filter() failed: %d", filter_id);
        (void)can_stop(can_dev);
        zsock_close(sock);
        return 0;
    }

    LOG_INF("Bridge running: CAN <-> TCP");

    uint8_t lenbuf[2];
    struct tcp_hdr hdrbuf;
    uint8_t databuf[8];

    bool running = true;

    while (running)
    {
        struct can_frame cf;
        while (k_msgq_get(&can_rx_q, &cf, K_NO_WAIT) == 0)
        {
            (void)tcp_send_can_frame(sock, &cf);
        }

        struct zsock_pollfd pfd = {
            .fd = sock,
            .events = ZSOCK_POLLIN,
        };

        int pr = zsock_poll(&pfd, 1, 10);
        if (pr == 0)
        {
            continue;
        }

        if (pr < 0)
        {
            LOG_ERR("zsock_poll error: %d", errno);
            break;
        }

        if (!(pfd.revents & ZSOCK_POLLIN))
        {
            continue;
        }

        if (recv_all(sock, lenbuf, 2))
        {
            LOG_ERR("recv len failed (peer closed?)");
            break;
        }

        uint16_t pay_len = sys_be16_to_cpu(*(uint16_t *)lenbuf);
        if (pay_len < sizeof(struct tcp_hdr) || pay_len > (sizeof(struct tcp_hdr) + sizeof(databuf)))
        {
            LOG_WRN("Bad payload len=%u", pay_len);
            size_t to_dump = pay_len;
            while (to_dump)
            {
                uint8_t dump[32];
                size_t chunk = MIN(to_dump, sizeof(dump));
                if (recv_all(sock, dump, chunk))
                {
                    running = false;
                    break;
                }
                to_dump -= chunk;
            }
            continue;
        }

        if (recv_all(sock, (uint8_t *)&hdrbuf, sizeof(hdrbuf)))
        {
            LOG_ERR("recv hdr failed");
            break;
        }

        size_t data_len = pay_len - sizeof(struct tcp_hdr);

        if (data_len)
        {
            if (recv_all(sock, databuf, data_len))
            {
                LOG_ERR("recv data failed");
                break;
            }
        }

        struct can_frame out = {0};
        int pe = can_from_tcp_parts(&hdrbuf, databuf, data_len, &out);
        if (pe == 0)
        {
            ret = can_send(can_dev, &out, K_MSEC(10), NULL, NULL);
            if (ret)
            {
                LOG_WRN("can_send: %d", ret);
            }
        }
        else
        {
            LOG_WRN("Bad TCP record -> drop");
        }
    }

    can_remove_rx_filter(can_dev, filter_id);
    (void)can_stop(can_dev);
    zsock_close(sock);
    LOG_INF("Bridge stopped");
}
