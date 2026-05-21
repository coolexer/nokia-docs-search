"""Central product metadata for parsing, search aliases, and indexing."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseNoteProduct:
    key: str
    slug: str
    display_name: str


PRODUCT_PATTERNS: list[tuple[str, str]] = [
    ("SR Linux", "srlinux-26-3"),
    ("sr-linux", "srlinux-26-3"),
    ("srlinux", "srlinux-26-3"),
    ("NSP webdocs", "nsp"),
    ("webdocs-enus", "nsp"),
    ("26-3", "sros-26-3"),
    ("7250_ixr", "7250-ixr"),
    ("7250_IXR", "7250-ixr"),
    ("7705 sar gen2", "7705-sar-gen2"),
    ("7705_sar_gen2", "7705-sar-gen2"),
    ("7705 sar", "7705-sar"),
    ("7705_sar", "7705-sar"),
    ("7210_sas", "7210-sas"),
    ("7210_SAS", "7210-sas"),
    ("7x50-shared", "sros-26-3"),
]


PRODUCT_ALIASES: dict[str, str] = {
    "srlinux": "srlinux-26-3",
    "sr linux": "srlinux-26-3",
    "sr-linux": "srlinux-26-3",
    "srl": "srlinux-26-3",
    "nsp": "nsp",
    "sros": "sros-26-3",
    "sr os": "sros-26-3",
    "sr-os": "sros-26-3",
    "sros-26-3": "sros-26-3",
    "sros 26.3": "sros-26-3",
    "sros26": "sros-26-3",
    "7750": "sros-26-3",
    "7750-sr": "sros-26-3",
    "ixr": "7250-ixr",
    "7250": "7250-ixr",
    "7250 ixr": "7250-ixr",
    "7250-ixr": "7250-ixr",
    "sar-gen2": "7705-sar-gen2",
    "sar gen2": "7705-sar-gen2",
    "7705-sar-gen2": "7705-sar-gen2",
    "7705 sar gen2": "7705-sar-gen2",
    "sar": "7705-sar",
    "7705": "7705-sar",
    "7705-sar": "7705-sar",
    "7705 sar": "7705-sar",
    "sas": "7210-sas",
    "7210": "7210-sas",
    "7210-sas": "7210-sas",
    "7210 sas": "7210-sas",
    "rn": "rn-sros",
    "rn sros": "rn-sros",
    "sros rn": "rn-sros",
    "release notes": "rn-sros",
    "release notes sros": "rn-sros",
    "rn-sros": "rn-sros",
    "rn srl": "rn-srl",
    "rn srlinux": "rn-srl",
    "srl rn": "rn-srl",
    "srlinux rn": "rn-srl",
    "release notes srlinux": "rn-srl",
    "rn-srl": "rn-srl",
    "rn sas": "rn-sas",
    "rn-sas": "rn-sas",
    "rn eda": "rn-eda",
    "rn-eda": "rn-eda",
    "eda": "rn-eda",
    "rn mag-c": "rn-mag-c",
    "rn magc": "rn-mag-c",
    "rn-mag-c": "rn-mag-c",
    "mag-c": "rn-mag-c",
    "magc": "rn-mag-c",
    "install": "install-guides",
    "install guide": "install-guides",
    "install guides": "install-guides",
    "installation": "install-guides",
    "chassis": "install-guides",
    "chassis guide": "install-guides",
    "install-guides": "install-guides",
}


PRODUCT_DISPLAY_NAMES: dict[str, str] = {
    "sros-26-3": "Nokia SR OS 26.3 (7750 SR / 7x50)",
    "srlinux-26-3": "Nokia SR Linux 26.3",
    "7250-ixr": "Nokia 7250 IXR 26.3 R1",
    "7705-sar-gen2": "Nokia 7705 SAR Gen2",
    "7705-sar": "Nokia 7705 SAR",
    "7210-sas": "Nokia 7210 SAS 26.3 R1",
    "nsp": "Nokia NSP",
    "rn-sros": "Nokia SR OS Release Notes",
    "rn-srl": "Nokia SR Linux Release Notes",
    "rn-sas": "Nokia 7210 SAS Release Notes",
    "rn-eda": "Nokia EDA Release Notes",
    "rn-mag-c": "Nokia MAG-c Release Notes",
    "install-guides": "Nokia Chassis Installation Guides",
}


RN_PRODUCTS: list[ReleaseNoteProduct] = [
    ReleaseNoteProduct("sros", "rn-sros", "Nokia SR OS"),
    ReleaseNoteProduct("srl", "rn-srl", "Nokia SR Linux"),
    ReleaseNoteProduct("sas", "rn-sas", "Nokia 7210 SAS"),
    ReleaseNoteProduct("mag-c", "rn-mag-c", "Nokia MAG-c"),
    ReleaseNoteProduct("eda", "rn-eda", "Nokia EDA"),
]


def normalize_alias(value: str) -> str:
    return re.sub(r"[\s_]+", " ", value.strip().lower())


def resolve_product(product_line: str | None) -> str | None:
    """Resolve a product slug or human-friendly alias to the canonical slug."""
    if not product_line:
        return None
    normalized_spaces = normalize_alias(product_line)
    if normalized_spaces in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[normalized_spaces]
    normalized_no_hyphen = re.sub(r"[\s_\-]+", " ", product_line.strip().lower())
    if normalized_no_hyphen in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[normalized_no_hyphen]
    return normalized_spaces
