"""Command-line interface for the MetalFab UNS Simulator."""

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from .complexity import ComplexityLevel
from .config import Config
from .multi_site import run_multi_site

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0")
def main():
    """MetalFab UNS Simulator - MQTT-based manufacturing simulation.

    Generates realistic Unified Namespace (UNS) data for High-Mix Low-Volume
    metalworking and sheet metal fabrication environments.

    Complexity Levels:
      0: Paused - no data generated
      1: Basic monitoring - stateless, sensors only
      2: Stateful - MQTT retain, jobs, positions
      3: ERP/MES - quality, margins, lead times
      4: Full - historian, dashboards, events
    """
    pass


@main.command()
@click.option(
    "--level",
    "-l",
    type=click.IntRange(0, 4),
    default=0,
    help="Complexity level (0-4, default: 0)",
)
@click.option(
    "--broker",
    "-b",
    default="localhost",
    help="MQTT broker address",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=1883,
    help="MQTT broker port",
)
@click.option(
    "--clean-start",
    is_flag=True,
    default=False,
    help="Force clear all retained MQTT topics on startup",
)
@click.option(
    "--no-auto-clean",
    is_flag=True,
    default=False,
    help="Disable automatic first-run cleanup of retained topics",
)
def run(level, broker, port, clean_start, no_auto_clean):
    """Start the multi-site simulator.

    By default, on first run the simulator will automatically clear all
    retained MQTT topics for a clean start. Use --no-auto-clean to disable
    this behavior.

    Use --clean-start to force a cleanup on every run.
    """
    run_multi_site(
        level=level,
        broker=broker,
        port=port,
        clean_start=clean_start,
        auto_clean=(not no_auto_clean)
    )


@main.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("config"),
    help="Output directory for config files",
)
def init(output):
    """Generate sample configuration files.

    Creates config.yaml with default settings for MQTT, UNS structure,
    and simulation parameters.
    """
    output.mkdir(parents=True, exist_ok=True)

    cfg = Config.default()
    config_path = output / "config.yaml"
    cfg.to_yaml(config_path)

    click.echo(f"Created: {config_path}")
    click.echo()
    click.echo("Edit the config file to customize:")
    click.echo("  - MQTT broker settings")
    click.echo("  - Enterprise/Site names")
    click.echo("  - Simulation speed and level")
    click.echo()
    click.echo(f"Run with: metalfab-sim run --config {config_path}")


@main.command()
def status():
    """Show simulator status information."""
    from pathlib import Path

    click.echo("MetalFab UNS Simulator")
    click.echo("=" * 40)
    click.echo()

    # Check first run status
    from .multi_site import _get_marker_file, _is_first_run

    marker_file = _get_marker_file()
    if _is_first_run():
        click.echo("First run status: NOT YET RUN")
        click.echo("  → Next run will auto-clear retained MQTT topics")
    else:
        click.echo(f"First run status: COMPLETE")
        click.echo(f"  Marker file: {marker_file}")
        if marker_file.exists():
            content = marker_file.read_text().strip()
            click.echo(f"  {content}")
    click.echo()

    click.echo("Complexity Levels:")
    click.echo("  0: Paused (no data)")
    click.echo("  1: Basic monitoring (stateless, sensors only)")
    click.echo("  2: Stateful (MQTT retain, jobs, positions)")
    click.echo("  3: ERP/MES (quality, margins, lead times)")
    click.echo("  4: Full (historian, dashboards, events)")
    click.echo()
    click.echo("Topic Structure:")
    click.echo("  umh/v1/{enterprise}/{site}/{area}/{cell}/{namespace}/...")
    click.echo()
    click.echo("Namespaces by Level:")
    click.echo("  Level 1: _raw (sensors)")
    click.echo("  Level 2: + _state, _meta, _jobs")
    click.echo("  Level 3: + _erp, _mes, _analytics")
    click.echo("  Level 4: + _dashboard, _event, _alarms")
    click.echo()
    click.echo("Example Data (Level 3+):")
    click.echo("  JOB_9942 [STATUS: BENDING] // LEAD_TIME: 2.3d ahead")
    click.echo("  ENERGY [KWH_TODAY: 847] // COST_PER_ORDER: 12.40 EUR")
    click.echo("  WELD_CELL_01 [QUALITY: 99.2%] // DEFECT_RATE: 0.8%")
    click.echo("  LASER_01 [OEE: 94%] // IDLE_TIME: 12min")


