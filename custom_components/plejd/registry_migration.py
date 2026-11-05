"""Keep device identities when the cloud changes a multi-output primary."""

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


@callback
def reconcile_primary_connections(hass, devices, config_entry_id):
    """Move only the BLE connection; preserve device/entity IDs and settings.

    A DIM-02 has multiple logical device records sharing one physical MAC.
    Cloud ordering can change which output is primary. HA cannot attach the
    MAC to the new primary while it still belongs to another record in the
    same config entry. An omitted connections field does not remove it.
    """
    registry = dr.async_get(hass)
    entries = list(dr.async_entries_for_config_entry(registry, config_entry_id))
    handled = set()
    for device in devices:
        if not getattr(device, "is_primary", False):
            continue
        mac = getattr(device, "ble_mac", None)
        identifier = getattr(device, "device_identifier", None)
        if not mac or not identifier or mac in handled:
            continue
        handled.add(mac)
        connection = (dr.CONNECTION_BLUETOOTH, mac)
        primary = registry.async_get_device_by_identifier(
            (DOMAIN, identifier), config_entry_id
        )
        # A former secondary must no longer point back to the old primary.
        if primary is not None and primary.via_device_id is not None:
            registry.async_update_device(primary.id, via_device_id=None)
        for entry in entries:
            if connection not in entry.connections:
                continue
            if primary is not None and entry.id == primary.id:
                continue
            registry.async_update_device(
                entry.id, new_connections=set(entry.connections) - {connection}
            )
