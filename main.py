from connectors.shopify_connector import ShopifyConnector

def main() -> None:
    connector = ShopifyConnector.from_env()
    orders = connector.fetch_orders(None)
    print(f"{len(orders)} orders")
    for order in orders:
        print(order.payload["name"], order.source_updated_at)


if __name__ == "__main__":
    main()
