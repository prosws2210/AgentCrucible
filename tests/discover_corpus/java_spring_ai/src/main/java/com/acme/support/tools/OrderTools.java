package com.acme.support.tools;

import java.util.Map;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClient;

@Service
public class OrderTools {

    private final JdbcTemplate jdbc;
    private final RestClient carrier;

    public OrderTools(JdbcTemplate jdbc,
                      @Value("${carrier.base-url}") String carrierUrl,
                      @Value("${carrier.api-key}") String carrierKey) {
        this.jdbc = jdbc;
        this.carrier = RestClient.builder()
                .baseUrl(carrierUrl)
                .defaultHeaders(h -> h.setBasicAuth(carrierKey, ""))
                .build();
    }

    @Tool(description = "Get the status, total and tracking code of an order")
    public Map<String, Object> getOrderStatus(@ToolParam(description = "Order number, e.g. A-10042") String orderId) {
        return jdbc.queryForMap(
                "SELECT id, status, total_cents, tracking_code FROM orders WHERE id = ?", orderId);
    }

    @Tool(description = "Cancel an order that has not shipped. Requires explicit customer confirmation.")
    @Transactional
    public String cancelOrder(String orderId, @ToolParam(description = "Why the customer is cancelling") String reason) {
        int updated = jdbc.update(
                "UPDATE orders SET status = 'CANCELLED', cancel_reason = ? WHERE id = ? AND status IN ('NEW','PAID')",
                reason, orderId);
        jdbc.update("INSERT INTO order_audit (order_id, action, detail) VALUES (?, 'CANCEL', ?)", orderId, reason);
        return updated == 1 ? "Order " + orderId + " cancelled" : "Order cannot be cancelled";
    }

    @Tool(name = "track_shipment", description = "Get live carrier tracking events for a tracking code")
    public String trackShipment(String trackingCode) {
        return carrier.get()
                .uri("/trackers?tracking_code={code}", trackingCode)
                .retrieve()
                .body(String.class);
    }
}
