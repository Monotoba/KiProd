from pathlib import Path

from kiprod.plugins.host import discover_plugins

SUPPLIERS = {
    "com.kiprod.supplier.pcbcart",
    "com.kiprod.supplier.pcbway",
    "com.kiprod.supplier.jlcpcb",
    "com.kiprod.supplier.aisler",
    "com.kiprod.supplier.sierra-circuits",
    "com.kiprod.supplier.hqpcb",
    "com.kiprod.supplier.nextpcb",
    "com.kiprod.supplier.aivon",
    "com.kiprod.supplier.san-francisco-circuits",
    "com.kiprod.supplier.elecrow",
    "com.kiprod.supplier.multi-circuit-boards",
    "com.kiprod.supplier.sunstone-circuits",
    "com.kiprod.supplier.mouser",
    "com.kiprod.supplier.lcsc",
    "com.kiprod.supplier.digikey",
    "com.kiprod.supplier.newark",
    "com.kiprod.supplier.jameco",
    "com.kiprod.supplier.unikeyic",
    "com.kiprod.supplier.tti",
    "com.kiprod.supplier.future-electronics",
    "com.kiprod.supplier.verical",
    "com.kiprod.supplier.rochester-electronics",
    "com.kiprod.supplier.allied-rs-americas",
    "com.kiprod.supplier.celestica",
    "com.kiprod.supplier.flex",
    "com.kiprod.supplier.plexus",
    "com.kiprod.supplier.circuits-central",
    "com.kiprod.supplier.imagineering-inc",
}
COMPONENT_SUPPLIERS = {
    "mouser",
    "lcsc",
    "digikey",
    "newark",
    "jameco",
    "unikeyic",
    "tti",
    "future-electronics",
    "verical",
    "rochester-electronics",
    "allied-rs-americas",
}
FABRICATION_SUPPLIERS = {
    "pcbcart",
    "pcbway",
    "jlcpcb",
    "aisler",
    "sierra-circuits",
    "hqpcb",
    "nextpcb",
    "aivon",
    "san-francisco-circuits",
    "elecrow",
    "multi-circuit-boards",
    "sunstone-circuits",
}
ASSEMBLY_SUPPLIERS = {
    "celestica",
    "flex",
    "plexus",
    "circuits-central",
    "imagineering-inc",
}


def test_all_requested_supplier_profiles_are_discoverable() -> None:
    bundled = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers"
    plugins = discover_plugins([bundled])

    assert {plugin.manifest.id for plugin in plugins} >= SUPPLIERS
    profiles = [plugin for plugin in plugins if plugin.manifest.id in SUPPLIERS]
    assert len(profiles) == len(SUPPLIERS)
    assert all(plugin.manifest.homepage.startswith("https://") for plugin in profiles)
    by_slug = {plugin.manifest.id.rsplit(".", 1)[-1]: plugin.manifest for plugin in profiles}
    assert all(
        manifest.status_label
        == (
            "Adapter available"
            if slug in {"mouser", "lcsc", "digikey", "newark"}
            else "Profile only"
        )
        for slug, manifest in by_slug.items()
    )
    assert len(COMPONENT_SUPPLIERS) == 11
    assert len(FABRICATION_SUPPLIERS) == 12
    assert len(ASSEMBLY_SUPPLIERS) == 5
    assert all("components" in by_slug[slug].resource_types for slug in COMPONENT_SUPPLIERS)
    assert all("fabrication" in by_slug[slug].resource_types for slug in FABRICATION_SUPPLIERS)
    assert all("assembly" in by_slug[slug].resource_types for slug in ASSEMBLY_SUPPLIERS)


def test_supplier_profiles_do_not_claim_unverified_capability_limits() -> None:
    bundled = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers"
    plugins = discover_plugins([bundled])

    for plugin in plugins:
        if plugin.manifest.id not in SUPPLIERS:
            continue
        for capability in ("pcb_fab", "pcb_assembly"):
            data = plugin.manifest.capabilities.get(capability)
            if isinstance(data, dict):
                assert data["validation_status"] == "limits_not_configured"
                assert data["limits"] == {}


def test_verified_multi_service_fabricators_declare_assembly_resource() -> None:
    bundled = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers"
    plugins = {plugin.manifest.id: plugin for plugin in discover_plugins([bundled])}

    for supplier in (
        "pcbway",
        "jlcpcb",
        "sierra-circuits",
        "san-francisco-circuits",
    ):
        manifest = plugins[f"com.kiprod.supplier.{supplier}"].manifest
        assert "fabrication" in manifest.resource_types
        assert "assembly" in manifest.resource_types
        assert "pcb_assembly" in manifest.capabilities
