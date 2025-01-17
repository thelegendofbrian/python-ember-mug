"""Tests for `ember_mug.mug connections`."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak import BleakError
from bleak.backends.device import BLEDevice

from ember_mug.consts import (
    EMBER_MUG,
    EXTRA_ATTRS,
    INITIAL_ATTRS,
    UPDATE_ATTRS,
    MugCharacteristic,
    TemperatureUnit,
    VolumeLevel,
)
from ember_mug.data import Colour, Model
from ember_mug.mug import EmberMug


@patch("ember_mug.mug.IS_LINUX", True)
async def test_adapter_with_bluez(ble_device: BLEDevice):
    mug = EmberMug(ble_device, adapter="hci0")
    assert mug._client_kwargs["adapter"] == "hci0"


@patch("ember_mug.mug.IS_LINUX", False)
async def test_adapter_without_bluez(ble_device: BLEDevice):
    with pytest.raises(ValueError):
        EmberMug(ble_device, adapter="hci0")


@patch("ember_mug.mug.EmberMug.subscribe")
@patch("ember_mug.mug.establish_connection")
async def test_connect(
    mug_subscribe: AsyncMock,
    mock_establish_connection: AsyncMock,
    ember_mug: AsyncMock,
) -> None:
    # Already connected
    ember_mug._client = AsyncMock()
    ember_mug._client.is_connected = True
    async with ember_mug.connection():
        pass
    mug_subscribe.assert_not_called()
    mock_establish_connection.assert_not_called()

    # Not connected
    ember_mug._client = None
    ember_mug.disconnect = AsyncMock()
    async with ember_mug.connection():
        pass

    mock_establish_connection.assert_called()
    mug_subscribe.assert_called()
    assert ember_mug._client is not None
    ember_mug.disconnect.assert_called()


@patch("ember_mug.mug.logger")
@patch("ember_mug.mug.establish_connection")
async def test_connect_error(
    mock_establish_connection: AsyncMock,
    mock_logger: Mock,
    ember_mug: AsyncMock,
) -> None:
    ember_mug._client = None  # type: ignore[assignment]
    mock_establish_connection.side_effect = BleakError
    with pytest.raises(BleakError):
        await ember_mug._ensure_connection()
    msg, device, exception = mock_logger.error.mock_calls[0].args
    assert msg == "%s: Failed to connect to the mug: %s"
    assert device == ember_mug.device
    assert isinstance(exception, BleakError)


@patch("ember_mug.mug.logger")
@patch("ember_mug.mug.establish_connection")
async def test_pairing_exceptions_esphome(
    mock_establish_connection: AsyncMock,
    mock_logger: Mock,
    ember_mug: AsyncMock,
) -> None:
    ember_mug._client.is_connected = False
    mock_client = AsyncMock()
    mock_client.connect.side_effect = BleakError
    mock_client.pair.side_effect = NotImplementedError
    mock_establish_connection.return_value = mock_client
    with patch.multiple(
        ember_mug,
        update_initial=AsyncMock(),
        subscribe=AsyncMock(),
    ):
        await ember_mug._ensure_connection()

    mock_establish_connection.assert_called_once()
    mock_logger.warning.assert_called_with(
        "Pairing not implemented. "
        "If your mug is still in pairing mode (blinking blue) tap the button on the bottom to exit.",
    )


@patch("ember_mug.mug.establish_connection")
async def test_pairing_exceptions(
    mock_establish_connection: AsyncMock,
    ember_mug: AsyncMock,
) -> None:
    mock_client = AsyncMock()
    mock_client.pair.side_effect = BleakError
    mock_establish_connection.return_value = mock_client
    with patch.multiple(
        ember_mug,
        update_initial=AsyncMock(),
        subscribe=AsyncMock(),
    ):
        await ember_mug._ensure_connection()


async def test_disconnect(ember_mug: AsyncMock) -> None:
    mock_client = AsyncMock()
    ember_mug._client = mock_client

    mock_client.is_connected = False
    await ember_mug.disconnect()
    assert ember_mug._client is None
    mock_client.disconnect.assert_not_called()

    mock_client.is_connected = True
    ember_mug._client = mock_client
    await ember_mug.disconnect()
    assert ember_mug._client is None
    mock_client.disconnect.assert_called()


@patch("ember_mug.mug.logger")
def test_disconnect_callback(mock_logger: Mock, ember_mug: AsyncMock) -> None:
    ember_mug._expected_disconnect = True
    ember_mug._disconnect_callback(AsyncMock())
    mock_logger.debug.assert_called_with("Disconnect callback called")
    mock_logger.reset_mock()

    ember_mug._expected_disconnect = False
    ember_mug._disconnect_callback(AsyncMock())
    mock_logger.warning.assert_called_with("Unexpectedly disconnected")


@patch("ember_mug.mug.logger")
async def test_read(
    mock_logger: Mock,
    ember_mug: AsyncMock,
) -> None:
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"TEST"
        await ember_mug._read(MugCharacteristic.MUG_NAME)
        ember_mug._client.read_gatt_char.assert_called_with(
            MugCharacteristic.MUG_NAME.uuid,
        )
        mock_logger.debug.assert_called_with(
            "Read attribute '%s' with value '%s'",
            MugCharacteristic.MUG_NAME,
            b"TEST",
        )


@patch("ember_mug.mug.logger")
async def test_write(mock_logger: Mock, ember_mug: AsyncMock) -> None:
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        test_name = bytearray(b"TEST")
        await ember_mug._write(
            MugCharacteristic.MUG_NAME,
            test_name,
        )
        ember_mug._client.write_gatt_char.assert_called_with(
            MugCharacteristic.MUG_NAME.uuid,
            test_name,
        )
        mock_logger.debug.assert_called_with(
            "Wrote '%s' to attribute '%s'",
            test_name,
            MugCharacteristic.MUG_NAME,
        )

        ember_mug._client = AsyncMock()
        ember_mug._client.write_gatt_char.side_effect = BleakError
        with pytest.raises(BleakError):
            await ember_mug._write(
                MugCharacteristic.MUG_NAME,
                test_name,
            )
        ember_mug._client.write_gatt_char.assert_called_with(
            MugCharacteristic.MUG_NAME.uuid,
            test_name,
        )
        msg, data, char, exception = mock_logger.error.mock_calls[0].args
        assert msg == "Failed to write '%s' to attribute '%s': %s"
        assert data == test_name
        assert char == MugCharacteristic.MUG_NAME
        assert isinstance(exception, BleakError)


def test_set_device(ember_mug: AsyncMock) -> None:
    new_device = BLEDevice(
        address="BA:36:a5:be:88:cb",
        name="Ember Ceramic Mug",
        details={},
        rssi=1,
    )
    assert ember_mug.device.address != new_device.address
    ember_mug.set_device(new_device)
    assert ember_mug.device.address == new_device.address


async def test_get_mug_meta(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"Yw====-ABCDEFGHIJ"
        meta = await ember_mug.get_meta()
        assert meta.mug_id == "WXc9PT09"
        assert meta.serial_number == "ABCDEFGHIJ"
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.MUG_ID.uuid)


async def test_get_mug_battery(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"5\x01"
        battery = await ember_mug.get_battery()
        assert battery.percent == 53.00
        assert battery.on_charging_base is True
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.BATTERY.uuid)


async def test_get_mug_led_colour(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\xf4\x00\xa1\xff"
        colour = await ember_mug.get_led_colour()
        assert colour.as_hex() == "#f400a1"
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LED.uuid)


async def test_set_mug_led_colour(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_led_colour(Colour(244, 0, 161))
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.LED.uuid,
            bytearray(b"\xf4\x00\xa1\xff"),
        )


async def test_set_volume_level_travel_mug(ember_mug: AsyncMock):
    ember_mug.is_travel_mug = True
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_volume_level(VolumeLevel.HIGH)
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.VOLUME.uuid,
            bytearray(b"\02"),
        )
        ember_mug._ensure_connection.reset_mock()
        ember_mug._client.write_gatt_char.reset_mock()

        await ember_mug.set_volume_level(0)
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.VOLUME.uuid,
            bytearray(b"\00"),
        )


async def test_set_volume_level_mug(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        with pytest.raises(NotImplementedError):
            await ember_mug.set_volume_level(VolumeLevel.HIGH)
        ember_mug._ensure_connection.assert_not_called()
        ember_mug._client.write_gatt_char.assert_not_called()


async def test_get_mug_target_temp(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\xcd\x15"
        assert (await ember_mug.get_target_temp()) == 55.81
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TARGET_TEMPERATURE.uuid)


async def test_set_mug_target_temp(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_target_temp(55.81)
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.TARGET_TEMPERATURE.uuid,
            bytearray(b"\xcd\x15"),
        )


async def test_get_mug_current_temp(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\xcd\x15"
        assert (await ember_mug.get_current_temp()) == 55.81
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.CURRENT_TEMPERATURE.uuid)


async def test_get_mug_liquid_level(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\n"
        assert (await ember_mug.get_liquid_level()) == 10
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LIQUID_LEVEL.uuid)


async def test_get_mug_liquid_state(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\x06"
        assert (await ember_mug.get_liquid_state()) == 6
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LIQUID_STATE.uuid)


async def test_get_mug_name(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"Mug Name"
        assert (await ember_mug.get_name()) == "Mug Name"
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.MUG_NAME.uuid)


async def test_set_mug_name(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()), pytest.raises(ValueError):
        await ember_mug.set_name("Hé!")

    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_name("Mug name")
        ember_mug._ensure_connection.assert_called()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.MUG_NAME.uuid,
            bytearray(b"Mug name"),
        )


async def test_get_mug_udsk(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"abcd12345"
        assert (await ember_mug.get_udsk()) == "YWJjZDEyMzQ1"
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.UDSK.uuid)


async def test_set_mug_udsk(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_udsk("abcd12345")
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.UDSK.uuid,
            bytearray(b"YWJjZDEyMzQ1"),
        )


async def test_get_mug_dsk(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"abcd12345"
        assert (await ember_mug.get_dsk()) == "YWJjZDEyMzQ1"
        ember_mug._client.read_gatt_char.return_value = b"something else"
        assert (await ember_mug.get_dsk()) == "c29tZXRoaW5nIGVsc2U="
        ember_mug._client.read_gatt_char.assert_called_with(MugCharacteristic.DSK.uuid)


async def test_get_mug_temperature_unit(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\x01"
        assert (await ember_mug.get_temperature_unit()) == TemperatureUnit.FAHRENHEIT
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TEMPERATURE_UNIT.uuid)
        ember_mug._client.read_gatt_char.reset_mock()
        ember_mug._client.read_gatt_char.return_value = b"\x00"
        assert (await ember_mug.get_temperature_unit()) == TemperatureUnit.CELSIUS
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TEMPERATURE_UNIT.uuid)


async def test_set_mug_temperature_unit(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        await ember_mug.set_temperature_unit(TemperatureUnit.CELSIUS)
        ember_mug._ensure_connection.assert_called_once()
        ember_mug._client.write_gatt_char.assert_called_once_with(
            MugCharacteristic.TEMPERATURE_UNIT.uuid,
            bytearray(b"\x00"),
        )


async def test_mug_ensure_correct_unit(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug.data.temperature_unit = TemperatureUnit.CELSIUS
        ember_mug.data.use_metric = True
        ember_mug.set_temperature_unit = AsyncMock(return_value=None)
        await ember_mug.ensure_correct_unit()
        ember_mug.set_temperature_unit.assert_not_called()
        ember_mug.data.temperature_unit = TemperatureUnit.FAHRENHEIT
        await ember_mug.ensure_correct_unit()
        ember_mug.set_temperature_unit.assert_called_with(TemperatureUnit.CELSIUS)


async def test_get_mug_battery_voltage(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"\x01"
        assert (await ember_mug.get_battery_voltage()) == 1
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.CONTROL_REGISTER_DATA.uuid)


async def test_get_mug_date_time_zone(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"c\x0f\xf6\x00"
        date_time = await ember_mug.get_date_time_zone()
        assert date_time.timestamp() == 1661990400.0
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.DATE_TIME_AND_ZONE.uuid)


async def test_read_firmware(ember_mug: AsyncMock):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._client.read_gatt_char.return_value = b"c\x01\x80\x00\x12\x00"
        firmware = await ember_mug.get_firmware()
        assert firmware.version == 355
        assert firmware.hardware == 128
        assert firmware.bootloader == 18
        ember_mug._client.read_gatt_char.assert_called_once_with(MugCharacteristic.FIRMWARE.uuid)


async def test_mug_update_initial(ember_mug):
    no_extra = INITIAL_ATTRS - EXTRA_ATTRS

    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._update_multiple = AsyncMock(return_value={})
        ember_mug.data.model = Model(EMBER_MUG, include_extra=False)
        assert (await ember_mug.update_initial()) == {}
        ember_mug._update_multiple.assert_called_once_with(no_extra)

    # Try with extra
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._update_multiple.reset_mock()
        ember_mug.data.model = Model(EMBER_MUG, include_extra=True)
        assert (await ember_mug.update_initial()) == {}
        ember_mug._update_multiple.assert_called_once_with(INITIAL_ATTRS)


async def test_mug_update_all(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._update_multiple = AsyncMock(return_value={})
        assert (await ember_mug.update_all()) == {}
        ember_mug._update_multiple.assert_called_once_with(UPDATE_ATTRS - EXTRA_ATTRS)

    # Try with extras
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._update_multiple.reset_mock()
        ember_mug._update_attrs = UPDATE_ATTRS
        assert (await ember_mug.update_all()) == {}
        ember_mug._update_multiple.assert_called_once_with(UPDATE_ATTRS)


async def test_mug_update_multiple(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug.get_name = AsyncMock(return_value="name")
        ember_mug.data.update_info = AsyncMock()
        await ember_mug._update_multiple(("name",))
        ember_mug.data.update_info.assert_called_once_with(name="name")


async def test_mug_update_queued_attributes(ember_mug):
    with patch.object(ember_mug, "_ensure_connection", AsyncMock()):
        ember_mug._queued_updates = set()
        assert (await ember_mug.update_queued_attributes()) == []
        ember_mug.get_name = AsyncMock(return_value="name")
        ember_mug.data.update_info = AsyncMock()
        ember_mug._queued_updates = {"name"}
        await ember_mug.update_queued_attributes()
        ember_mug.data.update_info.assert_called_once_with(name="name")


def test_mug_notify_callback(ember_mug: EmberMug) -> None:
    gatt_char = AsyncMock()
    ember_mug._notify_callback(gatt_char, bytearray(b"\x01"))
    ember_mug._notify_callback(gatt_char, bytearray(b"\x02"))
    assert 2 in ember_mug._latest_events
    ember_mug._notify_callback(gatt_char, bytearray(b"\x04"))
    assert 4 in ember_mug._latest_events
    ember_mug._notify_callback(gatt_char, bytearray(b"\x05"))
    assert 5 in ember_mug._latest_events
    ember_mug._notify_callback(gatt_char, bytearray(b"\x06"))
    assert 6 in ember_mug._latest_events
    ember_mug._notify_callback(gatt_char, bytearray(b"\x07"))
    assert 7 in ember_mug._latest_events
    ember_mug._notify_callback(gatt_char, bytearray(b"\x08"))
    assert 8 in ember_mug._latest_events
    callback = Mock()
    second_callback = Mock()
    unregister = ember_mug.register_callback(callback)
    second_unregister = ember_mug.register_callback(second_callback)
    repeat_unregister = ember_mug.register_callback(callback)
    assert unregister is repeat_unregister
    assert unregister is not second_unregister

    assert callback in ember_mug._callbacks
    ember_mug._notify_callback(gatt_char, bytearray(b"\x09"))
    assert 9 in ember_mug._latest_events
    callback.assert_not_called()
    assert ember_mug._queued_updates == {
        "battery",
        "target_temp",
        "current_temp",
        "liquid_level",
        "liquid_state",
        "battery_voltage",
    }
    ember_mug._latest_events = {}
    ember_mug._notify_callback(gatt_char, bytearray(b"\x02"))
    callback.assert_called_once()
    callback.reset_mock()
    ember_mug._notify_callback(gatt_char, bytearray(b"\x02"))
    callback.assert_not_called()
    # Remove callback
    unregister()
    assert callback not in ember_mug._callbacks
