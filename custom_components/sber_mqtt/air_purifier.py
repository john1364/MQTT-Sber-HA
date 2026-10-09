"""Очиститель воздуха (hvac_air_purifier): сопоставление сущностей HA и функций Сбера.

В HA очиститель обычно представлен набором отдельных сущностей
(switch питания, select скорости/режима, sensor ресурса фильтра и т.д.).
Здесь собрана вся логика чтения состояния и подбора команд по настройкам
устройства, сохранённым в мастере добавления. Модуль не зависит от MQTT.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    AIR_PURIFIER_BOOL_FEATURES,
    AIR_PURIFIER_ENTITY_KEYS,
    AIR_PURIFIER_REPLACE_FEATURES,
    AIR_PURIFIER_SELECT_DOMAINS,
    AIR_PURIFIER_SPEED_VALUES,
)

_NO_VALUE = ("unavailable", "unknown", "")


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if entity_id else ""


def watched_entities(attrs: dict) -> set[str]:
    """Все сущности HA, изменения которых влияют на состояние устройства."""
    return {attrs[k] for k in AIR_PURIFIER_ENTITY_KEYS if attrs.get(k)}


def clean_speed_map(attrs: dict) -> dict[str, str]:
    """{значение Сбера: опция select} — только корректные непустые пары."""
    raw = attrs.get("speed_map") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: str(v) for k, v in raw.items()
        if k in AIR_PURIFIER_SPEED_VALUES and v not in (None, "")
    }


def declared_features(attrs: dict) -> list[str]:
    """Список функций Сбера, который нужно объявить в модели устройства."""
    features = ["online", "on_off"]
    if attrs.get("speed_entity") and clean_speed_map(attrs):
        features.append("hvac_air_flow_power")
    for name, sber_key in AIR_PURIFIER_BOOL_FEATURES.items():
        if attrs.get(f"{name}_entity"):
            features.append(sber_key)
    for name, sber_key in AIR_PURIFIER_REPLACE_FEATURES.items():
        if attrs.get(f"{name}_entity"):
            features.append(sber_key)
    return features


def _state(hass: HomeAssistant, entity_id: str | None):
    return hass.states.get(entity_id) if entity_id else None


def power_state(hass: HomeAssistant, attrs: dict) -> bool:
    st = _state(hass, attrs.get("entity_id"))
    return bool(st and st.state == "on")


def online_state(hass: HomeAssistant, attrs: dict) -> bool:
    """Доступность. Без online_entity устройство всегда онлайн."""
    eid = attrs.get("online_entity")
    if not eid:
        return True
    st = _state(hass, eid)
    if st is None:
        return True
    return st.state not in ("off", "unavailable")


def speed_state(hass: HomeAssistant, attrs: dict) -> str | None:
    """Текущая скорость в терминах Сбера (None — не определена)."""
    if not (attrs.get("speed_entity") and clean_speed_map(attrs)):
        return None
    st = _state(hass, attrs["speed_entity"])
    if st is None or st.state in _NO_VALUE:
        return None
    smap = clean_speed_map(attrs)
    for sber, option in smap.items():
        if option == st.state:
            return sber
    low = st.state.casefold()
    for sber, option in smap.items():
        if option.casefold() == low:
            return sber
    return None


def bool_feature_state(hass: HomeAssistant, attrs: dict, name: str) -> bool | None:
    """Состояние булевого режима (ночной, ионизация…); None — нет данных."""
    eid = attrs.get(f"{name}_entity")
    if not eid:
        return None
    st = _state(hass, eid)
    if st is None or st.state in _NO_VALUE:
        return None
    if domain_of(eid) in AIR_PURIFIER_SELECT_DOMAINS:
        return st.state == attrs.get(f"{name}_on_option")
    return st.state == "on"


def replace_state(hass: HomeAssistant, attrs: dict, name: str) -> bool | None:
    """«Нужно менять» (фильтр / ионизатор); None — нет данных.

    binary_sensor (и любой on/off) — on означает «менять».
    Числовой sensor — сравнение с порогом: cmp="le" (остаток ≤ порога)
    либо cmp="ge" (наработка ≥ порога).
    """
    eid = attrs.get(f"{name}_entity")
    if not eid:
        return None
    st = _state(hass, eid)
    if st is None or st.state in _NO_VALUE:
        return None
    if domain_of(eid) != "sensor":
        return st.state == "on"
    try:
        value = float(st.state)
        threshold = float(attrs.get(f"{name}_threshold"))
    except (ValueError, TypeError):
        return None
    return value >= threshold if attrs.get(f"{name}_cmp") == "ge" else value <= threshold
