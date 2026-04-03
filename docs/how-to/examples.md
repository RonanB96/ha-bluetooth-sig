# Examples

Practical examples showing how to use Bluetooth SIG Devices sensor entities in Home Assistant.

## Automations

### Alert when battery is low

Trigger a notification when any Bluetooth SIG device's battery drops below 20%.

```yaml
alias: "Bluetooth SIG: Low battery alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.heart_rate_monitor_battery_level
    below: 20
action:
  - service: notify.mobile_app
    data:
      title: "Low battery"
      message: "{{ trigger.to_state.name }} is at {{ trigger.to_state.state }}%"
```

### Log high CO₂ levels

Record a warning when CO₂ concentration exceeds 1000 ppm (a common ventilation threshold).

```yaml
alias: "Bluetooth SIG: High CO2 warning"
trigger:
  - platform: numeric_state
    entity_id: sensor.air_quality_sensor_co2_concentration
    above: 1000
action:
  - service: persistent_notification.create
    data:
      title: "High CO₂"
      message: >
        CO₂ is {{ states('sensor.air_quality_sensor_co2_concentration') }} ppm.
        Consider ventilating the room.
```

### Capture heart rate during exercise

Log heart rate to a helper when an exercise session is active.

```yaml
alias: "Bluetooth SIG: Log heart rate"
trigger:
  - platform: state
    entity_id: sensor.heart_rate_monitor_heart_rate
action:
  - service: input_number.set_value
    target:
      entity_id: input_number.current_heart_rate
    data:
      value: "{{ trigger.to_state.state | int }}"
```

## Dashboard cards

### Environment monitoring card

Display temperature, humidity, and CO₂ side by side using a Entities card.

```yaml
type: entities
title: Office environment
entities:
  - entity: sensor.office_sensor_temperature
  - entity: sensor.office_sensor_humidity
  - entity: sensor.office_sensor_co2_concentration
  - entity: sensor.office_sensor_battery_level
```

### History graph for a temperature sensor

Show a 24-hour history graph for an environment sensor.

```yaml
type: history-graph
entities:
  - entity: sensor.env_sensor_temperature
  - entity: sensor.env_sensor_humidity
hours_to_show: 24
title: Temperature & Humidity — Last 24h
```

### Heart rate monitor card

Display real-time and historical heart rate data.

```yaml
type: vertical-stack
cards:
  - type: entity
    entity: sensor.heart_rate_monitor_heart_rate
    name: Heart Rate
  - type: history-graph
    entities:
      - entity: sensor.heart_rate_monitor_heart_rate
    hours_to_show: 1
    title: Heart Rate — Last hour
```

## Statistics and long-term tracking

Entities with a `state_class` of `measurement` automatically accumulate statistics in Home Assistant (min, max, mean, standard deviation). You can view these in:

- **Developer Tools → Statistics** — view and manage all statistics
- **History** panel — view historical values for any entity
- **Statistic** card — display aggregated values in dashboards

Energy entities with `state_class: total_increasing` (e.g., energy expended, cumulative step counts) integrate with Home Assistant's Energy dashboard.
