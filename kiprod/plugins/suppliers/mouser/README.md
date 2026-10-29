# Mouser Electronics supplier profile

- Category: Component distributor
- Official site: https://www.mouser.com/
- Integration status: read-only Search API adapter is available; it is inactive until you configure a key.
- Offers can also be reviewed from supplier quote files imported through KiProd’s RFQ workflow.
- Verify current pricing, stock, lead time, process capabilities, and terms directly with the supplier.
- Listed-name aliases: MOUSER.
- Request a Search API key from the official [Mouser API page](https://www.mouser.com/en/api-search/) and review its terms before use.
- Store the API key in the OS keyring through the supplier settings tab. CLI search requires the optional `keyring` dependency (`./scripts/setup-suppliers.sh` installs it).
- Search calls use the read-only `/api/v2/search/keywordandmanufacturer` endpoint. Cart and order APIs are not used.