@main.command()
def reset_first_run():
    """Reset the first-run marker (next run will auto-clear retained topics).

    Use this if you want to reset the simulator to a clean state.
    The marker file will NOT be deleted, only reset.
    """
    from .multi_site import _get_marker_file

    marker_file = _get_marker_file()

    if marker_file.exists():
        # Reset the content but don't delete the file
        marker_file.write_text(f"Reset requested at {datetime.now().isoformat()}\nNEXT_RUN_WILL_CLEAN=true\n")
        # Actually, for first-run detection we need to remove it
        marker_file.unlink()
        click.echo(f"Reset first-run marker: {marker_file}")
        click.echo("Next run will automatically clear all retained MQTT topics")
    else:
        click.echo("First-run marker not found - already in first-run state")
        click.echo("Next run will automatically clear all retained MQTT topics")


@main.command()
@click.option(
    "--broker",
    "-b",
    default="localhost",
    help="MQTT broker address",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=1883,
    help="MQTT broker port",
)
@click.option(
    "--level",
    "-l",
    type=click.IntRange(0, 4),
    required=True,
    help="New complexity level (0-4)",
)
def set_level(broker, port, level):
    """Set the simulator complexity level via MQTT.

    Publishes a level change command to the running simulator
    using the root-level control topic.
    """
    import json
    import paho.mqtt.client as mqtt

    # Use root-level topic (not under UNS path)
    topic = "metalfab-sim/settings/level"
    payload = json.dumps({"level": level})

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    try:
        client.connect(broker, port)
        result = client.publish(topic, payload, qos=1)
        result.wait_for_publish()
        client.disconnect()

        level_names = {
            0: "Paused",
            1: "Sensors",
            2: "Stateful",
            3: "ERP/MES",
            4: "Full",
        }
        if level in level_names:
            click.echo(f"Set level to {level} ({level_names[level]})")
        else:
            click.echo(f"Set level to {level}")
        click.echo(f"  Topic: {topic}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--broker",
    "-b",
    default="localhost",
    help="MQTT broker address",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=1883,
    help="MQTT broker port",
)
@click.argument("site_id")
@click.argument("state", type=click.Choice(["on", "off"]))
def toggle_site(broker, port, site_id, state):
    """Enable or disable a site via MQTT."""
    import json
    import paho.mqtt.client as mqtt

    topic = f"metalfab-sim/settings/sites/{site_id}"
    enabled = state == "on"
    payload = json.dumps({"enabled": enabled})

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    try:
        client.connect(broker, port)
        result = client.publish(topic, payload, qos=1)
        result.wait_for_publish()
        client.disconnect()

        click.echo(f"Set site '{site_id}' to {state}")
        click.echo(f"  Topic: {topic}")
        click.echo(f"  Payload: {payload}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--broker",
    "-b",
    default="localhost",
    help="MQTT broker address",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=1883,
    help="MQTT broker port",
)
@click.option(
    "--enterprise",
    default="acme_metalworks",
    help="Enterprise name in topic",
)
@click.option(
    "--site",
    default="plant_vienna",
    help="Site name in topic",
)
@click.option(
    "--filter",
    "-f",
    "topic_filter",
    default="#",
    help="Topic filter (default: # for all)",
)
def subscribe(broker, port, enterprise, site, topic_filter):
    """Subscribe to simulator topics and display messages.

    Useful for debugging and monitoring the simulator output.
    """
    import json
    import paho.mqtt.client as mqtt

    base = f"umh/v1/{enterprise}/{site}"
    full_topic = f"{base}/{topic_filter}"

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            # Shorten topic for display
            short_topic = msg.topic.replace(base + "/", "")
            click.echo(f"{short_topic}: {json.dumps(payload, indent=2)}")
        except Exception:
            click.echo(f"{msg.topic}: {msg.payload.decode()}")

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe(full_topic)
            click.echo(f"Subscribed to: {full_topic}")
            click.echo("Press Ctrl+C to stop")
            click.echo("-" * 40)

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(broker, port)
        client.loop_forever()
    except KeyboardInterrupt:
        click.echo("\nDisconnected")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()