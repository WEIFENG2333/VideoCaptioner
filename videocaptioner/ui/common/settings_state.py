from __future__ import annotations

from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal


class SettingValidator:
    def validate(self, value: Any) -> bool:
        return True

    def correct(self, value: Any) -> Any:
        return value


class RangeValidator(SettingValidator):
    def __init__(self, minimum: int | float, maximum: int | float):
        self.min = minimum
        self.max = maximum
        self.range = (minimum, maximum)

    def validate(self, value: Any) -> bool:
        return self.min <= value <= self.max

    def correct(self, value: Any) -> Any:
        return min(max(self.min, value), self.max)


class ChoiceValidator(SettingValidator):
    def __init__(self, options: Any):
        if isinstance(options, type) and issubclass(options, Enum):
            options = list(options)
        self.options = list(options)
        if not self.options:
            raise ValueError("ChoiceValidator requires at least one option")

    def validate(self, value: Any) -> bool:
        return value in self.options

    def correct(self, value: Any) -> Any:
        return value if self.validate(value) else self.options[0]


class BoolValidator(ChoiceValidator):
    def __init__(self):
        super().__init__([True, False])


class FolderValidator(SettingValidator):
    def validate(self, value: Any) -> bool:
        return Path(str(value)).exists()

    def correct(self, value: Any) -> str:
        path = Path(str(value))
        path.mkdir(parents=True, exist_ok=True)
        return str(path.absolute()).replace("\\", "/")


class SettingSerializer:
    def serialize(self, value: Any) -> Any:
        return value

    def deserialize(self, value: Any) -> Any:
        return value


class EnumSettingSerializer(SettingSerializer):
    def __init__(self, enum_class: type[Enum]):
        self.enum_class = enum_class

    def serialize(self, value: Enum) -> Any:
        return value.value

    def deserialize(self, value: Any) -> Enum:
        return self.enum_class(value)


class SettingField(QObject):
    valueChanged = pyqtSignal(object)

    def __init__(
        self,
        group: str,
        name: str,
        default: Any,
        validator: SettingValidator | None = None,
        serializer: SettingSerializer | None = None,
        restart: bool = False,
    ):
        super().__init__()
        self.group = group
        self.name = name
        self.validator = validator or SettingValidator()
        self.serializer = serializer or SettingSerializer()
        self.restart = restart
        self.defaultValue = self.validator.correct(default)
        self._value = self.defaultValue

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, raw_value: Any) -> None:
        if _is_secret_key_field(self) and isinstance(raw_value, str):
            raw_value = raw_value.strip()
        value = self.validator.correct(raw_value)
        old_value = self._value
        self._value = value
        if old_value != value:
            self.valueChanged.emit(value)

    @property
    def key(self) -> str:
        return f"{self.group}.{self.name}" if self.name else self.group

    def serialize(self) -> Any:
        return self.serializer.serialize(self.value)

    def deserializeFrom(self, value: Any) -> None:  # noqa: N802
        self.value = self.serializer.deserialize(value)


class ChoiceSettingField(SettingField):
    @property
    def options(self) -> list[Any]:
        return self.validator.options


class RangeSettingField(SettingField):
    @property
    def range(self) -> tuple[int | float, int | float]:
        return self.validator.range


class SettingsState(QObject):
    appRestartSig = pyqtSignal()
    themeChanged = pyqtSignal(object)
    themeColorChanged = pyqtSignal(object)

    def get(self, item: SettingField) -> Any:
        return item.value

    def set(self, item: SettingField, value: Any, save: bool = True, copy: bool = True) -> None:
        if _is_secret_key_field(item) and isinstance(value, str):
            value = value.strip()
        if item.value == value:
            return
        try:
            item.value = deepcopy(value) if copy else value
        except Exception:
            item.value = value
        if save:
            self.save()
        if item.restart:
            self.appRestartSig.emit()
        if item is getattr(self, "themeMode", None):
            self.themeChanged.emit(value)
        if item is getattr(self, "themeColor", None):
            self.themeColorChanged.emit(value)

    def save(self) -> None:
        raise NotImplementedError


def _is_secret_key_field(item: SettingField) -> bool:
    name = item.name.lower()
    return "key" in name or name.endswith("token") or name.endswith("secret")
