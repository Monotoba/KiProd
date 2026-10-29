# Supplier plugin catalog

KiProd bundles profile plugins for the requested suppliers so they appear in the
CLI and desktop supplier views. Profiles identify the supplier, homepage, and
supported resource category. They are **profile only**: they do not scrape
websites, call supplier APIs, place orders, or claim current prices, stock, lead
times, or verified manufacturing limits. Use the RFQ and quote-import workflow
for supplier-specific offers, then add capability limits only from current,
reviewed supplier documentation or quotations.

Run `kiprod plugins list --project PROJECT` to see the bundled entries. The
`Profile only` status distinguishes supplier metadata from an active adapter.
`docs/production/quotes/config/suppliers/` can still override a bundled profile
using the same stable plugin ID.

## Component distributors

Mouser, LCSC, DigiKey, Newark, Jameco, Unikeyic, TTI, Future Electronics,
Verical, Rochester Electronics, and Allied Electronics & Automation (RS
Americas).

The Mouser profile includes a read-only Search API adapter. Request an API key,
review Mouser's terms, and save the key in the OS keyring before searching:

```bash
kiprod quote MPN --plugin com.kiprod.supplier.mouser
```

Mouser documents product pricing, availability, a maximum of 50 results per
request, and rate limits on its [Search API page](https://www.mouser.com/en/api-search/).
The adapter calls only the Search API; it does not create carts or orders.

The other component profiles use manual quote import. Unikeyic advertises API
access by application on its official [company page](https://www.unikeyic.com/aboutus),
but this does not configure or authorize an API connection in KiProd.

## PCB fabricators

PCBCart (also listed as PCB Cart), PCBWay, JLCPCB (also listed as JLPCB),
AISLER, Sierra Circuits (also listed as SIERRA), HQPCB (also listed as HQ PCB),
NextPCB, AIVON, San Francisco Circuits, Elecrow, Multi-Circuit Boards, and
Sunstone Circuits.

PCBWay, JLCPCB, Sierra Circuits, and San Francisco Circuits profiles also declare
an assembly resource based on their published service pages ([PCBWay](https://www.pcbway.com/assembly-capabilities.html),
[JLCPCB](https://jlcpcb.com/help/article/how-do-i-place-a-pcba-order),
[Sierra Circuits](https://www.protoexpress.com/),
[San Francisco Circuits](https://www.sfcircuits.com/contact-us/about-us)). Their
process limits remain unset until verified for a specific service and quote.

## Assembly and EMS providers

Celestica, Flex (also listed as Flextronics), Plexus, Circuits Central, and
Imagineering, Inc.

## Integration boundary

Only Mouser currently has a supplier-specific live adapter. The generic
read-only JSON catalog protocol can support other suppliers that provide an
approved API with a documented response mapping. Supplier-specific API
integrations must confirm current API terms, endpoints, authentication, and
field provenance before they are enabled. Credentials must be supplied by the
user and stored through the OS keyring; tests must continue using recorded
fixtures only.
