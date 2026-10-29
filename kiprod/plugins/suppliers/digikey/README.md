# DigiKey supplier profile

- Category: Component distributor
- Official site: https://www.digikey.com/
- Integration status: read-only Product Information V4 adapter is available; it requires a registered OAuth application.
- Offers can be reviewed from supplier quote files imported through KiProd’s RFQ workflow.
- Verify current pricing, stock, lead time, process capabilities, and terms directly with the supplier.
- Listed-name aliases: DIGIKEY.
- Register a DigiKey API application, subscribe it to Product Information V4, and review DigiKey API terms before use.
- Store the client ID and secret in the OS keyring through the supplier settings tab.
- Search uses OAuth 2-legged client credentials followed by Product Information V4 KeywordSearch. Set site, language, and currency in supplier settings. It reports StandardPricing; MyPricing is not returned by KeywordSearch, and keyword prices may be cached for up to 24 hours. This adapter does not access ordering or cart APIs.
