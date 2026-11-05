"""Replay WPH-01 tap/dim traffic captured with no native load assigned."""

from types import SimpleNamespace
import unittest

from pyplejd import PlejdManager
from pyplejd.ble.lastdata import LastData
from pyplejd.interface.plejd_button import PlejdButton
import test_plejd_button as button_tests


class WphGestureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        button_tests.PlejdButtonTests.setUp(self)
        self.button.plejdDevice.firmware = SimpleNamespace(notes="WPH-01")
        self.manager = object.__new__(PlejdManager)
        self.manager.devices = [self.button]

    async def replay(self, *frames):
        for frame in frames:
            await self.manager.lastdata_callback(LastData(bytearray.fromhex(frame)))

    async def test_upper_tap(self):
        await self.replay("000110001627015a0a01", "270110009701")
        self.assertEqual(self.events, [
            {"button": 1, "action": "press"},
            {"button": 1, "action": "click", "on": True},
        ])

    async def test_lower_tap(self):
        self.button.settings.input = 3
        await self.replay("000110001627033d2001", "270110009700")
        self.assertEqual(self.events[-1], {"button": 3, "action": "click", "on": False})

    async def test_upper_hold_has_relative_steps_without_click(self):
        await self.replay(
            "00011000162701d50a01", "2701100098010000",
            "270110009801400a", "270110009801c01e",
            "000110001627011c0b00",
        )
        self.assertEqual([e["action"] for e in self.events], ["press", "dim", "dim", "dim", "release"])
        self.assertEqual([e["brightness_delta"] for e in self.events if e["action"] == "dim"], [0, 10, 20])

    async def test_lower_hold_has_negative_steps(self):
        self.button.settings.input = 3
        await self.replay(
            "00011000162703ce0a01", "27011000980190f8",
            "27011000980170f3", "270110009801d0d9",
            "00011000162703bd0a00",
        )
        self.assertEqual([e["brightness_delta"] for e in self.events if e["action"] == "dim"], [0, -5, -26])
        self.assertEqual(self.events[-1]["action"], "release")

    async def test_packets_without_press_are_ignored(self):
        await self.replay("270110009701", "270110009801400a")
        self.assertEqual(self.events, [])

    async def test_release_disarms_late_dimming(self):
        await self.replay("00011000162701d50a01", "2701100098010000", "000110001627011c0b00")
        count = len(self.events)
        await self.replay("270110009801400a", "270110009700")
        self.assertEqual(len(self.events), count)

    async def test_other_input_disarms_previous_hold(self):
        await self.replay("00011000162701d50a01", "2701100098010000")
        count = len(self.events)
        await self.replay("00011000162703ce0a01", "27011000980190f8")
        self.assertEqual(len(self.events), count)

    async def test_hold_does_not_emit_click_on_state_update(self):
        await self.replay("00011000162701d50a01", "2701100098010000", "270110009700")
        self.assertEqual([e["action"] for e in self.events], ["press", "dim"])

    async def test_foreign_address_does_not_drive_gestures(self):
        await self.replay("00011000162701d50a01", "260110009701", "260110009801400a")
        self.assertEqual([e["action"] for e in self.events], ["press"])

    async def test_only_pending_input_receives_gesture(self):
        lower = PlejdButton(
            address=42, deviceAddress=39, device=self.button.deviceData,
            plejdDevice=self.button.plejdDevice, settings=SimpleNamespace(input=3),
            room=None, mesh=None, rxAddress=42,
        )
        other_events = []
        lower.subscribe(other_events.append)
        self.manager.devices.append(lower)
        await self.replay("00011000162701d50a01", "2701100098010000")
        self.assertEqual(other_events, [])
        await self.replay("00011000162703ce0a01", "27011000980190f8")
        self.assertEqual([e["action"] for e in other_events], ["press", "dim"])

    async def test_wired_button_gestures_are_unchanged(self):
        self.button.plejdDevice.firmware.notes = "DIM-01"
        await self.replay("00011000162701d50a01", "270110009701", "270110009801400a")
        self.assertEqual(self.events, [{"button": 1, "action": "press"}])

    async def test_stale_pending_gesture_expires(self):
        await self.replay("00011000162701d50a01")
        self.button._gesture_last_seen -= 2
        await self.replay("270110009801400a", "270110009701")
        self.assertEqual(self.events, [{"button": 1, "action": "press"}])

    async def test_hold_updates_at_a_brightness_limit_are_not_dropped(self):
        self.button.settings.input = 3
        await self.replay(
            "00011000162703ce0a01",
            "2701100098010000",
            "2701100098010000",
            "00011000162703bd0a00",
        )
        self.assertEqual(
            [event["action"] for event in self.events],
            ["press", "dim", "dim", "release"],
        )
        self.assertEqual(
            [event["brightness_delta"] for event in self.events if event["action"] == "dim"],
            [0, 0],
        )
