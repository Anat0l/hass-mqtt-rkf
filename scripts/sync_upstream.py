#!/usr/bin/env python3
"""Copy the official Mosquitto add-on and keep one local change.

The released add-on metadata comes from home-assistant/addons. Since 7.1.3 the
build files live in home-assistant/app-mosquitto. This script combines those
two trees, points `image` at the prebuilt GHCR images for this repository, and
inserts a build step that comments out Mosquitto's rejection of SUBSCRIBE
packets whose packet identifier is 0.

The sync stops if that check is no longer exactly the expected three lines.
A newer official release is not published with a patch that did not apply.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/eclipse/mosquitto/"
    "v{version}/src/handle_subscribe.c"
)
MID_BLOCK = re.compile(
    r"^[ \t]*if\(mid == 0\)\{\r?\n"
    r"[ \t]*return MOSQ_ERR_MALFORMED_PACKET;\r?\n"
    r"[ \t]*\}\r?\n",
    re.MULTILINE,
)
CD_MARKER = "    && cd mosquitto \\\n"
PATCH = (
    "    # RKf: Mosquitto rejects SUBSCRIBE when the packet id is 0. Some clients send that.\n"
    "    && grep -q 'if(mid == 0){' src/handle_subscribe.c \\\n"
    "    && sed -i '/if(mid == 0){/,/^[[:space:]]*}/{s|^|// RKf |}' src/handle_subscribe.c \\\n"
    "    && ! grep -E -q '^[[:space:]]*if\\(mid == 0\\)\\{' src/handle_subscribe.c \\\n"
    "    && grep -q '// RKf' src/handle_subscribe.c \\\n"
)
IDENTITY = {
    "slug": "mosquitto-rkf",
    "name": "Mosquitto broker (RKf)",
    "description": "An Open Source MQTT broker (RKf)",
    "url": "https://github.com/Anat0l/hass-mqtt-rkf/tree/main/mosquitto",
}
IMAGE = "ghcr.io/anat0l/{arch}-addon-mosquitto-rkf"


def read_text(path: Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")


def mosquitto_version(build_yaml: str) -> str:
    match = re.search(r"^  MOSQUITTO_VERSION:\s*(\S+)\s*$", build_yaml, re.MULTILINE)
    if not match:
        raise SystemExit("MOSQUITTO_VERSION was not found in build.yaml")
    return match.group(1)


def mosquitto_version_from_dockerfile(dockerfile: str) -> str:
    match = re.search(r"^ARG MOSQUITTO_VERSION=(\S+)\s*$", dockerfile, re.MULTILINE)
    if not match:
        raise SystemExit("MOSQUITTO_VERSION was not found in the Dockerfile")
    return match.group(1)


def base_image(dockerfile: str) -> str:
    match = re.search(r"^ARG BUILD_FROM=(\S+)\s*$", dockerfile, re.MULTILINE)
    if not match:
        raise SystemExit("BUILD_FROM was not found in the Dockerfile")
    image = match.group(1)
    if image.startswith("$"):
        raise SystemExit(f"BUILD_FROM is not a concrete image: {image}")
    return image


def write_build_yaml(dest: Path, image: str) -> None:
    """Tell the legacy add-on builder which base image to use.

    Without build.yaml it ignores the Dockerfile default and uses
    ghcr.io/home-assistant/<arch>-base:latest. The current Dockerfile is
    written for the Debian image named by ARG BUILD_FROM.
    """
    if (dest / "build.yaml").is_file() or (dest / "build.yml").is_file():
        return
    quoted = image.replace('"', "")
    text = (
        "build_from:\n"
        f'  aarch64: "{quoted}"\n'
        f'  amd64: "{quoted}"\n'
    )
    (dest / "build.yaml").write_bytes(text.encode("utf-8"))


def addon_version(config_yaml: str) -> str:
    match = re.search(r"^version:\s*(\S+)\s*$", config_yaml, re.MULTILINE)
    if not match:
        raise SystemExit("version was not found in config.yaml")
    return match.group(1)


def assert_patch_still_applies(version: str) -> None:
    url = SOURCE_URL.format(version=version)
    request = urllib.request.Request(url, headers={"User-Agent": "hass-mqtt-rkf-sync"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            source = response.read().decode("utf-8")
    except Exception as exc:
        raise SystemExit(f"Cannot read Mosquitto {version} source ({url}): {exc}") from exc
    found = len(MID_BLOCK.findall(source))
    if found != 1:
        raise SystemExit(
            f"Mosquitto {version} has {found} copies of the packet-id check, expected 1. "
            "The patch no longer matches upstream, so this sync was not published."
        )


def rewrite_config(text: str) -> str:
    rewritten: list[str] = []
    seen = {key: False for key in IDENTITY}
    wrote_image = False
    for line in text.splitlines(keepends=True):
        if line.startswith("image:"):
            ending = "\n" if line.endswith("\n") else ""
            rewritten.append(f"image: {IMAGE}{ending}")
            wrote_image = True
            continue
        key = line.split(":", 1)[0]
        if key in IDENTITY:
            ending = "\n" if line.endswith("\n") else ""
            rewritten.append(f"{key}: {IDENTITY[key]}{ending}")
            seen[key] = True
            continue
        rewritten.append(line)
    missing = [key for key, present in seen.items() if not present]
    if missing:
        raise SystemExit(f"config.yaml is missing: {', '.join(missing)}")
    if not wrote_image:
        raise SystemExit(
            "Official config.yaml has no image: line. "
            "Refusing to publish, because Home Assistant would compile the add-on locally."
        )
    return "".join(rewritten)


def rewrite_dockerfile(text: str) -> str:
    found = text.count(CD_MARKER)
    if found != 1:
        raise SystemExit(f"Expected one 'cd mosquitto' build step, found {found}")
    if "RKf" in text:
        raise SystemExit("Upstream Dockerfile already contains an RKf marker")
    return text.replace(CD_MARKER, CD_MARKER + PATCH, 1)


STORE_FILES = ("config.yaml", "CHANGELOG.md", "DOCS.md", "README.md", "icon.png", "logo.png")


def overlay_store(store: Path, dest: Path) -> None:
    for name in STORE_FILES:
        source = store / name
        if source.is_file():
            shutil.copy2(source, dest / name)
    translations = store / "translations"
    if not translations.is_dir():
        return
    destination = dest / "translations"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(translations, destination)


def sync(store: Path, sources: Path, dest: Path) -> str:
    if not (store / "config.yaml").is_file():
        raise SystemExit(f"Add-on metadata is missing config.yaml: {store}")
    if not (sources / "Dockerfile").is_file():
        raise SystemExit(f"Build sources are missing a Dockerfile: {sources}")
    if dest.resolve() in {store.resolve(), sources.resolve()}:
        raise SystemExit("Destination must be different from the store and the sources")

    dockerfile_text = read_text(sources / "Dockerfile")
    if (sources / "build.yaml").is_file():
        engine_version = mosquitto_version(read_text(sources / "build.yaml"))
    else:
        engine_version = mosquitto_version_from_dockerfile(dockerfile_text)
    addon = addon_version(read_text(store / "config.yaml"))
    assert_patch_still_applies(engine_version)

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(sources, dest)
    overlay_store(store, dest)

    config_path = dest / "config.yaml"
    config_path.write_bytes(rewrite_config(read_text(config_path)).encode("utf-8"))
    dockerfile_path = dest / "Dockerfile"
    dockerfile_path.write_bytes(rewrite_dockerfile(read_text(dockerfile_path)).encode("utf-8"))
    if not (sources / "build.yaml").is_file() and not (sources / "build.yml").is_file():
        write_build_yaml(dest, base_image(dockerfile_text))

    config = read_text(config_path)
    dockerfile = read_text(dockerfile_path)
    if "slug: mosquitto-rkf" not in config or f"image: {IMAGE}" not in config:
        raise SystemExit("config.yaml was not rewritten correctly")
    if "ghcr.io/home-assistant/" in config or re.search(r"^image:\s*homeassistant/", config, re.MULTILINE):
        raise SystemExit("official image name was not replaced")
    if PATCH not in dockerfile:
        raise SystemExit("Dockerfile patch was not inserted")
    if addon_version(config) != addon:
        raise SystemExit("Add-on version changed while rewriting config.yaml")
    if not (dest / "build.yaml").is_file() and not (dest / "build.yml").is_file():
        raise SystemExit("build.yaml is missing, so the builder would use the wrong base image")
    return addon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    version = sync(args.store, args.sources, args.dest)
    print(f"Synced Mosquitto add-on {version}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc.code, file=sys.stderr)
        raise
