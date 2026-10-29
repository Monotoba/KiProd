# KiProd JSON catalog adapter protocol

`kiprod.plugins.suppliers.json_catalog.JsonCatalogAdapter` adapts a supplier's
read-only JSON catalog endpoint into KiProd `Offer` records. It does not initiate
orders, reserve stock, add items to carts, or write supplier data.

## Request

Call `search` with a non-empty MPN, an HTTPS `endpoint`, a KiProd `supplier_id`,
and optional expected currency and bearer token. The adapter adds an URL-encoded
`mpn` query parameter while preserving other query parameters. If supplied, the
token is sent as an Authorization bearer token. Do not put credentials in the URL.
The endpoint hostname must be listed under the plugin manifest's
`permissions.network`; the trusted host brokers the actual request through
`HttpClient`.

## Response

The endpoint returns HTTP 200 and JSON shaped as follows:

```json
{
  "items": [
    {
      "supplier_part_number": "C14663",
      "manufacturer_part_number": "RC0603FR-074K7L",
      "currency": "USD",
      "price_breaks": [
        {"quantity": 1, "unit_price": "0.01"},
        {"quantity": 1000, "unit_price": "0.004"}
      ],
      "stock": 12000,
      "lead_time_days": 3
    }
  ]
}
```

`stock` and `lead_time_days` are optional and non-negative. Price breaks are
required, have non-negative prices and strictly ascending positive quantities.
Items for other MPNs are ignored. A caller may require an expected currency; a
mismatch is an error rather than a silent conversion. Offers retain the request
URL and queried MPN as their source reference.

The adapter is validated against recorded fixtures only. A supplier-specific
plugin must confirm the provider's current API terms, map its response to this
shape, declare its hostname, and configure its credentials before any live call.
