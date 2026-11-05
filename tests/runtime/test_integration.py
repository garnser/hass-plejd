"""Native HA regression checks without BLE commands or production data."""
import tempfile
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.plejd.registry_migration import reconcile_primary_connections
from custom_components.plejd.plejd_entity import device_info
from custom_components.plejd.event import PlejdButtonEvent

MAC = "AA:BB:CC:DD:EE:FF"
CONNECTION = (dr.CONNECTION_BLUETOOTH, MAC)


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.temp.name)
        self.entry = ConfigEntry(version=1, minor_version=1, domain="plejd", title="Test",
            data={}, options={}, source="user", unique_id=None,
            discovery_keys=MappingProxyType({}), subentries_data=[], state=ConfigEntryState.LOADED)
        self.hass.config_entries = SimpleNamespace(async_get_entry=lambda key: self.entry)
        self.registry = dr.DeviceRegistry(self.hass)
        self.hass.data[dr.DATA_REGISTRY] = self.registry
        await self.registry.async_load(load_empty=True)

    async def asyncTearDown(self):
        self.temp.cleanup()

    def create(self, ident, **kwargs):
        return self.registry.async_get_or_create(config_entry_id=self.entry.entry_id,
            identifiers={("plejd", ident)}, **kwargs)

    def device(self, ident, primary=True, parent=None):
        return SimpleNamespace(is_primary=primary, ble_mac=MAC, device_identifier=ident,
            parent_identifier=parent or ident, name="Test output", hardware="DIM-02",
            room=None, firmware="4.35.6")

    async def test_reproduces_collision_and_moves_connection_without_replacing_devices(self):
        old = self.create("physical:old", connections={CONNECTION})
        new = self.create("physical:new", via_device_id=old.id)
        self.registry.async_update_device(old.id, name_by_user="Existing name")
        with self.assertRaises(dr.DeviceInfoError):
            self.create("physical:new", connections={CONNECTION})
        primary = self.device("physical:new")
        secondary = self.device("physical:old", primary=False, parent="physical:new")
        reconcile_primary_connections(self.hass, [secondary, primary], self.entry.entry_id)
        updated_new = self.registry.async_get_or_create(config_entry_id=self.entry.entry_id,
            **device_info(self.hass, primary, self.entry.entry_id))
        updated_old = self.registry.async_get_or_create(config_entry_id=self.entry.entry_id,
            **device_info(self.hass, secondary, self.entry.entry_id))
        self.assertEqual(updated_new.id, new.id)
        self.assertEqual(updated_old.id, old.id)
        self.assertEqual(updated_new.connections, {CONNECTION})
        self.assertFalse(updated_old.connections)
        self.assertIsNone(updated_new.via_device_id)
        self.assertEqual(updated_old.via_device_id, new.id)
        self.assertEqual(updated_old.name_by_user, "Existing name")

    async def test_new_primary_can_be_registered_after_connection_is_released(self):
        old = self.create("physical:old", connections={CONNECTION})
        reconcile_primary_connections(self.hass, [self.device("physical:new")], self.entry.entry_id)
        new = self.create("physical:new", connections={CONNECTION})
        self.assertNotEqual(new.id, old.id)
        self.assertFalse(self.registry.async_get(old.id).connections)

    async def test_repeated_reconciliation_keeps_connection_and_unrelated_devices(self):
        primary = self.create("physical:new", connections={CONNECTION})
        other = self.create("other", connections={(dr.CONNECTION_BLUETOOTH, "11:22:33:44:55:66")})
        before = self.registry.async_get(other.id)
        for _ in range(2):
            reconcile_primary_connections(self.hass,
                [self.device("physical:new"), self.device("physical:new"), SimpleNamespace()],
                self.entry.entry_id)
        self.assertEqual(self.registry.async_get(primary.id).connections, {CONNECTION})
        self.assertEqual(self.registry.async_get(other.id), before)

    async def test_other_config_entries_are_not_modified(self):
        other = self.create("physical:other", connections={CONNECTION})
        reconcile_primary_connections(self.hass, [self.device("physical:new")], "different-entry")
        self.assertEqual(self.registry.async_get(other.id).connections, {CONNECTION})


class EventTests(unittest.TestCase):
    def test_button_events_preserve_native_gesture_fields(self):
        event = PlejdButtonEvent.__new__(PlejdButtonEvent)
        event._trigger_event = Mock()
        for action in ["press", "release", "click", "dim"]:
            payload = {"action": action, "on": True, "brightness": 80, "brightness_delta": 10}
            event._handle_update(payload)
        self.assertEqual(event._trigger_event.call_args_list[0].args, ("press",))
        self.assertEqual(event._trigger_event.call_args_list[1].args, ("release",))
        self.assertEqual(event._trigger_event.call_args_list[2].args, ("click", {"on": True}))
        self.assertEqual(event._trigger_event.call_args_list[3].args,
            ("dim", {"brightness": 80, "brightness_delta": 10}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
